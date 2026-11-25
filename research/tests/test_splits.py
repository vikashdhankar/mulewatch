import random
from datetime import datetime, timedelta, timezone

import pytest

from common.labels import CLASSES
from data.splits import (channel_split, drop_leaks, join, make_all, parse_date, text_key, time_channel_split,
                         time_split)


def make_examples(n=600, channels=20, seed=0):
    rng = random.Random(seed)
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    out = []
    for i in range(n):
        out.append({"post_id": f"tg:c{i % channels}:{i}", "channel": f"c{i % channels}",
                    "date": (start + timedelta(hours=rng.randint(0, 24 * 365))).isoformat(),
                    "text": f"post number {i} " + "word" * (i % 7) + " " + rng.choice("abcdefgh") * (i % 11),
                    "ocr_text": "", "label": CLASSES[i % 7], "lang": "en"})
    return out


@pytest.fixture(scope="module")
def ex():
    return make_examples()


def ids(part):
    return {e["post_id"] for e in part}


def test_time_split_is_chronological_and_complete(ex):
    sp = time_split(ex, dev_frac=0.1, test_frac=0.2)["splits"]
    assert max(parse_date(e["date"]) for e in sp["train"]) < min(parse_date(e["date"]) for e in sp["dev"])
    assert max(parse_date(e["date"]) for e in sp["dev"]) < min(parse_date(e["date"]) for e in sp["test"])
    assert ids(sp["train"]) | ids(sp["dev"]) | ids(sp["test"]) == ids(ex)
    assert sum(len(v) for v in sp.values()) == len(ex)
    assert abs(len(sp["test"]) - 0.2 * len(ex)) <= 0.02 * len(ex)


def test_time_split_ties_stay_together():
    d = "2025-06-01T00:00:00+00:00"
    ex = [{"post_id": str(i), "channel": "c", "date": d if 3 <= i <= 7 else f"2025-0{1 + i % 9}-02T00:00:00+00:00",
           "text": str(i), "label": "benign"} for i in range(10)]
    sp = time_split(ex, 0.0, 0.5)["splits"]
    same = [e for e in ex if e["date"] == d]
    assert ids(same) <= ids(sp["train"]) or ids(same) <= ids(sp["test"])


def test_channel_split_has_no_shared_channels(ex):
    sp = channel_split(ex, 0.1, 0.2, seed=3)["splits"]
    ch = {k: {e["channel"] for e in v} for k, v in sp.items()}
    assert not ch["train"] & ch["test"] and not ch["train"] & ch["dev"] and not ch["dev"] & ch["test"]
    assert ch["test"] and ch["dev"] and ch["train"]
    assert ids(sp["train"]) | ids(sp["dev"]) | ids(sp["test"]) == ids(ex)


def test_channel_split_is_deterministic(ex):
    a = channel_split(ex, seed=5)["meta"]["test_channels"]
    b = channel_split(list(reversed(ex)), seed=5)["meta"]["test_channels"]
    assert a == b
    assert a != channel_split(ex, seed=6)["meta"]["test_channels"]


def test_time_channel_split_tests_on_new_posts_from_unseen_channels(ex):
    r = time_channel_split(ex, 0.1, 0.2, unseen_frac=0.3, seed=1)
    sp, meta = r["splits"], r["meta"]
    train_ch = {e["channel"] for e in sp["train"] + sp["dev"]}
    test_ch = {e["channel"] for e in sp["test"]}
    assert test_ch and not train_ch & test_ch
    assert set(meta["unseen_channels"]) == test_ch
    latest_train = max(parse_date(e["date"]) for e in sp["train"])
    assert latest_train < min(parse_date(e["date"]) for e in sp["test"])
    assert latest_train < min(parse_date(e["date"]) for e in sp["test_seen_channels"])
    assert {e["channel"] for e in sp["test_seen_channels"]} <= train_ch
    kept = sum(len(v) for v in sp.values())
    assert kept + meta["dropped"] == len(ex)
    all_ids = [i for v in sp.values() for i in ids(v)]
    assert len(all_ids) == len(set(all_ids))


def test_duplicates_of_train_posts_removed_from_test():
    train = [{"text": "Current A/C kit ready, call [PHONE]!!", "ocr_text": ""}]
    test = [{"text": "current a/c KIT ready call [PHONE] 😀", "ocr_text": ""},
            {"text": "Current account kit 2 ready", "ocr_text": ""}]
    kept, n = drop_leaks(train, test)
    assert n == 1 and kept == [test[1]]
    assert text_key({"text": "[PHONE] 123"}) == ""


def test_make_all_removes_leaks_everywhere():
    ex = make_examples(300, 10, seed=2)
    for e in ex[150:]:
        e["text"] = ex[int(e["post_id"].split(":")[-1]) - 150]["text"]   # every post appears twice
    res = make_all(ex)
    for r in res.values():
        train_keys = {text_key(e) for e in r["splits"]["train"]}
        for part, v in r["splits"].items():
            if part != "train":
                assert not {text_key(e) for e in v} & train_keys


def test_join_prefers_annotator_language():
    posts = [{"post_id": "a", "channel": "c", "date": "2025-01-01T00:00:00+00:00", "text": "hello", "lang": "en"},
             {"post_id": "b", "channel": "c", "date": "2025-01-01T00:00:00+00:00", "text": "x"}]
    gold = [{"post_id": "a", "label": "benign", "language": "hinglish"}]
    out = join(posts, gold)
    assert len(out) == 1 and out[0]["lang"] == "hinglish" and out[0]["label"] == "benign"
