"""Scores: macro-F1, per-class F1, per-language macro-F1, suspicious-vs-not F1, latency and cost.

Macro-F1 is averaged over the classes present in the gold labels or the predictions of the set being
scored; a class nobody wrote or predicted there does not count as F1 = 0.
"""
import statistics
import time

from sklearn.metrics import f1_score

from common.labels import CLASSES, SUSPICIOUS


def _labels(y_true, y_pred):
    present = set(y_true) | set(y_pred)
    return [c for c in CLASSES if c in present]


def macro_f1(y_true, y_pred) -> float:
    if not y_true:
        return float("nan")
    return float(f1_score(y_true, y_pred, labels=_labels(y_true, y_pred), average="macro", zero_division=0))


def per_class_f1(y_true, y_pred) -> dict:
    scores = f1_score(y_true, y_pred, labels=CLASSES, average=None, zero_division=0)
    support = {c: y_true.count(c) for c in CLASSES}
    return {c: (float(s) if support[c] or c in y_pred else None) for c, s in zip(CLASSES, scores)}


def per_language_f1(y_true, y_pred, langs) -> dict:
    out = {}
    for lang in sorted(set(langs)):
        idx = [i for i, x in enumerate(langs) if x == lang]
        t, p = [y_true[i] for i in idx], [y_pred[i] for i in idx]
        out[lang] = {"n": len(idx), "macro_f1": macro_f1(t, p)}
    return out


def suspicious_f1(y_true, y_pred) -> float:
    t = [y in SUSPICIOUS for y in y_true]
    p = [y in SUSPICIOUS for y in y_pred]
    return float(f1_score(t, p, zero_division=0))


def score(y_true, y_pred, langs) -> dict:
    return {"n": len(y_true), "macro_f1": macro_f1(y_true, y_pred),
            "accuracy": sum(a == b for a, b in zip(y_true, y_pred)) / max(1, len(y_true)),
            "suspicious_f1": suspicious_f1(y_true, y_pred),
            "per_class_f1": per_class_f1(y_true, y_pred),
            "per_language": per_language_f1(y_true, y_pred, langs)}


def timed_predict(model, texts: list[str], single_sample: int = 50) -> tuple[list[str], dict]:
    """Predict the whole set (throughput) and, unless the model already timed its own requests,
    up to `single_sample` posts one at a time (latency a user waiting on one post would see)."""
    t0 = time.perf_counter()
    preds = model.predict(texts)
    total = time.perf_counter() - t0
    singles = list(getattr(model, "request_latencies", None) or [])
    if not singles:
        for t in texts[:single_sample]:
            s0 = time.perf_counter()
            model.predict([t])
            singles.append(time.perf_counter() - s0)
    singles.sort()
    q = lambda p: singles[min(len(singles) - 1, int(p * len(singles)))] * 1000 if singles else None  # noqa: E731
    return preds, {"total_s": total, "ms_per_post": total / max(1, len(texts)) * 1000,
                   "single_p50_ms": q(0.5), "single_p95_ms": q(0.95),
                   "single_mean_ms": statistics.fmean(singles) * 1000 if singles else None}


def cost_per_1k(timing: dict, n_posts: int, cost_cfg: dict, usage: dict | None = None) -> dict:
    """Hardware cost from wall-clock time at cost_cfg.usd_per_hour, plus API token cost if priced."""
    usage = usage or {}
    seconds_per_1k = timing["ms_per_post"]          # ms per post x 1000 posts / 1000 ms per s
    compute = seconds_per_1k / 3600 * float(cost_cfg.get("usd_per_hour", 0.0))
    api = 0.0
    if usage and n_posts:
        api = (usage.get("prompt_tokens", 0) / 1e6 * float(cost_cfg.get("usd_per_1m_input_tokens", 0.0))
               + usage.get("completion_tokens", 0) / 1e6 * float(cost_cfg.get("usd_per_1m_output_tokens", 0.0)))
        api = api / n_posts * 1000
    return {"compute_usd_per_1k": compute, "api_usd_per_1k": api, "usd_per_1k": compute + api,
            "hardware": cost_cfg.get("hardware", "")}
