"""Collect results/runs/*.json into the summary tables (mean and std over seeds).

    python -m models.report

  main_results      macro-F1 (± std), suspicious-vs-not F1, accuracy, ms/post, p95 single-post latency,
                    USD per 1k posts, training minutes
  per_class_f1      F1 of each of the 7 classes
  per_language_f1   macro-F1 within en / hi / hinglish / mixed posts (with counts)
"""
import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

from common.labels import CLASSES, LANGUAGES
from common.results import RESULTS_DIR, write_table


def _mean(vals):
    vals = [v for v in vals if isinstance(v, (int, float)) and v == v]
    return statistics.fmean(vals) if vals else None


def _std(vals):
    vals = [v for v in vals if isinstance(v, (int, float)) and v == v]
    return statistics.stdev(vals) if len(vals) > 1 else None


def load_runs(results_dir) -> dict:
    groups = defaultdict(list)
    for p in sorted(Path(results_dir, "runs").glob("*.json")):
        r = json.loads(p.read_text())
        groups[(r["model"], r["split"], r["test_set"])].append(r)
    return groups


def build(results_dir=RESULTS_DIR) -> None:
    groups = load_runs(results_dir)
    if not groups:
        return
    main_rows, class_rows, lang_rows = [], [], []
    for (model, split, test_set), runs in sorted(groups.items()):
        key = {"model": model, "split": split, "test_set": test_set, "seeds": len(runs)}
        main_rows.append({**key, "n_test": runs[0]["n"],
                          "macro_f1": _mean([r["macro_f1"] for r in runs]),
                          "macro_f1_std": _std([r["macro_f1"] for r in runs]),
                          "suspicious_f1": _mean([r["suspicious_f1"] for r in runs]),
                          "accuracy": _mean([r["accuracy"] for r in runs]),
                          "ms_per_post": _mean([r["timing"]["ms_per_post"] for r in runs]),
                          "p95_ms": _mean([r["timing"]["single_p95_ms"] for r in runs]),
                          "usd_per_1k": _mean([r["cost"]["usd_per_1k"] for r in runs]),
                          "train_min": _mean([r["train_s"] / 60 for r in runs])})
        class_rows.append({**key, **{c: _mean([r["per_class_f1"].get(c) for r in runs]) for c in CLASSES}})
        lr = dict(key)
        for lang in LANGUAGES:
            lr[lang] = _mean([r["per_language"].get(lang, {}).get("macro_f1") for r in runs])
            lr[f"n_{lang}"] = runs[0]["per_language"].get(lang, {}).get("n", 0)
        lang_rows.append(lr)
    write_table("main_results", main_rows, caption="Baselines: macro-F1, latency and cost per 1,000 posts",
                results_dir=results_dir, bold_max=["macro_f1", "suspicious_f1"])
    write_table("per_class_f1", class_rows, caption="Per-class F1", results_dir=results_dir, bold_max=CLASSES)
    write_table("per_language_f1", lang_rows, caption="Macro-F1 by language", results_dir=results_dir,
                bold_max=LANGUAGES)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--results-dir", default=str(RESULTS_DIR))
    build(ap.parse_args().results_dir)
