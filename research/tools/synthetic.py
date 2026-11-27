"""SYNTHETIC data for smoke-testing the pipeline end to end. Not research data: never report numbers from it.

    python -m tools.synthetic --out /tmp/mw_smoke

Writes <out>/raw.jsonl (collector format, with made-up identifiers) and <out>/ls_export.json (a Label
Studio export with two simulated annotators who disagree on ~10% of the shared posts).
tools/smoke.sh runs every stage on it into a throw-away results directory.
"""
import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common.labels import CLASSES

T = {
    "mule_account_sale": {
        "en": ["Corporate current account kit available {price}, passbook ATM net banking SIM all ready. {contact}",
               "Fresh savings accounts for sale, full kit with debit card. Price {price}. {contact}"],
        "hinglish": ["Current account kit ready hai bhai, {price} me milega, {contact}",
                     "Firm account chahiye? full kit milega {price}, jaldi {contact}"],
        "hi": ["करंट खाता किट उपलब्ध, पासबुक एटीएम सिम सब मिलेगा, कीमत {price}, {contact}"]},
    "account_holder_recruitment": {
        "en": ["Need account holders, give your bank account for 2 days and earn {price} commission. {contact}"],
        "hinglish": ["Apna khata do aur roz {price} kamao, sirf 2 din ke liye, {contact}"],
        "hi": ["अपना बैंक खाता किराये पर दें और {price} रोज कमाएं, {contact}"]},
    "card_sale": {
        "en": ["ATM cards with PIN available, {price} each, bulk discount. {contact}"],
        "hinglish": ["Debit card PIN ke saath milega {price}, {contact}"],
        "hi": ["एटीएम कार्ड पिन के साथ {price} में, {contact}"]},
    "kyc_fraud": {
        "en": ["KYC documents ready, open any bank account without your own papers. {contact}"],
        "hinglish": ["Bina documents ke account khulwao, KYC hum karenge, {contact}"],
        "hi": ["बिना दस्तावेज़ खाता खुलवाएं, केवाईसी हम करेंगे, {contact}"]},
    "easy_money_lure": {
        "en": ["Work from home, like videos and earn {price} daily. Join now {contact}"],
        "hinglish": ["Ghar baithe {price} roz kamao, sirf phone chahiye, {contact}"],
        "hi": ["घर बैठे रोज {price} कमाएं, अभी जुड़ें {contact}"]},
    "awareness": {
        "en": ["Beware: renting your bank account is a crime. Report mule account offers on 1930.",
               "Police busted a gang buying current accounts. Never share your passbook or ATM card."],
        "hinglish": ["Apna account kisi ko mat do, ye fraud hai. 1930 pe report karo."],
        "hi": ["सावधान! अपना खाता किसी को किराये पर न दें, यह अपराध है। 1930 पर शिकायत करें।"]},
    "benign": {
        "en": ["Bank holiday on Monday, branches closed.", "Selling my old bike, good condition, {contact}",
               "New FD rates announced by the bank today."],
        "hinglish": ["Kal market band rahega, sab log dhyan rakhein.", "Purana phone bechna hai, {contact}"],
        "hi": ["कल बैंक की छुट्टी है।", "पुरानी किताबें बेचनी हैं, {contact}"]},
}


def make(n: int, channels: int, sellers: int, seed: int):
    rng = random.Random(seed)
    # 9200 series: a real mobile format (the redactor must see one) but not in the allotment table, so not
    # random people's numbers (see README "Synthetic data only")
    sell = [{"phone": f"9200{rng.randint(100000, 999999)}",
             "upi": f"seller{i}{rng.choice(['', '.k', '_77'])}@{rng.choice(['ybl', 'paytm', 'okaxis', 'ibl'])}",
             "handle": f"@kits_dealer_{i}"} for i in range(sellers)]
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    posts = []
    for i in range(n):
        label = rng.choices(CLASSES, weights=[3, 2, 2, 1, 2, 2, 4])[0]
        lang = rng.choices(["en", "hinglish", "hi"], weights=[4, 4, 2])[0]
        s = sell[rng.randrange(sellers)]
        contact = rng.choice([f"call {s['phone']}", f"pay {s['upi']}", f"DM {s['handle']}",
                              f"WhatsApp {s['phone'][:5]} {s['phone'][5:]} or {s['upi']}"])
        text = rng.choice(T[label][lang]).format(price=rng.choice(["Rs 25,000", "₹1500", "2k", "₹40000"]),
                                                  contact=contact)
        ch = rng.randrange(channels)
        ocr = f"UPI {s['upi']}" if rng.random() < 0.15 else ""
        posts.append({"post_id": f"tg:chan{ch}:{i}", "message_id": i, "channel": f"chan{ch}",
                      "date": (start + timedelta(minutes=rng.randint(0, 525600))).isoformat(), "text": text,
                      "media_type": "photo" if ocr else "none", "ocr_text": ocr, "views": rng.randint(10, 5000),
                      "source": "synthetic", "_label": label, "_lang": lang})
    return posts


def ls_export(posts, overlap: float, noise: float, seed: int):
    rng = random.Random(seed)
    tasks = []
    for i, p in enumerate(posts):
        def ann(who, lab):
            return {"completed_by": who, "result": [
                {"from_name": "label", "to_name": "text", "type": "choices", "value": {"choices": [lab]}},
                {"from_name": "language", "to_name": "text", "type": "choices", "value": {"choices": [p["_lang"]]}}]}
        shared = rng.random() < overlap
        anns = [ann(1, p["_label"])]
        if shared:
            anns.append(ann(2, p["_label"] if rng.random() > noise else rng.choice(CLASSES)))
        tasks.append({"id": i, "data": {"post_id": p["post_id"], "overlap": shared}, "annotations": anns})
    return tasks


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=1500)
    ap.add_argument("--channels", type=int, default=15)
    ap.add_argument("--sellers", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    posts = make(args.n, args.channels, args.sellers, args.seed)
    with open(out / "raw.jsonl", "w", encoding="utf-8") as f:
        for p in posts:
            f.write(json.dumps({k: v for k, v in p.items() if not k.startswith("_")}, ensure_ascii=False) + "\n")
    (out / "ls_export.json").write_text(json.dumps(ls_export(posts, 0.3, 0.1, args.seed), ensure_ascii=False))
    print(f"{len(posts)} synthetic posts -> {out}")


if __name__ == "__main__":
    main()
