"""evaluate_external.py: loaders and metrics (tiny made-up inputs; no real dataset needed)."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("MW_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import evaluate_external as ev  # noqa: E402


def test_wilson_and_auc():
    lo, hi = ev.wilson(0, 129)
    assert lo == 0 and 0.02 < hi < 0.04                      # 0 of 129 still allows up to ~3%
    lo, hi = ev.wilson(50, 100)
    assert 0.40 < lo < 0.5 < hi < 0.60
    rows = [{"label": 1, "score": s} for s in (90, 70)] + [{"label": 0, "score": s} for s in (10, 70)]
    assert ev.roc_auc(rows) == 0.875                           # one tie counts half
    c = ev.confusion(rows, 55)
    assert (c["tp"], c["fp"], c["fn"], c["tn"]) == (2, 1, 0, 1) and c["recall"] == 1 and c["fpr"] == 0.5


def test_load_scamshield_keeps_only_labelled_sms(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps([
        {"message": "Share OTP now", "label": "fraud", "fraud_type": "OTP Phishing"},
        {"message": "Your order shipped", "label": "legit", "fraud_type": None},
        {"message": "Plan a trip to Goa?", "label": None, "fraud_type": None},   # chatbot data, not SMS
        {"message": None, "label": "fraud", "fraud_type": None},
    ]), encoding="utf-8")
    rows, skipped = ev.load_scamshield(str(p))
    assert [(r["label"], r["type"]) for r in rows] == [(1, "OTP Phishing"), (0, "(legit)")]
    assert sum(skipped.values()) == 2


def test_load_csv_joins_columns(tmp_path):
    p = tmp_path / "jobs.csv"
    p.write_text("title,description,fraudulent\nData entry,Earn 5000 daily,1\nClerk,Office job in Jaipur,0\n,,0\n",
                 encoding="utf-8")
    rows, skipped = ev.load_csv(str(p), "title+description", "fraudulent", "1")
    assert [(r["text"], r["label"]) for r in rows] == [("Data entry Earn 5000 daily", 1), ("Clerk Office job in Jaipur", 0)]
    assert skipped == {"empty text": 1}
