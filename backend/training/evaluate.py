"""Evaluate the detector on the 62 Charcha forum posts and their comments (never used for training).

    cd backend && python training/evaluate.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("MW_DATA_DIR", tempfile.mkdtemp())
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent / "forum"))

from app.imaging import ocr_image  # noqa: E402
from app.ml import retrain  # noqa: E402
from app.pipeline import base_training_set  # noqa: E402
from app.scoring import analyze  # noqa: E402
from seed_forum import IMG, POSTS  # noqa: E402

# ground truth: the posts in the first two blocks of seed_forum.POSTS are mule / card-sale ads
SUSPICIOUS_AUTHORS = {"rohit_traders", "quickdeals_jpr", "sharma_enterprises", "sonu_bhai_deals", "earnfromhome_21",
                      "priya_jobs", "naukri_guru_jpr", "cardzone_official", "cc_dealer_x", "vikram_p2p",
                      "fastmoney_hub", "sim_store_jpr", "anon_seller77", "kit_wala_rajesh", "deepak_kumar_88",
                      # drugs, arms, fake documents
                      "party_supply_jpr", "green_leaf_jdh", "ganganagar_supply", "desi_hathiyar_sk", "hathiyar_wala_x",
                      "doc_seva_fast", "aadhaar_pan_center"}


def main(threshold=55):
    retrain(base_training_set())
    tp = fp = tn = fn = 0
    rows = []
    for user, comm, _h, title, body, link, image, *_ in POSTS:
        text = "\n".join(x for x in (title, body, link) if x)
        ocr = ocr_image(str(IMG / image)) if image else ""
        score = analyze(text, ocr)["base_score"]
        truth = user in SUSPICIOUS_AUTHORS
        pred = score >= threshold
        tp += truth and pred; fn += truth and not pred; fp += pred and not truth; tn += not truth and not pred
        rows.append((score, truth, title[:60]))
    for score, truth, title in sorted(rows, reverse=True):
        print(f"{score:6.1f}  {'MULE ' if truth else 'clean'}  {title}")
    # comments: three seeded seller comments hidden under ordinary posts, the rest are normal replies
    scam_commenters = {"quick_earn_99", "kitwala_support", "easy_paisa_jpr", "maal_wala_99"}
    ctp = cfp = ctn = cfn = 0
    for *_, comments in POSTS:
        for who, text in comments:
            score = analyze(text)["base_score"]
            truth, pred = who in scam_commenters, score >= threshold
            ctp += truth and pred; cfn += truth and not pred; cfp += pred and not truth; ctn += not truth and not pred
            if truth or pred:
                print(f"{score:6.1f}  {'SCAM ' if truth else 'clean'}  comment by {who}: {text[:50]}")
    print(f"comments: TP {ctp}  FP {cfp}  TN {ctn}  FN {cfn}")
    tp += ctp; fp += cfp; tn += ctn; fn += cfn
    prec = tp / (tp + fp) if tp + fp else 0
    rec = tp / (tp + fn) if tp + fn else 0
    print(f"\nthreshold {threshold}:  TP {tp}  FP {fp}  TN {tn}  FN {fn}   precision {prec:.2f}  recall {rec:.2f}  "
          f"(posts + comments, base score only, before ring/watchlist boosts)")


if __name__ == "__main__":
    main()
