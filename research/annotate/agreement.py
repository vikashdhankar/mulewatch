"""Inter-annotator agreement on the posts two annotators both labelled.

    python -m annotate.agreement store/annotations/annotations.jsonl

Writes to research/results/: agreement.csv/.tex (Cohen's kappa for the 7 classes, for suspicious vs
not suspicious, observed agreement, span F1), agreement_per_class.csv/.tex (one-vs-rest kappa per
class) and agreement_confusion_<a>_<b>.csv. With more than two annotators every pair is reported.
"""
import argparse
import csv
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from common.io import read_jsonl
from common.labels import CLASSES, SUSPICIOUS
from common.results import RESULTS_DIR, write_table


def cohen_kappa(a: list, b: list, labels: list | None = None) -> float:
    """Cohen's kappa for two raters over the same items."""
    if len(a) != len(b):
        raise ValueError("raters must label the same items")
    n = len(a)
    if n == 0:
        return float("nan")
    labels = labels or sorted(set(a) | set(b))
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in labels) / (n * n)
    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


def span_f1(spans_a: list[list[dict]], spans_b: list[list[dict]]) -> float:
    """Exact-match span F1 between two annotators (field, start, end, label), micro-averaged."""
    tp = fp = fn = 0
    for sa, sb in zip(spans_a, spans_b):
        A = {(s["field"], s["start"], s["end"], s["label"]) for s in sa}
        B = {(s["field"], s["start"], s["end"], s["label"]) for s in sb}
        tp += len(A & B)
        fp += len(A - B)
        fn += len(B - A)
    if tp + fp + fn == 0:
        return float("nan")
    return 2 * tp / (2 * tp + fp + fn)


def paired(rows: list[dict]) -> dict[tuple[str, str], list[tuple[dict, dict]]]:
    by_post = defaultdict(dict)
    for r in rows:
        by_post[r["post_id"]][r["annotator"]] = r        # last label per annotator wins
    pairs = defaultdict(list)
    for anns in by_post.values():
        for x, y in combinations(sorted(anns), 2):
            pairs[(x, y)].append((anns[x], anns[y]))
    return pairs


def agreement(rows: list[dict]) -> tuple[list[dict], list[dict], dict]:
    summary, per_class, confusions = [], [], {}
    for (x, y), items in sorted(paired(rows).items()):
        la = [i[0]["label"] for i in items]
        lb = [i[1]["label"] for i in items]
        sus_a = [lab in SUSPICIOUS for lab in la]
        sus_b = [lab in SUSPICIOUS for lab in lb]
        summary.append({"annotator_a": x, "annotator_b": y, "n_items": len(items),
                        "observed_agreement": sum(p == q for p, q in zip(la, lb)) / len(items),
                        "kappa_7class": cohen_kappa(la, lb, CLASSES),
                        "kappa_suspicious": cohen_kappa(sus_a, sus_b, [True, False]),
                        "span_f1": span_f1([i[0]["spans"] for i in items], [i[1]["spans"] for i in items])})
        for c in CLASSES:
            per_class.append({"annotator_a": x, "annotator_b": y, "class": c,
                              "n_a": la.count(c), "n_b": lb.count(c),
                              "kappa": cohen_kappa([v == c for v in la], [v == c for v in lb], [True, False])})
        confusions[(x, y)] = Counter(zip(la, lb))
    return summary, per_class, confusions


def main(argv=None):
    ap = argparse.ArgumentParser(description="Cohen's kappa between annotators")
    ap.add_argument("annotations", nargs="?", default="store/annotations/annotations.jsonl")
    ap.add_argument("--results-dir", default=str(RESULTS_DIR))
    args = ap.parse_args(argv)

    summary, per_class, confusions = agreement(read_jsonl(args.annotations))
    if not summary:
        raise SystemExit("no post was labelled by two annotators")
    write_table("agreement", summary, caption="Inter-annotator agreement on doubly-annotated posts",
                results_dir=args.results_dir)
    write_table("agreement_per_class", per_class, caption="One-vs-rest Cohen's kappa per class",
                results_dir=args.results_dir)
    for (x, y), conf in confusions.items():
        path = Path(args.results_dir) / f"agreement_confusion_{x}_{y}.csv"
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([f"{x} \\ {y}"] + CLASSES)
            for c in CLASSES:
                w.writerow([c] + [conf[(c, d)] for d in CLASSES])
    for s in summary:
        print(f"{s['annotator_a']} vs {s['annotator_b']}: n={s['n_items']} kappa={s['kappa_7class']:.3f} "
              f"(suspicious-vs-not {s['kappa_suspicious']:.3f})")


if __name__ == "__main__":
    main()
