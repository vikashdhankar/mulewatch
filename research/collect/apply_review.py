"""Apply a person's channel review (the spreadsheet) to config/channels.discovered.yaml.

    python -m collect.apply_review                         # store/MuleWatch_Channel_Review.xlsx
    python -m collect.apply_review --xlsx store/a.xlsx --xlsx store/b.xlsx --dry-run

For every row whose "approved (Y/N)" cell is Y, the channel's entry gets approved: true and the label of
the row's suggestion (approve_fraud -> likely_fraud, approve_legit -> likely_legit), plus a 'review'
record (file, row, suggestion, date). Rows without Y are never touched: N or an empty cell does not
un-approve anything. A Y row whose suggestion is still 'review' or 'reject' is reported and skipped:
change the suggestion to approve_fraud or approve_legit first.

Discovery keeps these decisions when it rewrites the file (collect.discover_channels). The collector then
reads only the approved entries (python -m collect.telegram_public --approved-only).
"""
import argparse
import logging
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import yaml

log = logging.getLogger("collect.apply_review")

SUGGESTION_LABEL = {"approve_fraud": "likely_fraud", "approve_legit": "likely_legit"}
YES = {"y", "yes"}


def _norm(h) -> str:
    return str(h or "").strip().lower()


def read_review(path) -> list[dict]:
    """Rows of the review sheet as dicts: row (sheet row number), username, suggestion, approved."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["Review"] if "Review" in wb.sheetnames else wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    header = [_norm(h) for h in next(rows)]

    def col(*names):
        for i, h in enumerate(header):
            if any(h == n or h.startswith(n) for n in names):
                return i
        raise ValueError(f"{path}: no column {names[0]!r} in the review sheet")
    iu, isug, iap = col("username"), col("suggestion"), col("approved")
    out = []
    for n, r in enumerate(rows, start=2):
        r = list(r) + [None] * len(header)
        if not r[iu]:
            continue
        out.append({"row": n, "username": str(r[iu]).strip().lstrip("@"), "suggestion": _norm(r[isug]),
                    "approved": _norm(r[iap])})
    wb.close()
    return out


def apply(doc: dict, rows: list[dict], source: str, today: str | None = None) -> Counter:
    """Apply the Y rows to the channels document in place. Returns counts of what happened."""
    today = today or date.today().isoformat()
    by_name = {str(e.get("username", "")).lower(): e for e in doc.get("channels") or []}
    n = Counter()
    for r in rows:
        if r["approved"] not in YES:
            n["not_marked_y"] += 1
            continue
        n["marked_y"] += 1
        label = SUGGESTION_LABEL.get(r["suggestion"])
        if not label:
            n["skipped_suggestion_" + (r["suggestion"] or "empty")] += 1
            log.warning("row %d %s: marked Y but the suggestion is %r; set approve_fraud or approve_legit",
                        r["row"], r["username"], r["suggestion"])
            continue
        e = by_name.get(r["username"].lower())
        if e is None:
            n["skipped_not_in_channels_file"] += 1
            log.warning("row %d %s: not in the channels file", r["row"], r["username"])
            continue
        if e.get("approved") is True and e.get("label") == label:
            n["already_approved"] += 1
        else:
            n["approved_now"] += 1
            if e.get("label") != label:
                n[f"label_changed_to_{label}"] += 1
        e["approved"], e["label"] = True, label
        e["review"] = {"source": source, "row": r["row"], "suggestion": r["suggestion"], "applied": today}
    return n


def summary(channels: list[dict]) -> dict:
    return {"label": Counter(e.get("label") for e in channels),
            "category": Counter(e.get("category") for e in channels),
            "district": Counter((e.get("top_district") or "-") for e in channels if e.get("rajasthan_focus"))}


def print_summary(title: str, channels: list[dict], stream=sys.stdout) -> None:
    p = lambda *a: print(*a, file=stream)  # noqa: E731
    s = summary(channels)
    p(f"\n{title}: {len(channels)} channels")
    for key, head in (("label", "per label"), ("category", "per category"),
                      ("district", "per district (rajasthan_focus only)")):
        p(f"  {head}:")
        for k, v in sorted(s[key].items(), key=lambda kv: (-kv[1], str(kv[0]))):
            p(f"    {str(k):26s} {v}")


def write_yaml(path: Path, doc: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    tmp.replace(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--xlsx", action="append", help="review spreadsheet(s); default store/MuleWatch_Channel_Review.xlsx")
    ap.add_argument("--channels", default="config/channels.discovered.yaml")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    path = Path(args.channels)
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    total = Counter()
    for x in args.xlsx or ["store/MuleWatch_Channel_Review.xlsx"]:
        rows = read_review(x)
        n = apply(doc, rows, Path(x).name)
        log.info("%s: %d rows; %s", x, len(rows), ", ".join(f"{k} {v}" for k, v in sorted(n.items())))
        total += n
    approved = [e for e in doc.get("channels") or [] if e.get("approved") is True]
    if not args.dry_run and (total["approved_now"] or total["already_approved"]):
        write_yaml(path, doc)
        log.info("wrote %s", path)
    elif not args.dry_run:
        log.info("nothing to apply: %s unchanged", path)
    print_summary("approved for collection", approved)
    print_summary("all channels in the file", doc.get("channels") or [])
    fraud, legit = (sum(e.get("label") == k for e in approved) for k in ("likely_fraud", "likely_legit"))
    print(f"\ncollection set: {fraud} likely_fraud : {legit} likely_legit"
          + (f" (ratio {fraud / legit:.1f}:1)" if legit else ""))


if __name__ == "__main__":
    main()
