"""Perturb test posts the way sellers dodge filters, and measure how much each baseline's F1 drops.

    python -m robustness.attacks --config models/configs/tfidf_lr.yaml --split time_channel
    python -m robustness.attacks --config models/configs/xlmr.yaml --attacks char,translit,emoji,paraphrase \
        --paraphrase-config models/configs/llm_zeroshot.yaml --only-suspicious

Attacks (placeholders such as [PHONE] are never touched):
  char        leetspeak (acc0unt), Cyrillic/Greek look-alike letters, zero-width characters inside words,
              dotted letters (a.t.m); Devanagari words get zero-width joiners and swapped vowel signs
  translit    Devanagari -> Roman (Hinglish spelling); in Roman text, domain words -> Devanagari
  emoji       keywords -> emoji (bank -> 🏦, card -> 💳, paise -> 💰), existing emoji -> look-alike emoji
  paraphrase  LLM rewrite with the same meaning, language mix and placeholders (cached in store/)

The model is trained on the clean train set once, then scored on the clean test set and on each
attacked copy. Results: research/results/robustness.{csv,tex} (macro-F1 clean vs attacked, absolute
and relative drop, suspicious-vs-not F1 drop, share of posts the attack changed).
"""
import argparse
import hashlib
import json
import random
import re
from pathlib import Path

from common.io import iter_jsonl, write_jsonl
from common.labels import SUSPICIOUS
from common.results import RESULTS_DIR, write_table

_PLACEHOLDER = re.compile(r"(\[(?:PHONE|UPI|ACCOUNT|CARD|ID|EMAIL|URL|HANDLE|IMAGE TEXT)\])")
_DEV = re.compile(r"[ऀ-ॿ]")
# a word: letters plus Devanagari vowel signs, virama and nukta (which \w alone splits words on)
WORD = re.compile(r"(?:[^\W\d_]|[\u0900-\u0963\u0971-\u097F\u200c\u200d])+")


def _map_outside_placeholders(text: str, fn) -> str:
    parts = _PLACEHOLDER.split(text or "")
    return "".join(p if i % 2 else fn(p) for i, p in enumerate(parts))


# ----------------------------------------------------------------------------- character substitution

LEET = {"a": ["4", "@"], "e": ["3"], "i": ["1", "!"], "o": ["0"], "s": ["5", "$"], "t": ["7"], "l": ["1"], "b": ["8"]}
HOMOGLYPH = {"a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у", "i": "і", "k": "κ", "n": "п",
             "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М", "O": "О", "P": "Р", "T": "Т"}
ZW = ["​", "‌", "‍"]
MATRA_SWAP = {"ि": "ी", "ी": "ि", "ु": "ू", "ू": "ु", "े": "ै", "ो": "ौ"}


def _perturb_latin_word(w: str, rng: random.Random) -> str:
    kind = rng.choice(["leet", "homoglyph", "zw", "dots"])
    chars = list(w)
    idx = [i for i, c in enumerate(chars) if c.isalpha()]
    if not idx:
        return w
    if kind == "dots" and len(w) <= 5:
        return ".".join(chars)
    if kind == "zw":
        i = rng.randrange(1, len(chars)) if len(chars) > 1 else 1
        return "".join(chars[:i]) + rng.choice(ZW) + "".join(chars[i:])
    table = LEET if kind == "leet" else HOMOGLYPH
    cand = [i for i in idx if (chars[i].lower() if kind == "leet" else chars[i]) in table]
    if not cand:
        return w[:1] + rng.choice(ZW) + w[1:]
    for i in rng.sample(cand, max(1, len(cand) // 2)):
        sub = table[chars[i].lower()] if kind == "leet" else table[chars[i]]
        chars[i] = rng.choice(sub) if isinstance(sub, list) else sub
    return "".join(chars)


def _perturb_devanagari_word(w: str, rng: random.Random) -> str:
    swaps = [i for i, c in enumerate(w) if c in MATRA_SWAP]
    if swaps and rng.random() < 0.5:
        i = rng.choice(swaps)
        return w[:i] + MATRA_SWAP[w[i]] + w[i + 1:]
    i = rng.randrange(1, len(w)) if len(w) > 1 else 1
    return w[:i] + rng.choice(ZW[1:]) + w[i:]


def char_substitution(text: str, rng: random.Random, rate: float = 0.3) -> str:
    def fn(seg):
        def word(m):
            w = m.group(0)
            if len(w) < 3 or rng.random() > rate:
                return w
            return _perturb_devanagari_word(w, rng) if _DEV.search(w) else _perturb_latin_word(w, rng)
        return WORD.sub(word, seg)
    return _map_outside_placeholders(text, fn)


# ----------------------------------------------------------------------------- transliteration

_VOWELS = {"अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri", "ए": "e", "ऐ": "ai",
           "ओ": "o", "औ": "au", "ऑ": "o", "ॲ": "e"}
_MATRAS = {"ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
           "ॉ": "o", "ॅ": "e"}
_CONS = {"क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
         "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
         "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
         "ष": "sh", "स": "s", "ह": "h", "क़": "q", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "d", "ढ़": "rh", "फ़": "f",
         "य़": "y"}
_NUKTA_FORMS = {"क": "q", "ख": "kh", "ग": "g", "ज": "z", "ड": "d", "ढ": "rh", "फ": "f"}
_SIGNS = {"ं": "n", "ँ": "n", "ः": "h", "्": "", "़": "", "।": ".", "॥": "."}


def devanagari_to_roman(text: str) -> str:
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c in _CONS:
            nxt = text[i + 1] if i + 1 < n else ""
            if nxt == "़":
                out.append(_NUKTA_FORMS.get(c, _CONS[c]))
                i += 1
                nxt = text[i + 1] if i + 1 < n else ""
            else:
                out.append(_CONS[c])
            if nxt in _MATRAS:
                out.append(_MATRAS[nxt])
                i += 1
            elif nxt == "्":
                i += 1
            else:
                # inherent vowel, dropped at the end of a word (schwa deletion): "kamal", not "kamala"
                after = text[i + 1] if i + 1 < n else ""
                if after and (after in _CONS or after in _SIGNS and after not in "।॥"):
                    out.append("a")
        elif c in _VOWELS:
            out.append(_VOWELS[c])
        elif c in _MATRAS:
            out.append(_MATRAS[c])
        elif c in _SIGNS:
            out.append(_SIGNS[c])
        elif "०" <= c <= "९":
            out.append(str(ord(c) - 0x0966))
        else:
            out.append(c)
        i += 1
    return "".join(out)


ROMAN_TO_DEV = {
    "account": "अकाउंट", "accounts": "अकाउंट्स", "bank": "बैंक", "card": "कार्ड", "cards": "कार्ड्स", "atm": "एटीएम",
    "khata": "खाता", "kit": "किट", "kits": "किट्स", "current": "करंट", "savings": "सेविंग्स", "saving": "सेविंग",
    "sale": "सेल", "paisa": "पैसा", "paise": "पैसे", "kamao": "कमाओ", "daily": "डेली", "rent": "रेंट",
    "commission": "कमीशन", "contact": "कॉन्टैक्ट", "call": "कॉल", "whatsapp": "व्हाट्सएप", "telegram": "टेलीग्राम",
    "upi": "यूपीआई", "online": "ऑनलाइन", "job": "जॉब", "work": "वर्क", "earn": "अर्न", "money": "मनी",
    "cash": "कैश", "holder": "होल्डर", "holders": "होल्डर्स", "corporate": "कॉर्पोरेट", "firm": "फर्म",
    "banking": "बैंकिंग", "sim": "सिम", "passbook": "पासबुक", "available": "अवेलेबल", "urgent": "अर्जेंट",
    "ready": "रेडी", "price": "प्राइस", "kyc": "केवाईसी", "debit": "डेबिट", "credit": "क्रेडिट", "chahiye": "चाहिए",
    "milega": "मिलेगा", "hai": "है", "karo": "करो", "aur": "और", "buy": "बाय", "sell": "सेल", "home": "होम",
}


def roman_to_devanagari_words(text: str) -> str:
    return re.sub(r"[A-Za-z]+", lambda m: ROMAN_TO_DEV.get(m.group(0).lower(), m.group(0)), text)


def transliterate(text: str, rng: random.Random | None = None) -> str:
    def fn(seg):
        return devanagari_to_roman(seg) if _DEV.search(seg) else roman_to_devanagari_words(seg)
    return _map_outside_placeholders(text, fn)


# ----------------------------------------------------------------------------- emoji

KEYWORD_EMOJI = {
    "bank": "🏦", "बैंक": "🏦", "card": "💳", "cards": "💳", "atm": "💳", "कार्ड": "💳", "एटीएम": "💳",
    "money": "💰", "cash": "💵", "paise": "💰", "paisa": "💰", "पैसे": "💰", "पैसा": "💰", "rupees": "₹", "rs": "₹",
    "call": "📞", "phone": "📱", "mobile": "📱", "whatsapp": "📲", "contact": "📞", "कॉल": "📞", "sim": "📶",
    "telegram": "✈️", "daily": "📅", "roz": "📅", "earn": "🤑", "kamao": "🤑", "profit": "📈", "fast": "⚡",
    "urgent": "🚨", "home": "🏠", "ghar": "🏠", "free": "🆓", "new": "🆕", "ok": "👌", "kit": "🧰", "passbook": "📒",
    "account": "🏧", "khata": "📒", "खाता": "📒", "gift": "🎁",
}
EMOJI_SWAP = {"🔥": "💯", "💯": "🔥", "✅": "☑️", "☑️": "✅", "💰": "💵", "💵": "💰", "📞": "☎️", "☎️": "📞",
              "👉": "➡️", "➡️": "👉", "🏦": "🏛️", "💳": "🪪", "🤑": "💸", "💸": "🤑", "⚡": "🚀", "🚀": "⚡",
              "📲": "📱", "📱": "📲", "❤️": "💖", "👍": "👌"}
_EMOJI_SWAP_RX = re.compile("|".join(sorted(map(re.escape, EMOJI_SWAP), key=len, reverse=True)))


def emoji_swap(text: str, rng: random.Random, rate: float = 0.7) -> str:
    def fn(seg):
        seg = _EMOJI_SWAP_RX.sub(lambda m: EMOJI_SWAP[m.group(0)], seg)
        return WORD.sub(lambda m: KEYWORD_EMOJI[m.group(0).lower()]
                      if m.group(0).lower() in KEYWORD_EMOJI and rng.random() < rate else m.group(0), seg)
    return _map_outside_placeholders(text, fn)


# ----------------------------------------------------------------------------- LLM paraphrase

PARAPHRASE_PROMPT = """Rewrite the following social-media post in different words. Keep the same meaning, \
the same language and script mix (English, Hindi or Hinglish), and keep every placeholder in square \
brackets such as [PHONE] or [UPI] exactly as it is. Reply with the rewritten post only.

Post:
{text}"""


class Paraphraser:
    """Paraphrases through the LLM endpoint of a model config; caches every answer on disk."""

    def __init__(self, llm_params: dict, cache_path: str = "store/robustness/paraphrase_cache.jsonl"):
        from common.llm_client import LLMClient
        self.p = llm_params
        self.client = LLMClient(llm_params["model"], llm_params.get("base_url"),
                                allow_remote=llm_params.get("allow_remote", False),
                                timeout=llm_params.get("timeout_s", 120))
        self.cache_path = Path(cache_path)
        self.cache = {}
        if self.cache_path.exists():
            self.cache = {r["key"]: r["out"] for r in iter_jsonl(self.cache_path)}
        self.failed = 0

    def _key(self, text: str) -> str:
        return hashlib.sha1(f"{self.p['model']}\n{text}".encode()).hexdigest()

    def __call__(self, text: str, rng=None) -> str:
        if not (text or "").strip():
            return text
        k = self._key(text)
        if k not in self.cache:
            out, _, _ = self.client.chat([{"role": "user", "content": PARAPHRASE_PROMPT.format(text=text)}],
                                         temperature=0.7, max_tokens=int(self.p.get("paraphrase_max_tokens", 400)))
            out = out.strip()
            if sorted(_PLACEHOLDER.findall(out)) != sorted(_PLACEHOLDER.findall(text)) or not out:
                self.failed += 1          # lost or invented an identifier: keep the original post
                out = text
            self.cache[k] = out
            write_jsonl(self.cache_path, [{"key": k, "out": out}], append=True, private=True)
        return self.cache[k]


# ----------------------------------------------------------------------------- evaluation

ATTACKS = {"char": char_substitution, "translit": transliterate, "emoji": emoji_swap}


def attack_examples(examples: list[dict], fn, seed: int, only_suspicious: bool = False) -> tuple[list[dict], float]:
    rng = random.Random(seed)
    out, changed = [], 0
    for e in examples:
        if only_suspicious and e["label"] not in SUSPICIOUS:
            out.append(e)
            continue
        new = dict(e, text=fn(e.get("text") or "", rng), ocr_text=fn(e.get("ocr_text") or "", rng))
        changed += (new["text"], new["ocr_text"]) != (e.get("text"), e.get("ocr_text"))
        out.append(new)
    return out, changed / max(1, len(examples))


def main(argv=None):
    from models.metrics import score
    from models.registry import build, load_config, load_split, xy

    ap = argparse.ArgumentParser(description="Robustness of a baseline to evasion-style perturbations")
    ap.add_argument("--config", required=True)
    ap.add_argument("--split", default="time_channel")
    ap.add_argument("--test-set", default="test")
    ap.add_argument("--splits-dir", default="store/splits")
    ap.add_argument("--attacks", default="char,translit,emoji")
    ap.add_argument("--paraphrase-config", default="models/configs/llm_zeroshot.yaml",
                    help="model config whose LLM endpoint does the paraphrasing")
    ap.add_argument("--only-suspicious", action="store_true",
                    help="perturb only posts whose gold class is suspicious (what an evading seller would do)")
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--results-dir", default=str(RESULTS_DIR))
    ap.add_argument("--save-examples", default="", help="write attacked test sets to this directory")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    parts = load_split(Path(args.splits_dir) / args.split)
    test = parts[args.test_set]
    tr_x, tr_y, _ = xy(parts["train"])
    dv_x, dv_y, _ = xy(parts.get("dev", []))
    model = build(cfg, args.seed).fit(tr_x, tr_y, dv_x or None, dv_y or None)

    x, y, langs = xy(test)
    clean = score(y, model.predict(x), langs)
    print(f"clean: macro-F1 {clean['macro_f1']:.3f}")

    attacks = dict(ATTACKS)
    names = [a.strip() for a in args.attacks.split(",") if a.strip()]
    if "paraphrase" in names:
        attacks["paraphrase"] = Paraphraser(load_config(args.paraphrase_config)["params"])

    path = Path(args.results_dir) / "robustness.csv"
    rows = []
    if path.exists():                     # keep rows of other models / settings
        import csv
        with open(path, encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f)
                    if not (r["model"] == cfg["name"] and r["split"] == args.split and r["test_set"] == args.test_set
                            and r["only_suspicious"] == str(args.only_suspicious))]
        for r in rows:
            for k in ("macro_f1_clean", "macro_f1_attacked", "drop", "relative_drop", "suspicious_f1_clean",
                      "suspicious_f1_attacked", "suspicious_f1_drop", "changed_share"):
                r[k] = float(r[k]) if r.get(k) not in (None, "") else None
    for name in names:
        if name not in attacks:
            raise SystemExit(f"unknown attack {name!r}; choose from {sorted(attacks)}")
        attacked, share = attack_examples(test, attacks[name], args.seed, args.only_suspicious)
        if args.save_examples:
            write_jsonl(Path(args.save_examples) / f"{args.split}_{args.test_set}_{name}.jsonl", attacked)
        ax, ay, alangs = xy(attacked)
        s = score(ay, model.predict(ax), alangs)
        rows.append({"model": cfg["name"], "split": args.split, "test_set": args.test_set,
                     "only_suspicious": str(args.only_suspicious), "attack": name,
                     "macro_f1_clean": clean["macro_f1"], "macro_f1_attacked": s["macro_f1"],
                     "drop": clean["macro_f1"] - s["macro_f1"],
                     "relative_drop": (clean["macro_f1"] - s["macro_f1"]) / clean["macro_f1"] if clean["macro_f1"] else None,
                     "suspicious_f1_clean": clean["suspicious_f1"], "suspicious_f1_attacked": s["suspicious_f1"],
                     "suspicious_f1_drop": clean["suspicious_f1"] - s["suspicious_f1"], "changed_share": share})
        print(f"{name:10s} macro-F1 {s['macro_f1']:.3f} (drop {rows[-1]['drop']:+.3f}, "
              f"{share:.0%} of posts changed)")
    if isinstance(attacks.get("paraphrase"), Paraphraser) and attacks["paraphrase"].failed:
        print(f"paraphrase: {attacks['paraphrase'].failed} answers dropped a placeholder; originals kept")
    rows.sort(key=lambda r: (r["model"], r["split"], r["test_set"], r["only_suspicious"], r["attack"]))
    write_table("robustness", rows, caption="Macro-F1 under evasion-style perturbations",
                results_dir=args.results_dir)


if __name__ == "__main__":
    main()
