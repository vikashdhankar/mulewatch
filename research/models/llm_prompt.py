"""Zero-shot and few-shot classification with an LLM behind an OpenAI-compatible endpoint."""
import json
import random
import re
from concurrent.futures import ThreadPoolExecutor

from common.labels import CLASS_DESCRIPTIONS, CLASSES
from common.llm_client import LLMClient

SYSTEM = """You classify public Telegram posts from India (English, Hindi or Hinglish) for research on \
money-mule account markets. Phone numbers, UPI IDs, accounts, cards, links and usernames have been replaced \
by placeholders such as [PHONE] or [UPI]. Text after [IMAGE TEXT] was read from the post's image by OCR.

Classes:
{classes}

Answer with JSON only, exactly like {{"label": "<class>"}}, using one of the class names above."""


def system_prompt() -> str:
    return SYSTEM.format(classes="\n".join(f"- {c}: {CLASS_DESCRIPTIONS[c]}" for c in CLASSES))


def parse_label(text: str) -> str | None:
    m = re.search(r"\{.*?\}", text or "", re.S)
    if m:
        try:
            lab = str(json.loads(m.group(0)).get("label", "")).strip().lower()
            if lab in CLASSES:
                return lab
        except (ValueError, AttributeError):
            pass
    low = (text or "").lower()
    hits = [c for c in CLASSES if c in low]
    return hits[0] if len(hits) == 1 else None


class LLMClassifier:
    """params: model, base_url, allow_remote, shots_per_class (0 = zero-shot), max_chars, workers,
    temperature, max_tokens, fallback_label."""

    def __init__(self, params: dict, seed: int = 13):
        self.p, self.seed = params, seed
        self.client = LLMClient(params["model"], params.get("base_url"), allow_remote=params.get("allow_remote", False),
                                timeout=params.get("timeout_s", 120), extra_body=params.get("extra_body"))
        self.shots: list[tuple[str, str]] = []
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}
        self.request_latencies: list[float] = []
        self.invalid = 0

    def _clip(self, t: str) -> str:
        n = int(self.p.get("max_chars", 1500))
        return t if len(t) <= n else t[:n] + " ..."

    def fit(self, texts, labels, dev_texts=None, dev_labels=None):
        k = int(self.p.get("shots_per_class", 0))
        if k:
            rng = random.Random(self.seed)
            by = {}
            for t, y in zip(texts, labels):
                by.setdefault(y, []).append(t)
            for c in CLASSES:
                pool = [t for t in by.get(c, []) if 20 <= len(t) <= int(self.p.get("max_shot_chars", 400))] \
                    or by.get(c, [])
                self.shots += [(self._clip(t), c) for t in rng.sample(pool, min(k, len(pool)))]
            rng.shuffle(self.shots)
        return self

    def messages(self, text: str) -> list[dict]:
        msgs = [{"role": "system", "content": system_prompt()}]
        for t, y in self.shots:
            msgs += [{"role": "user", "content": t}, {"role": "assistant", "content": json.dumps({"label": y})}]
        msgs.append({"role": "user", "content": self._clip(text)})
        return msgs

    def _one(self, text: str) -> str:
        out, usage, secs = self.client.chat(self.messages(text), temperature=float(self.p.get("temperature", 0.0)),
                                            max_tokens=int(self.p.get("max_tokens", 32)))
        self.usage["prompt_tokens"] += int(usage.get("prompt_tokens", 0))
        self.usage["completion_tokens"] += int(usage.get("completion_tokens", 0))
        self.request_latencies.append(secs)
        lab = parse_label(out)
        if lab is None:
            self.invalid += 1
            lab = self.p.get("fallback_label", "benign")
        return lab

    def predict(self, texts):
        with ThreadPoolExecutor(int(self.p.get("workers", 4))) as ex:
            return list(ex.map(self._one, texts))

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"params": self.p, "shots": self.shots}, f, ensure_ascii=False, indent=1)
