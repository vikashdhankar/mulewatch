"""Export redacted posts as Label Studio task batches, one file per annotator per batch.

    python -m annotate.export store/redacted/posts.jsonl --out store/annotation_batches \
        --batch-size 200 --annotators a1,a2 --overlap 0.25

Every batch has a shared overlap slice that all annotators label (for Cohen's kappa); the rest is
split between them. Posts already exported earlier (listed in <out>/exported.txt) are skipped, so
running it again produces the next batches. Only the language is pre-filled; the class is not, so
annotators are not anchored on a model's guess.

Add --push PROJECT_ID[,PROJECT_ID...] (one Label Studio project per annotator, in --annotators order)
to send the files straight to Label Studio.
"""
import argparse
import json
import random
from pathlib import Path

from common.io import iter_jsonl
from common.lang import detect_language


def to_task(post: dict, annotator: str, batch: int, overlap: bool) -> dict:
    lang = post.get("lang") or detect_language((post.get("text") or "") + " " + (post.get("ocr_text") or ""))
    return {
        "data": {"post_id": post["post_id"], "text": post.get("text") or "", "ocr_text": post.get("ocr_text") or "",
                 "channel": post.get("channel", ""), "date": post.get("date", ""),
                 "media_type": post.get("media_type", ""), "batch": batch, "assigned_to": annotator,
                 "overlap": overlap},
        "predictions": [{"model_version": "lang-heuristic-v1",
                         "result": [{"from_name": "language", "to_name": "text", "type": "choices",
                                     "value": {"choices": [lang]}}]}],
    }


def make_batches(posts: list[dict], annotators: list[str], batch_size: int, overlap: float, seed: int = 13,
                 start_batch: int = 1) -> dict[tuple[int, str], list[dict]]:
    """{(batch number, annotator): tasks}. Batch size counts distinct posts."""
    if not annotators:
        raise ValueError("need at least one annotator")
    rng = random.Random(seed)
    posts = list(posts)
    rng.shuffle(posts)
    out = {}
    for b, i in enumerate(range(0, len(posts), batch_size), start=start_batch):
        chunk = posts[i:i + batch_size]
        n_shared = round(len(chunk) * overlap) if len(annotators) > 1 else 0
        shared, rest = chunk[:n_shared], chunk[n_shared:]
        for k, a in enumerate(annotators):
            own = rest[k::len(annotators)]
            tasks = [to_task(p, a, b, True) for p in shared] + [to_task(p, a, b, False) for p in own]
            rng.shuffle(tasks)                     # shared items are not bunched at the top
            out[(b, a)] = tasks
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Export Label Studio task batches")
    ap.add_argument("posts", help="redacted posts JSONL")
    ap.add_argument("--out", default="store/annotation_batches")
    ap.add_argument("--batch-size", type=int, default=200)
    ap.add_argument("--annotators", default="a1,a2")
    ap.add_argument("--overlap", type=float, default=0.25, help="share of each batch labelled by everyone")
    ap.add_argument("--max-batches", type=int, default=0)
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--push", default="", help="Label Studio project ids, one per annotator")
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ledger = out / "exported.txt"
    done = set(ledger.read_text().split()) if ledger.exists() else set()
    prev = [int(p.stem.split("_")[1]) for p in out.glob("batch_*_*.json")]
    posts = [p for p in iter_jsonl(args.posts) if p["post_id"] not in done
             and ((p.get("text") or "").strip() or (p.get("ocr_text") or "").strip())]
    if args.max_batches:
        posts = posts[: args.max_batches * args.batch_size]
    annotators = [a.strip() for a in args.annotators.split(",") if a.strip()]
    batches = make_batches(posts, annotators, args.batch_size, args.overlap, args.seed,
                           start_batch=max(prev, default=0) + 1)

    projects = [int(x) for x in args.push.split(",") if x.strip()]
    if projects and len(projects) != len(annotators):
        raise SystemExit("--push needs one project id per annotator")
    for (b, a), tasks in sorted(batches.items()):
        path = out / f"batch_{b:03d}_{a}.json"
        path.write_text(json.dumps(tasks, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{path}: {len(tasks)} tasks ({sum(t['data']['overlap'] for t in tasks)} shared)")
        if projects:
            from annotate.ls_api import push_tasks
            push_tasks(projects[annotators.index(a)], tasks)
    with open(ledger, "a") as f:
        for p in posts:
            f.write(p["post_id"] + "\n")


if __name__ == "__main__":
    main()
