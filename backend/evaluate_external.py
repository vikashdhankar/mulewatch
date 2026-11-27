"""Evaluate MuleWatch's text scoring on an external, labelled dataset that it was never trained on.

    cd backend
    ../.venv/bin/python evaluate_external.py scamshield ../datasets/scamshield-in/sms_fraud_classification.json
    ../.venv/bin/python evaluate_external.py csv fake_job_postings.csv --text-col description --label-col fraudulent --positive 1
    options: --out report.md   --examples 8   --live-model   --limit N

What it measures: every message goes through the same analyze() that scores forum and Telegram posts (keywords,
identifiers, rule engine and the n-gram model; no images, no LLM). A message counts as "flagged" when its score
reaches a risk level: Medium >= 30, High >= 55 (shown as "flagged" on the dashboard), Critical >= 80.

By default the model is trained afresh, in a temporary folder, on the shipped corpus (backend/training/), so results
are reproducible and don't depend on this laptop's cases or analyst feedback. --live-model scores with the model in
MW_DATA_DIR (backend/data) instead.

Read results honestly: MuleWatch looks for the SALE or RENTAL of bank accounts, cards and kits and for mule
recruitment. A general SMS-fraud set (OTP phishing, KYC, lottery) is a neighbouring problem, so recall there is a
lower bound, while the false-positive rate on legitimate messages is directly meaningful.
Examples in the report are masked (phone numbers, UPI IDs, account numbers, e-mails): datasets can hold real people's data.
"""
import argparse
import csv
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

LEVELS = (("Medium", 30.0), ("High", 55.0), ("Critical", 80.0))


# ----------------------------------------------------------------------------- loaders -> [{"text", "label", "type"}]

def load_scamshield(path: str) -> tuple[list[dict], dict]:
    """ScamShield-IN (Hugging Face haxrits/ScamShield-IN): only rows with label fraud/legit are SMS; the rest of the
    file is unrelated chatbot instruction data (no label) and is skipped."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    rows, skipped = [], Counter()
    for r in raw:
        label, text = r.get("label"), (r.get("message") or "").strip()
        if label not in ("fraud", "legit"):
            skipped["no fraud/legit label (not SMS data)"] += 1
            continue
        if not text:
            skipped["empty message"] += 1
            continue
        rows.append({"text": text, "label": int(label == "fraud"),
                     "type": r.get("fraud_type") or ("(legit)" if label == "legit" else "(fraud, no type)")})
    return rows, dict(skipped)


def load_csv(path: str, text_col: str, label_col: str, positive: str, type_col: str = "") -> tuple[list[dict], dict]:
    rows, skipped = [], Counter()
    csv.field_size_limit(10 * 1024 * 1024)
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for col in (*text_col.split("+"), label_col, type_col):
            if col and col not in (reader.fieldnames or []):
                sys.exit(f"column '{col}' not in {path}; columns: {', '.join(reader.fieldnames or [])}")
        for r in reader:
            text = " ".join((r.get(col) or "").strip() for col in text_col.split("+")).strip()
            if not text:
                skipped["empty text"] += 1
                continue
            lab = int(str(r.get(label_col, "")).strip() == positive)
            rows.append({"text": text, "label": lab,
                         "type": (r.get(type_col) if type_col else "") or ("(positive)" if lab else "(negative)")})
    return rows, dict(skipped)


# ----------------------------------------------------------------------------- metrics

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion k/n (sane for small n and for 0 or n)."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def confusion(scored: list[dict], threshold: float) -> dict:
    tp = sum(1 for r in scored if r["label"] and r["score"] >= threshold)
    fn = sum(1 for r in scored if r["label"] and r["score"] < threshold)
    fp = sum(1 for r in scored if not r["label"] and r["score"] >= threshold)
    tn = sum(1 for r in scored if not r["label"] and r["score"] < threshold)
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    fpr = fp / (fp + tn) if fp + tn else float("nan")
    f1 = 2 * prec * rec / (prec + rec) if tp else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": prec, "recall": rec, "fpr": fpr, "f1": f1,
            "recall_ci": wilson(tp, tp + fn), "fpr_ci": wilson(fp, fp + tn), "precision_ci": wilson(tp, tp + fp)}


def roc_auc(scored: list[dict]) -> float:
    """Probability that a random positive scores above a random negative (ties count half)."""
    pos = [r["score"] for r in scored if r["label"]]
    neg = [r["score"] for r in scored if not r["label"]]
    if not pos or not neg:
        return float("nan")
    allv = sorted((s, i) for i, s in enumerate(pos + neg))
    ranks, i = [0.0] * len(allv), 0
    while i < len(allv):                       # average ranks over ties
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[allv[k][1]] = (i + j) / 2 + 1
        i = j + 1
    r_pos = sum(ranks[:len(pos)])
    return (r_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def _norm(t: str) -> str:
    return re.sub(r"\W+", " ", t.lower()).strip()


# ----------------------------------------------------------------------------- scoring

def prepare_model(live: bool):
    """Import the app with a fresh model trained on the shipped corpus (default) or the live one."""
    if not live:
        os.environ["MW_DATA_DIR"] = tempfile.mkdtemp(prefix="mw-eval-")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from app.ml import retrain
    from app.pipeline import base_training_set
    train = base_training_set()
    if not live:
        retrain(train)
    return train


def score_all(rows: list[dict]) -> list[dict]:
    from app.scoring import analyze
    out = []
    for n, r in enumerate(rows, 1):
        a = analyze(r["text"][:20000])
        out.append({**r, "score": a["base_score"], "groups": a["groups"], "reason": (a["reasons"] or [""])[0]})
        if n % 200 == 0:
            print(f"  scored {n}/{len(rows)}", file=sys.stderr)
    return out


# ----------------------------------------------------------------------------- report

def pct(x: float) -> str:
    return "n/a" if x != x else f"{x * 100:.1f}%"


def ci(c: tuple[float, float]) -> str:
    return "" if c[0] != c[0] else f" ({c[0] * 100:.0f}–{c[1] * 100:.0f}%)"


def build_report(name: str, scored: list[dict], skipped: dict, train: list, dupes: int, live: bool,
                 n_examples: int) -> str:
    from app.masking import mask_text
    pos = sum(r["label"] for r in scored)
    L = [f"# MuleWatch on {name}", "",
         f"- Messages scored: **{len(scored)}** ({pos} positive / {len(scored) - pos} negative)"
         + (f"; skipped: " + ", ".join(f"{v} {k}" for k, v in skipped.items()) if skipped else ""),
         f"- Model: {'live model from MW_DATA_DIR' if live else f'fresh, trained on the shipped corpus ({len(train)} examples)'}"
         "; text only (no images, no LLM)",
         f"- Overlap with the training corpus: {dupes} message(s) identical after normalisation"
         + (" (they inflate the result)" if dupes else ""),
         f"- Ranking quality (ROC AUC, 0.5 = chance): **{roc_auc(scored):.3f}**", "",
         "| Flagged at | Recall (fraud caught) | False-positive rate (legit flagged) | Precision | F1 | TP / FP / FN / TN |",
         "|---|---|---|---|---|---|"]
    for lvl, th in LEVELS:
        c = confusion(scored, th)
        L.append(f"| {lvl} (≥{th:.0f}) | {pct(c['recall'])}{ci(c['recall_ci'])} | {pct(c['fpr'])}{ci(c['fpr_ci'])} | "
                 f"{pct(c['precision'])} | {c['f1']:.2f} | {c['tp']} / {c['fp']} / {c['fn']} / {c['tn']} |")
    L += ["", "95% Wilson intervals in brackets. 'High' is the dashboard's *flagged high or critical*.", "",
          "## Recall by type (flagged at High)", "", "| Type | n | caught | recall | median score |", "|---|---|---|---|---|"]
    by_type = defaultdict(list)
    for r in scored:
        by_type[r["type"]].append(r)
    for t, rs in sorted(by_type.items(), key=lambda kv: (-sum(x["label"] for x in kv[1]), -len(kv[1]))):
        scores = sorted(x["score"] for x in rs)
        hit = sum(1 for x in rs if x["score"] >= 55)
        note = " *(false positives)*" if not any(x["label"] for x in rs) else ""
        L.append(f"| {t}{note} | {len(rs)} | {hit} | {pct(hit / len(rs))} | {scores[len(scores) // 2]:.0f} |")
    hist = Counter(min(int(r["score"] // 10) * 10, 90) for r in scored)
    L += ["", "## Score distribution", "", "| score | positives | negatives |", "|---|---|---|"]
    for b in range(0, 100, 10):
        L.append(f"| {b}–{b + 9 if b < 90 else 100} | {sum(1 for r in scored if r['label'] and min(int(r['score'] // 10) * 10, 90) == b)}"
                 f" | {sum(1 for r in scored if not r['label'] and min(int(r['score'] // 10) * 10, 90) == b)} |")
    assert sum(hist.values()) == len(scored)

    def ex(title, rows):
        L.extend(["", f"## {title}", ""])
        for r in rows[:n_examples]:
            t = mask_text(re.sub(r"\s+", " ", r["text"]))[:220]
            L.append(f"- **{r['score']:.0f}** · {r['type']} · {', '.join(r['groups']) or 'no keyword groups'}: {t}")
        if not rows:
            L.append("- none")
    ex("Missed fraud (lowest-scoring positives)", sorted((r for r in scored if r["label"] and r["score"] < 55), key=lambda r: r["score"]))
    ex("False alarms (highest-scoring negatives)", sorted((r for r in scored if not r["label"] and r["score"] >= 55), key=lambda r: -r["score"]))
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="fmt", required=True)
    s = sub.add_parser("scamshield", help="ScamShield-IN json (Hugging Face haxrits/ScamShield-IN)")
    s.add_argument("path")
    c = sub.add_parser("csv", help="any CSV with a text column and a label column (e.g. EMSCAD fake_job_postings.csv)")
    c.add_argument("path")
    c.add_argument("--text-col", required=True, help="column, or several joined with + (title+description)")
    c.add_argument("--label-col", required=True)
    c.add_argument("--positive", required=True, help="label value that means fraud, e.g. 1")
    c.add_argument("--type-col", default="")
    for p in (s, c):
        p.add_argument("--out", help="write the markdown report here too")
        p.add_argument("--examples", type=int, default=8, help="masked examples per list (0 = none)")
        p.add_argument("--live-model", action="store_true", help="use the model in MW_DATA_DIR instead of a fresh one")
        p.add_argument("--limit", type=int, default=0, help="score only the first N rows (quick check)")
    a = ap.parse_args(argv)

    rows, skipped = (load_scamshield(a.path) if a.fmt == "scamshield"
                     else load_csv(a.path, a.text_col, a.label_col, a.positive, a.type_col))
    if a.limit:
        rows = rows[:a.limit]
    if not rows or not any(r["label"] for r in rows) or all(r["label"] for r in rows):
        sys.exit("need both positive and negative rows to evaluate")
    train = prepare_model(a.live_model)
    train_norm = {_norm(t) for t, _ in train}
    dupes = sum(1 for r in rows if _norm(r["text"]) in train_norm)
    print(f"scoring {len(rows)} messages ...", file=sys.stderr)
    scored = score_all(rows)
    name = Path(a.path).name if a.fmt == "csv" else "ScamShield-IN (labelled SMS)"
    report = build_report(name, scored, skipped, train, dupes, a.live_model, a.examples)
    print(report)
    if a.out:
        Path(a.out).write_text(report, encoding="utf-8")
        print(f"report written to {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
