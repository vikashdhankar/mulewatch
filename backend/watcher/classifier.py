"""The watcher's text classifier and its LLM second opinion.

Model choice, in order:
  1. the best saved research model: the run in research/results/runs/ with the highest macro-F1 on its test
     set whose checkpoint exists in research/checkpoints/ (`python -m models.run ... --save-model`);
     TF-IDF+LR pickles and fine-tuned transformers are both read;
  2. otherwise TF-IDF + LR (research/models/tfidf_lr.py, research config) trained once and cached, on:
     research gold labels joined with redacted posts, plus officers' decisions on watcher alerts; if that is
     under MIN_REAL examples, a bootstrap set is added (research synthetic posts and the backend's template
     corpus, weakly labelled by the discovery category lexicon). The bootstrap model is a stop-gap.
Research models predict the research classes (common/labels.py); `classifier.class_map` turns them into
watcher categories. Every text is redacted before it reaches a model or the LLM."""
import json
import logging
import pickle
import re
import time
from collections import Counter
from pathlib import Path

from .config import CATEGORIES, FRAUD_CATEGORIES, path

log = logging.getLogger("watcher.classifier")
MIN_REAL = 200

DESCRIPTIONS = {
    "payout_mule": "Recruits people or accounts to receive and pass on money: payout/pay-in, gaming or betting "
                   "settlement, commission per transaction, renting out one's own account",
    "account_sale": "Sells or rents bank accounts, current/savings/corporate accounts, full kits (passbook, "
                    "ATM card, net banking, SIM) or cards",
    "usdt_p2p": "Buys or sells USDT/crypto for rupees peer-to-peer (P2P, F2F, Binance), cash-out rails",
    "crypto_investment_scam": "Promises guaranteed or daily profits from crypto, forex or trading investments",
    "task_job_scam": "Part-time job, task or work-from-home offers with daily payments that lead to fraud",
    "legit_finance": "Legitimate finance: market news, bank or regulator updates, investment education",
    "unrelated": "Anything else, including warnings and awareness posts about fraud",
}


def _lexicon():
    from collect.discover_channels import CATEGORY_TERMS
    rx = []
    for cat, terms in CATEGORY_TERMS.items():
        for t in terms:
            rx.append((cat, t, re.compile(r"(?<!\w)" + re.escape(t) + r"(?!\w)", re.I)))
    return rx


_LEX = None


def lexicon_terms(text: str) -> dict[str, list[str]]:
    """Discovery category terms found in the text, by category (a longer term hides a shorter one in it)."""
    global _LEX
    if _LEX is None:
        _LEX = _lexicon()
    hits = [(c, t) for c, t, rx in _LEX if rx.search(text or "")]
    terms = {t for _, t in hits}
    out: dict[str, list[str]] = {}
    for c, t in hits:
        if not any(t != o and t in o for o in terms):
            out.setdefault(c, []).append(t)
    return out


# ----------------------------------------------------------------------------- models

class SklearnModel:
    """A fitted scikit-learn pipeline with predict_proba (research TF-IDF + LR)."""

    def __init__(self, pipe, class_map: dict, name: str, max_cues: int = 6):
        self.pipe, self.name, self.max_cues = pipe, name, max_cues
        self.classes = list(pipe.classes_)
        self.map = {c: class_map.get(c, c) for c in self.classes}
        bad = sorted({v for v in self.map.values() if v not in CATEGORIES})
        if bad:
            raise ValueError(f"{name}: classes {bad} have no watcher category; add them to classifier.class_map")

    def predict(self, text: str) -> tuple[dict, list[str]]:
        proba = self.pipe.predict_proba([text])[0]
        probs = dict.fromkeys(CATEGORIES, 0.0)
        for c, pr in zip(self.classes, proba):
            probs[self.map[c]] += float(pr)
        cat = max(probs, key=probs.get)
        if sum(probs[c] for c in FRAUD_CATEGORIES) >= 0.5:
            cat = max(FRAUD_CATEGORIES, key=probs.get)
        return probs, cues(text, cat, self.model_cues(text, cat), self.max_cues)

    def model_cues(self, text: str, category: str) -> list[str]:
        """Words (from the word n-gram block) that weigh most towards the category in this text."""
        feats, clf = self.pipe.named_steps.get("features"), self.pipe.named_steps.get("clf")
        if feats is None or not hasattr(clf, "coef_"):
            return []
        offset, word = 0, None
        for name, tr in feats.transformer_list:
            if name == "word":
                word = tr
                break
            offset += len(tr.vocabulary_)
        if word is None:
            return []
        x = word.transform([text]).tocoo()
        coef = clf.coef_
        rows = [i for i, c in enumerate(self.classes) if self.map[c] == category]
        if not rows:
            return []
        vocab = word.get_feature_names_out()
        scored = []
        for j, v in zip(x.col, x.data):
            if coef.shape[0] == 1:          # binary LR: one row of weights for classes_[1]
                w = max(coef[0, offset + j] * (1 if r == 1 else -1) for r in rows)
            else:
                w = max(coef[r, offset + j] for r in rows)
            if w > 0:
                scored.append((v * w, vocab[j]))
        scored.sort(reverse=True)
        return [t for _, t in scored if not re.fullmatch(r"\[\w+\]|\d+", t)]


class HFModel:
    """A fine-tuned transformer saved by research/models/hf_finetune.py."""

    def __init__(self, ckpt: Path, class_map: dict, name: str, max_cues: int = 6):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(ckpt)
        self.model = AutoModelForSequenceClassification.from_pretrained(ckpt).eval()
        self.classes = [self.model.config.id2label[i] for i in range(self.model.config.num_labels)]
        self.map = {c: class_map.get(c, c) for c in self.classes}
        self.name, self.max_cues = name, max_cues

    def predict(self, text: str) -> tuple[dict, list[str]]:
        with self.torch.no_grad():
            enc = self.tok([text], truncation=True, max_length=256, return_tensors="pt")
            proba = self.torch.softmax(self.model(**enc).logits, -1)[0].tolist()
        probs = dict.fromkeys(CATEGORIES, 0.0)
        for c, pr in zip(self.classes, proba):
            probs[self.map.get(c, "unrelated")] += pr
        cat = max(FRAUD_CATEGORIES, key=probs.get) if sum(probs[c] for c in FRAUD_CATEGORIES) >= 0.5 \
            else max(probs, key=probs.get)
        return probs, cues(text, cat, [], self.max_cues)


_TOKEN = re.compile(r"(?u)\b\w\w+\b")       # scikit-learn's default token pattern


def as_written(text: str, term: str) -> str:
    """The words of the text a model n-gram came from. The tokenizer splits Devanagari at vowel signs
    ("एटीएम" -> "एट", "एम"), so the n-gram itself can be unreadable; '' if it is not in the text."""
    words = text.split()
    frags = [(i, f.lower()) for i, w in enumerate(words) for f in _TOKEN.findall(w)]
    want = term.lower().split()
    for k in range(len(frags) - len(want) + 1):
        if [f for _, f in frags[k:k + len(want)]] == want:
            span = words[frags[k][0]:frags[k + len(want) - 1][0] + 1]
            return " ".join(w.strip(".,;:!?()\"'“”‘’।") for w in span)
    return ""


def cues(text: str, category: str, model_words: list[str], n: int) -> list[str]:
    """Explanation: lexicon terms of the category, then the model's top words as written in the post, distinct."""
    out: list[str] = []
    readable = [w for w in (as_written(text, t) for t in model_words)
                if w and not re.search(r"[\d\[\]]", w) and len(w) >= 3]
    for t in lexicon_terms(text).get(category, []) + readable:       # the category's own terms first
        low = t.lower()
        if len(low) < 3 or any(low == o.lower() or low in o.lower().split() for o in out):
            continue
        out = [o for o in out if o.lower() not in low.split()]       # "net" gives way to "net banking"
        out.append(t)
    return out[:n]


def best_saved(research_dir: Path, class_map: dict, max_cues: int = 6):
    """The saved research model with the best macro-F1 on its test set, or None."""
    runs = []
    for f in (research_dir / "results" / "runs").glob("*.json"):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if r.get("type") in ("tfidf_lr", "hf") and r.get("test_set") == "test" and "macro_f1" in r:
            runs.append(r)
    for r in sorted(runs, key=lambda r: -r["macro_f1"]):
        ckpt = research_dir / "checkpoints" / f"{r['model']}_{r['split']}_s{r['seed']}"
        if not ckpt.exists():
            continue
        name = f"{r['model']} ({r['split']}, seed {r['seed']}, test macro-F1 {r['macro_f1']:.3f})"
        try:
            if r["type"] == "tfidf_lr":
                with open(ckpt, "rb") as fh:          # written by research/models/tfidf_lr.py on this machine
                    return SklearnModel(pickle.load(fh), class_map, name, max_cues)
            return HFModel(ckpt, class_map, name, max_cues)
        except Exception as e:                       # missing transformers, unreadable checkpoint: try the next
            log.warning("cannot load %s: %s", ckpt.name, type(e).__name__)
    return None


# ----------------------------------------------------------------------------- fallback

def _research_examples(research_dir: Path, redactor, class_map: dict) -> list[tuple[str, str]]:
    from common.io import read_jsonl
    from common.text import model_input
    out = []
    gold, posts = research_dir / "store/annotations/gold.jsonl", research_dir / "store/redacted/posts.jsonl"
    if gold.exists() and posts.exists():
        labels = {g["post_id"]: g["label"] for g in read_jsonl(gold)}
        for p in read_jsonl(posts):
            if p["post_id"] in labels and class_map.get(labels[p["post_id"]], labels[p["post_id"]]) in CATEGORIES:
                out.append((model_input(p), class_map.get(labels[p["post_id"]], labels[p["post_id"]])))
    # officers' decisions on watcher alerts (app.watcher_api.export_feedback)
    fb_dec, fb_posts = research_dir / "store/annotations/watcher/decisions.jsonl", \
        research_dir / "store/annotations/watcher/posts.jsonl"
    if fb_dec.exists() and fb_posts.exists():
        cats = {g["post_id"]: g.get("category") for g in read_jsonl(fb_dec) if g.get("category") in CATEGORIES}
        out += [(model_input(p), cats[p["post_id"]]) for p in read_jsonl(fb_posts) if p["post_id"] in cats]
    return out


def bootstrap_examples(redactor, class_map: dict) -> list[tuple[str, str]]:
    """Template data only: research synthetic posts and the backend's training corpus, weakly labelled."""
    from common.text import model_input
    from tools.synthetic import make
    from .research import BACKEND
    out = []
    for p in make(1500, 15, 60, seed=7):
        r = redactor.redact_post(p)
        out.append((model_input(r), class_map.get(p["_label"], p["_label"])))
    corpus = BACKEND / "training" / "training_data.jsonl"
    for line in corpus.read_text(encoding="utf-8").splitlines() if corpus.exists() else []:
        row = json.loads(line)
        text, _ = redactor.redact(row["text"])
        hits = lexicon_terms(text)
        if int(row["label"]) == 1:
            fraud = Counter({c: len(hits.get(c, [])) for c in FRAUD_CATEGORIES})
            cat = fraud.most_common(1)[0][0] if fraud.most_common(1)[0][1] else "account_sale"
        else:
            cat = "legit_finance" if hits.get("legit_finance") else "unrelated"
        out.append((text, cat))
    return out


def train_fallback(cfg: dict, redactor) -> SklearnModel:
    import yaml
    from models.tfidf_lr import TfidfLR
    research_dir = path(cfg["research_dir"])
    cmap = cfg["classifier"]["class_map"]
    real = _research_examples(research_dir, redactor, cmap)
    data, source = list(real), f"{len(real)} labelled posts"
    if len(real) < MIN_REAL:
        boot = bootstrap_examples(redactor, cmap)
        data += boot
        source += f" + {len(boot)} bootstrap template posts (weak labels)"
    params = yaml.safe_load((research_dir / "models/configs/tfidf_lr.yaml").read_text(encoding="utf-8"))["params"]
    texts, labels = zip(*data)
    m = TfidfLR(params).fit(list(texts), list(labels))
    name = f"tfidf_lr fallback ({source})"
    cache = path(cfg["classifier"]["fallback_cache"])
    cache.parent.mkdir(parents=True, exist_ok=True)
    with open(cache, "wb") as fh:
        pickle.dump({"pipe": m.pipe, "name": name, "trained_at": time.time()}, fh)
    log.info("trained %s", name)
    return SklearnModel(m.pipe, {}, name, cfg["classifier"]["max_cues"])


def load_model(cfg: dict, redactor, retrain: bool = False):
    c = cfg["classifier"]
    if c.get("prefer_saved_model", True):
        m = best_saved(path(cfg["research_dir"]), c["class_map"], c["max_cues"])
        if m:
            return m
    cache = path(c["fallback_cache"])
    if cache.exists() and not retrain:
        with open(cache, "rb") as fh:                 # written by train_fallback above
            d = pickle.load(fh)
        return SklearnModel(d["pipe"], {}, d["name"], c["max_cues"])
    return train_fallback(cfg, redactor)


# ----------------------------------------------------------------------------- LLM second opinion

SYSTEM = """You classify public Telegram posts from India (English, Hindi or Hinglish) for a police team that \
looks for money-mule and fraud advertising. Phone numbers, UPI IDs, accounts, cards, links and usernames have \
been replaced by placeholders such as [PHONE] or [UPI]. Text after [IMAGE TEXT] was read from an image by OCR.

Categories:
{cats}

Answer with JSON only, exactly like {{"category": "<name>"}}, using one of the names above."""


def parse_category(text: str) -> str | None:
    m = re.search(r"\{.*?\}", text or "", re.S)
    if m:
        try:
            c = str(json.loads(m.group(0)).get("category", "")).strip().lower()
            if c in CATEGORIES:
                return c
        except (ValueError, AttributeError):
            pass
    hits = [c for c in CATEGORIES if c in (text or "").lower()]
    return hits[0] if len(hits) == 1 else None


class LLMOpinion:
    """Second opinion through research/common/llm_client.py (OpenAI-compatible, local unless allowed)."""

    def __init__(self, llm_cfg: dict, client=None):
        self.cfg, self.until = llm_cfg, 0.0
        if client is None:
            import yaml
            from common.llm_client import LLMClient
            p = yaml.safe_load(path(llm_cfg["config"]).read_text(encoding="utf-8"))["params"]
            client = LLMClient(p["model"], p.get("base_url"), allow_remote=p.get("allow_remote", False),
                               timeout=llm_cfg.get("timeout_s", 20), retries=1, extra_body=p.get("extra_body"))
        self.client = client
        self.system = SYSTEM.format(cats="\n".join(f"- {c}: {d}" for c, d in DESCRIPTIONS.items()))

    def __call__(self, text: str) -> str | None:
        if time.monotonic() < self.until:
            return None
        try:
            out, _, _ = self.client.chat([{"role": "system", "content": self.system},
                                          {"role": "user", "content": text[:1500]}], temperature=0.0, max_tokens=24)
        except Exception as e:
            self.until = time.monotonic() + self.cfg.get("cooldown_s", 300)
            log.warning("LLM second opinion unavailable (%s); skipping it for %ss", type(e).__name__,
                        self.cfg.get("cooldown_s", 300))
            return None
        return parse_category(out)


def make_llm(cfg: dict):
    if not cfg["llm"].get("enabled", True):
        return None
    try:
        return LLMOpinion(cfg["llm"])
    except (PermissionError, OSError, KeyError, ValueError) as e:
        log.warning("LLM second opinion off: %s", e)
        return None
