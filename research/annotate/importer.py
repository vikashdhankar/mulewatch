"""Read Label Studio JSON exports back: per-annotator labels, gold labels and the conflicts to adjudicate.

    python -m annotate.importer store/ls_exports/*.json --out store/annotations
    python -m annotate.importer --pull 3,4 --out store/annotations          # straight from Label Studio
    python -m annotate.importer ... --adjudicated store/annotations/adjudicated.csv   # post_id,label

Writes <out>/annotations.jsonl (one row per post and annotator), <out>/gold.jsonl (one label per post:
agreed, single-annotated or adjudicated) and <out>/conflicts.jsonl (posts annotators disagree on and
nobody has adjudicated yet; they are left out of gold until then).
"""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from common.io import write_jsonl
from common.labels import CLASSES


def _annotator(ann: dict, task: dict, id_map: dict) -> str:
    who = ann.get("completed_by")
    if isinstance(who, dict):
        who = who.get("email") or who.get("id")
    who = str(who) if who is not None else ""
    if who in id_map:
        return id_map[who]
    return who or task.get("data", {}).get("assigned_to", "unknown")


def parse_export(tasks: list[dict], id_map: dict | None = None) -> list[dict]:
    """One row per (task, annotation). Cancelled/skipped annotations are dropped."""
    id_map = id_map or {}
    rows = []
    for task in tasks:
        data = task.get("data", {})
        for ann in task.get("annotations", []):
            if ann.get("was_cancelled"):
                continue
            row = {"post_id": data.get("post_id"), "annotator": _annotator(ann, task, id_map), "label": None,
                   "language": None, "spans": [], "notes": "", "overlap": bool(data.get("overlap")),
                   "batch": data.get("batch"), "lead_time_s": ann.get("lead_time")}
            for r in ann.get("result", []):
                v = r.get("value", {})
                if r.get("from_name") == "label" and v.get("choices"):
                    row["label"] = v["choices"][0]
                elif r.get("from_name") == "language" and v.get("choices"):
                    row["language"] = v["choices"][0]
                elif r.get("from_name") in ("spans", "ocr_spans") and v.get("labels"):
                    row["spans"].append({"field": "text" if r["from_name"] == "spans" else "ocr_text",
                                         "start": v.get("start"), "end": v.get("end"), "text": v.get("text"),
                                         "label": v["labels"][0]})
                elif r.get("from_name") == "notes" and v.get("text"):
                    row["notes"] = " ".join(v["text"])
            if row["label"] is None:
                continue
            if row["label"] not in CLASSES:
                raise ValueError(f"unknown class {row['label']!r} in task {task.get('id')}")
            rows.append(row)
    return rows


def build_gold(rows: list[dict], adjudicated: dict | None = None) -> tuple[list[dict], list[dict]]:
    adjudicated = adjudicated or {}
    by_post = defaultdict(list)
    for r in rows:
        by_post[r["post_id"]].append(r)
    gold, conflicts = [], []
    for pid, anns in by_post.items():
        latest = {}
        for a in anns:                           # the same annotator re-labelling: last one wins
            latest[a["annotator"]] = a
        anns = list(latest.values())
        labels = Counter(a["label"] for a in anns)
        langs = Counter(a["language"] for a in anns if a["language"])
        language = langs.most_common(1)[0][0] if langs else None
        spans = max(anns, key=lambda a: len(a["spans"]))["spans"]
        if pid in adjudicated:
            gold.append({"post_id": pid, "label": adjudicated[pid], "language": language, "spans": spans,
                         "source": "adjudicated", "n_annotators": len(anns)})
        elif len(labels) == 1:
            gold.append({"post_id": pid, "label": next(iter(labels)), "language": language, "spans": spans,
                         "source": "agreed" if len(anns) > 1 else "single", "n_annotators": len(anns)})
        else:
            conflicts.append({"post_id": pid, "labels": {a["annotator"]: a["label"] for a in anns},
                              "notes": {a["annotator"]: a["notes"] for a in anns if a["notes"]}})
    return gold, conflicts


def main(argv=None):
    ap = argparse.ArgumentParser(description="Import Label Studio exports")
    ap.add_argument("exports", nargs="*", help="Label Studio JSON export files")
    ap.add_argument("--pull", default="", help="Label Studio project ids to pull through the API")
    ap.add_argument("--out", default="store/annotations")
    ap.add_argument("--annotator-map", default="", help="e.g. 12=a1,13=a2 (Label Studio user id or e-mail)")
    ap.add_argument("--adjudicated", default="", help="CSV post_id,label")
    args = ap.parse_args(argv)

    id_map = dict(kv.split("=", 1) for kv in args.annotator_map.split(",") if "=" in kv)
    tasks = []
    for path in args.exports:
        tasks += json.loads(Path(path).read_text(encoding="utf-8"))
    if args.pull:
        from annotate.ls_api import pull_export
        for pid in args.pull.split(","):
            tasks += pull_export(int(pid))
    rows = parse_export(tasks, id_map)

    adjudicated = {}
    if args.adjudicated:
        with open(args.adjudicated, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["label"] not in CLASSES:
                    raise SystemExit(f"unknown class {r['label']!r} for {r['post_id']}")
                adjudicated[r["post_id"]] = r["label"]
    gold, conflicts = build_gold(rows, adjudicated)
    out = Path(args.out)
    write_jsonl(out / "annotations.jsonl", rows)
    write_jsonl(out / "gold.jsonl", gold)
    write_jsonl(out / "conflicts.jsonl", conflicts)
    print(f"{len(rows)} annotations, {len(gold)} gold labels, {len(conflicts)} conflicts -> {out}")


if __name__ == "__main__":
    main()
