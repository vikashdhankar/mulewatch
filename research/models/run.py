"""Train a baseline on one split and score it on every test set of that split.

    python -m models.run --config models/configs/tfidf_lr.yaml --split time_channel
    python -m models.run --config models/configs/xlmr.yaml --split time_channel --seeds 13,42,2026

One JSON per (model, split, test set, seed) goes to results/runs/, predictions to store/predictions/,
and the summary tables in results/ are rebuilt (see models/report.py).
"""
import argparse
import json
import time
from pathlib import Path

from common.io import write_jsonl
from common.results import RESULTS_DIR
from models import report
from models.metrics import cost_per_1k, score, timed_predict
from models.registry import build, load_config, load_split, xy


def run(cfg: dict, split: str, splits_dir: str, seeds: list[int], results_dir: str, save_model: bool = False,
        predictions_dir: str = "store/predictions", checkpoints: str = "checkpoints") -> list[dict]:
    parts = load_split(Path(splits_dir) / split)
    tr_x, tr_y, _ = xy(parts["train"])
    dev = parts.get("dev", [])
    dv_x, dv_y, _ = xy(dev)
    tests = {k: v for k, v in parts.items() if k not in ("train", "dev") and v}
    runs_dir = Path(results_dir) / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for seed in seeds:
        model = build(cfg, seed, checkpoints)
        t0 = time.perf_counter()
        model.fit(tr_x, tr_y, dv_x or None, dv_y or None)
        train_s = time.perf_counter() - t0
        if save_model:
            model.save(f"{checkpoints}/{cfg['name']}_{split}_s{seed}")
        for test_name, examples in tests.items():
            x, y, langs = xy(examples)
            if hasattr(model, "usage"):
                model.usage = {"prompt_tokens": 0, "completion_tokens": 0}
                model.request_latencies = []
            preds, timing = timed_predict(model, x)
            usage = dict(getattr(model, "usage", {}) or {})
            rec = {"model": cfg["name"], "type": cfg["type"], "split": split, "test_set": test_name, "seed": seed,
                   "n_train": len(tr_x), "n_dev": len(dv_x), "train_s": train_s,
                   "train_usd": train_s / 3600 * float(cfg["cost"].get("usd_per_hour", 0.0)),
                   **score(y, preds, langs), "timing": timing, "usage": usage,
                   "cost": cost_per_1k(timing, len(x), cfg["cost"], usage),
                   "invalid_outputs": getattr(model, "invalid", 0), "params": cfg["params"]}
            (runs_dir / f"{cfg['name']}__{split}__{test_name}__s{seed}.json").write_text(
                json.dumps(rec, indent=1, ensure_ascii=False))
            write_jsonl(f"{predictions_dir}/{cfg['name']}__{split}__{test_name}__s{seed}.jsonl",
                        ({"post_id": e["post_id"], "gold": g, "pred": p, "lang": lg}
                         for e, g, p, lg in zip(examples, y, preds, langs)))
            print(f"{cfg['name']} {split}/{test_name} seed={seed}: macro-F1 {rec['macro_f1']:.3f}  "
                  f"{timing['ms_per_post']:.1f} ms/post  ${rec['cost']['usd_per_1k']:.4f}/1k")
            out.append(rec)
    report.build(results_dir)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Train and evaluate one baseline")
    ap.add_argument("--config", required=True)
    ap.add_argument("--split", default="time_channel")
    ap.add_argument("--splits-dir", default="store/splits")
    ap.add_argument("--seeds", default="", help="comma-separated; default from the config")
    ap.add_argument("--results-dir", default=str(RESULTS_DIR))
    ap.add_argument("--save-model", action="store_true")
    ap.add_argument("--predictions-dir", default="store/predictions")
    ap.add_argument("--checkpoints", default="checkpoints")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()] or cfg["seeds"]
    run(cfg, args.split, args.splits_dir, seeds, args.results_dir, args.save_model, args.predictions_dir,
        args.checkpoints)


if __name__ == "__main__":
    main()
