"""Train/dev/test splits that test on the future and on channels the model has never seen.

    python -m data.splits --posts store/redacted/posts.jsonl --gold store/annotations/gold.jsonl \
        --out store/splits

Three splits, each written to <out>/<name>/{train,dev,test}.jsonl:

  time          train on the oldest posts, dev on the next ones, test on the newest.
  channel       whole channels go to one side: test channels never appear in train.
  time_channel  the strict one. Channels are divided into seen and unseen; posts are divided at two
                dates. train = seen channels before t1, dev = seen channels between t1 and t2,
                test = unseen channels from t2 on. Posts outside those cells are dropped, and the
                newer posts of seen channels are kept as test_seen_channels, so temporal drift and
                channel drift can be told apart.

Copy-paste spam is common, so a post in dev/test whose normalised text also occurs in train is
removed (counted in the summary). A summary table goes to research/results/splits_summary.{csv,tex}.
"""
import argparse
import hashlib
import random
import re
from collections import Counter
from datetime import datetime, timezone

from common.io import read_jsonl, write_jsonl
from common.labels import CLASSES
from common.lang import detect_language
from common.results import RESULTS_DIR, write_table


def parse_date(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def join(posts: list[dict], gold: list[dict]) -> list[dict]:
    """Labelled examples: redacted post + gold label; the annotators' language tag wins over the heuristic."""
    labels = {g["post_id"]: g for g in gold}
    out = []
    for p in posts:
        g = labels.get(p["post_id"])
        if not g:
            continue
        out.append({"post_id": p["post_id"], "channel": p["channel"], "date": p["date"],
                    "text": p.get("text") or "", "ocr_text": p.get("ocr_text") or "", "label": g["label"],
                    "lang": g.get("language") or p.get("lang") or detect_language(p.get("text", "")),
                    "media_type": p.get("media_type", "")})
    return out


# ----------------------------------------------------------------------------- leakage

_PLACEHOLDER = re.compile(r"\[(?:PHONE|UPI|ACCOUNT|CARD|ID|EMAIL|URL|HANDLE)\]")


def text_key(ex: dict) -> str:
    """Normalised text: case, digits, punctuation, emoji and masked identifiers ignored."""
    t = _PLACEHOLDER.sub(" ", (ex.get("text") or "") + " " + (ex.get("ocr_text") or "")).lower()
    t = re.sub(r"[\d\W_]+", " ", t).strip()
    return hashlib.sha1(t.encode()).hexdigest() if t else ""


def drop_leaks(train: list[dict], other: list[dict]) -> tuple[list[dict], int]:
    seen = {text_key(e) for e in train} - {""}
    kept = [e for e in other if text_key(e) not in seen]
    return kept, len(other) - len(kept)


# ----------------------------------------------------------------------------- splits

def _date_cut(sorted_ex: list[dict], frac: float) -> datetime:
    """Date such that about `frac` of posts are strictly before it (ties move to the later side)."""
    if not sorted_ex:
        raise ValueError("no examples")
    i = min(len(sorted_ex) - 1, max(0, round(len(sorted_ex) * frac)))
    return parse_date(sorted_ex[i]["date"])


def time_split(examples: list[dict], dev_frac: float = 0.1, test_frac: float = 0.2) -> dict:
    ex = sorted(examples, key=lambda e: (parse_date(e["date"]), e["post_id"]))
    t1 = _date_cut(ex, 1 - dev_frac - test_frac)
    t2 = _date_cut(ex, 1 - test_frac)
    out = {"train": [e for e in ex if parse_date(e["date"]) < t1],
           "dev": [e for e in ex if t1 <= parse_date(e["date"]) < t2],
           "test": [e for e in ex if parse_date(e["date"]) >= t2]}
    return {"splits": out, "meta": {"t1": t1.isoformat(), "t2": t2.isoformat()}}


def assign_channels(examples: list[dict], dev_frac: float, test_frac: float, seed: int) -> dict[str, str]:
    """channel -> 'train' | 'dev' | 'test', filling test then dev with whole channels (shuffled with seed)
    until each holds about its share of posts."""
    sizes = Counter(e["channel"] for e in examples)
    channels = sorted(sizes)
    random.Random(seed).shuffle(channels)
    total = sum(sizes.values())
    quota = [(k, f * total) for k, f in (("test", test_frac), ("dev", dev_frac))]
    filled, out = Counter(), {}
    for ch in channels:
        while quota and filled[quota[0][0]] >= quota[0][1]:
            quota.pop(0)
        side = quota[0][0] if quota else "train"
        out[ch] = side
        filled[side] += sizes[ch]
    return out


def channel_split(examples: list[dict], dev_frac: float = 0.1, test_frac: float = 0.2, seed: int = 13) -> dict:
    side = assign_channels(examples, dev_frac, test_frac, seed)
    out = {k: [e for e in examples if side[e["channel"]] == k] for k in ("train", "dev", "test")}
    return {"splits": out, "meta": {"test_channels": sorted(c for c, s in side.items() if s == "test")}}


def time_channel_split(examples: list[dict], dev_frac: float = 0.1, test_frac: float = 0.2,
                       unseen_frac: float = 0.3, seed: int = 13) -> dict:
    side = assign_channels(examples, 0.0, unseen_frac, seed)          # 'test' = unseen channels
    unseen = {c for c, s in side.items() if s == "test"}
    ex = sorted(examples, key=lambda e: (parse_date(e["date"]), e["post_id"]))
    t1 = _date_cut(ex, 1 - dev_frac - test_frac)
    t2 = _date_cut(ex, 1 - test_frac)
    out = {"train": [], "dev": [], "test": [], "test_seen_channels": []}
    dropped = 0
    for e in ex:
        d, is_unseen = parse_date(e["date"]), e["channel"] in unseen
        if is_unseen:
            if d >= t2:
                out["test"].append(e)
            else:
                dropped += 1
        elif d < t1:
            out["train"].append(e)
        elif d < t2:
            out["dev"].append(e)
        else:
            out["test_seen_channels"].append(e)
    return {"splits": out, "meta": {"t1": t1.isoformat(), "t2": t2.isoformat(), "dropped": dropped,
                                    "unseen_channels": sorted(unseen)}}


def make_all(examples: list[dict], dev_frac=0.1, test_frac=0.2, unseen_frac=0.3, seed=13) -> dict:
    result = {"time": time_split(examples, dev_frac, test_frac),
              "channel": channel_split(examples, dev_frac, test_frac, seed),
              "time_channel": time_channel_split(examples, dev_frac, test_frac, unseen_frac, seed)}
    for r in result.values():
        sp = r["splits"]
        r["meta"]["leaks_removed"] = {}
        for k in sp:
            if k != "train":
                sp[k], n = drop_leaks(sp["train"], sp[k])
                r["meta"]["leaks_removed"][k] = n
    return result


def summary_rows(result: dict) -> list[dict]:
    rows = []
    for name, r in result.items():
        for part, ex in r["splits"].items():
            dates = sorted(e["date"] for e in ex)
            cls = Counter(e["label"] for e in ex)
            rows.append({"split": name, "part": part, "n": len(ex),
                         "channels": len({e["channel"] for e in ex}),
                         "from": dates[0][:10] if dates else "", "to": dates[-1][:10] if dates else "",
                         "leaks_removed": r["meta"]["leaks_removed"].get(part, 0),
                         **{c: cls.get(c, 0) for c in CLASSES}})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="Time- and channel-based splits")
    ap.add_argument("--posts", default="store/redacted/posts.jsonl")
    ap.add_argument("--gold", default="store/annotations/gold.jsonl")
    ap.add_argument("--out", default="store/splits")
    ap.add_argument("--dev-frac", type=float, default=0.1)
    ap.add_argument("--test-frac", type=float, default=0.2)
    ap.add_argument("--unseen-frac", type=float, default=0.3, help="share of posts in unseen channels")
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--results-dir", default=str(RESULTS_DIR))
    args = ap.parse_args(argv)

    examples = join(read_jsonl(args.posts), read_jsonl(args.gold))
    result = make_all(examples, args.dev_frac, args.test_frac, args.unseen_frac, args.seed)
    for name, r in result.items():
        for part, ex in r["splits"].items():
            write_jsonl(f"{args.out}/{name}/{part}.jsonl", ex)
    rows = summary_rows(result)
    write_table("splits_summary", rows, caption="Split sizes, date ranges and class counts",
                results_dir=args.results_dir)
    for r in rows:
        print(f"{r['split']:13s} {r['part']:19s} n={r['n']:6d} channels={r['channels']:4d} "
              f"{r['from']}..{r['to']} leaks_removed={r['leaks_removed']}")


if __name__ == "__main__":
    main()
