"""Watcher pipeline as pure functions:  cd backend && python -m pytest -q tests/test_watcher_pipeline.py"""
import json
import pickle
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from watcher import config  # noqa: E402
from watcher.classifier import SklearnModel, best_saved, cues, parse_category  # noqa: E402
from watcher.pipeline import (AlertView, Classification, Signals, burst_check, case_level, classify,  # noqa: E402
                              compute_signals, format_alert, reasons, redact, risk_score, route)
from watcher.replay import parse_speed  # noqa: E402
from watcher.telegram import next_interval  # noqa: E402

from pii.redact import Redactor  # noqa: E402

CFG = config.load()
RISK = CFG["risk"]
RED = Redactor(b"unit-test-salt-0123456789")
T0 = datetime(2026, 11, 20, 12, 0)


class FixedModel:
    name = "fixed"

    def __init__(self, probs, cue_words=()):
        self.probs, self.cue_words = probs, list(cue_words)

    def predict(self, text):
        return dict(self.probs), list(self.cue_words)


class FakeHistory:
    def __init__(self, keys_by_channel=None, times=None, first=None):
        self.kbc = keys_by_channel or {}           # key -> set of channels
        self.times, self.first = times or [], first

    def known(self, keys):
        return {k for k in keys if k in self.kbc}

    def channels_of(self, keys):
        return {k: set(self.kbc[k]) for k in keys if k in self.kbc}

    def channel_times(self, channel, since, until):
        return [t for t in self.times if since <= t <= until]

    def channel_first_seen(self, channel):
        return self.first


def cls(category="account_sale", p=0.9, **kw):
    return Classification(category, p, p, {}, (), "fixed", **kw)


# ----------------------------------------------------------------------------- redact

def test_redact_masks_identifiers_and_keeps_keyed_hashes():
    r = redact({"channel": "kitwala", "text": "Kit ready, call 92000 41736 or pay kit77@ybl, DM @seller_jpr or @kitwala",
                "ocr_text": "UPI kit77@ybl card XXXX XXXX XXXX 1234"}, RED)
    assert "98290" not in r.text and "kit77@ybl" not in r.text + r.ocr_text
    assert "[PHONE]" in r.text and "[UPI]" in r.text and "[UPI]" in r.ocr_text
    kinds = sorted(k.split(":")[0] for k in r.keys)
    # one UPI (same value in text and OCR), the seller's handle; not the channel's own handle, not a masked card
    assert kinds == ["HANDLE", "PHONE", "UPI"]
    assert r.keys == redact({"channel": "x", "text": "+91-9200041736 kit77@YBL t.me/seller_jpr"}, RED).keys
    assert "[IMAGE TEXT]" in r.model_text


# ----------------------------------------------------------------------------- classify

def test_classify_skips_llm_when_model_is_sure():
    asked = []
    c = classify("x", FixedModel({"account_sale": 0.9, "unrelated": 0.1}), CFG["llm"], lambda t: asked.append(t))
    assert asked == [] and c.category == "account_sale" and c.p == 0.9 and c.llm is None
    c = classify("x", FixedModel({"account_sale": 0.2, "unrelated": 0.8}), CFG["llm"], lambda t: asked.append(t))
    assert asked == [] and c.category == "unrelated"


@pytest.mark.parametrize("p_model,asked", [(0.34, False), (0.35, True), (0.6, True), (0.75, True), (0.76, False)])
def test_classify_asks_llm_only_in_gray_zone(p_model, asked):
    calls = []

    def llm(text):
        calls.append(text)
        return "usdt_p2p"
    c = classify("t", FixedModel({"account_sale": p_model, "unrelated": 1 - p_model}), CFG["llm"], llm)
    assert bool(calls) == asked
    if asked:      # weight 0.5, LLM fraud p 0.9; the LLM names the fraud type
        assert c.p == pytest.approx(0.5 * p_model + 0.45) and c.category == "usdt_p2p"
        assert c.llm == {"category": "usdt_p2p", "p": 0.9} and c.p_model == pytest.approx(p_model)


def test_classify_llm_can_lower_p_and_failure_keeps_model():
    c = classify("t", FixedModel({"payout_mule": 0.6, "unrelated": 0.4}), CFG["llm"], lambda t: "unrelated")
    assert c.p == pytest.approx(0.35) and c.category == "unrelated"
    c = classify("t", FixedModel({"payout_mule": 0.6, "unrelated": 0.4}), CFG["llm"], lambda t: None)
    assert c.p == pytest.approx(0.6) and c.category == "payout_mule" and "error" in c.llm


def test_parse_category():
    assert parse_category('{"category": "task_job_scam"}') == "task_job_scam"
    assert parse_category("I think account_sale.") == "account_sale"
    assert parse_category("no idea") is None


def test_cue_words_prefer_phrases():
    out = cues("full kit with net banking", "account_sale", ["net", "banking", "kit", "a"], 6)
    assert "net banking" in out and "net" not in out and "banking" not in out and "a" not in out


# ----------------------------------------------------------------------------- risk score

def test_risk_score_formula():
    sig = Signals(new_keys=("PHONE:1",), places=("Jaipur",), burst=True, cross_channel=("PHONE:1",))
    score, parts = risk_score(cls("account_sale", 0.9), sig, RISK)
    assert parts == {"model": 54.0, "new_identifier": 15, "rajasthan_place": 10, "burst": 10, "cross_channel": 5}
    assert score == 94.0
    assert risk_score(cls("usdt_p2p", 0.5), Signals(), RISK) == (21.0, {"model": 21.0, "new_identifier": 0,
                                                                        "rajasthan_place": 0, "burst": 0,
                                                                        "cross_channel": 0})
    assert risk_score(cls("crypto_investment_scam", 1.0), Signals(), RISK)[0] == 54.0
    assert risk_score(cls("task_job_scam", 1.0), Signals(), RISK)[0] == 54.0
    assert risk_score(cls("payout_mule", 1.0), Signals(), RISK)[0] == 60.0
    assert risk_score(cls("unrelated", 0.99), Signals(), RISK)[0] == 0
    assert risk_score(cls("legit_finance", 0.99), Signals(places=("Kota",)), RISK)[0] == 10


def test_weights_come_from_config():
    risk = config.merge(RISK, {"weights": {"model": 100, "new_identifier": 0}})
    assert risk_score(cls("account_sale", 1.0), Signals(new_keys=("x",)), risk)[0] == 100
    with pytest.raises(ValueError):
        config.load(overrides={"risk": {"thresholds": {"high": 30, "medium": 40}}})


@pytest.mark.parametrize("score,expected", [(100, "HIGH"), (70, "HIGH"), (69.9, "MEDIUM"), (40, "MEDIUM"),
                                            (39.9, "LOW"), (0, "LOW")])
def test_routing_thresholds(score, expected):
    assert route(score, RISK["thresholds"]) == expected


def test_case_level_names():
    assert case_level("HIGH", 85) == "Critical" and case_level("HIGH", 72) == "High"
    assert case_level("MEDIUM", 50) == "Medium" and case_level("LOW", 10) == "Low"


# ----------------------------------------------------------------------------- signals

def test_identifier_novelty_and_cross_channel():
    h = FakeHistory({"PHONE:a": {"ch1", "ch2"}, "UPI:b": {"ch3"}})
    s = compute_signals(("PHONE:a", "UPI:b", "UPI:new"), "ch3", T0, [], h, RISK)
    assert s.new_keys == ("UPI:new",)
    assert s.linked == 2
    assert s.cross_channel == ("PHONE:a",) and s.max_channels == 3      # ch1, ch2 + this one
    s = compute_signals(("PHONE:a",), "ch1", T0, [], h, RISK)             # this channel is one of the two
    assert s.cross_channel == () and s.new_keys == ()
    s = compute_signals((), "ch1", T0, ["Jaipur", "Jaipur"], h, RISK)
    assert s.new_keys == () and s.places == ("Jaipur",)


def test_burst_needs_history_and_volume():
    assert burst_check([], T0, None, 3, 3) == (False, 1, 1.0)            # new channel: never a burst
    week = [T0 - timedelta(hours=h) for h in range(10, 160, 24)]          # ~1 post a day for a week
    hour = [T0 - timedelta(minutes=m) for m in (5, 20, 40)]
    burst, last_hour, mean = burst_check(week + hour, T0, T0 - timedelta(days=30), 3, 3)
    assert burst and last_hour == 4 and mean == pytest.approx((len(week) + 4) / 168, abs=1e-3)
    assert not burst_check(week + hour[:1], T0, T0 - timedelta(days=30), 3, 3)[0]   # 2 posts < min 3
    # three hours of history at 3/h, then 4 in the last hour: not 3x the usual rate
    steady = [T0 - timedelta(minutes=m) for m in range(10, 180, 20)]
    assert not burst_check(steady, T0, steady[-1], 3, 3)[0]


def test_signals_use_post_time_not_clock():
    times = [T0 - timedelta(days=3)] + [T0 - timedelta(minutes=m) for m in (1, 2, 3)]
    s = compute_signals((), "ch", T0, [], FakeHistory(times=times, first=T0 - timedelta(days=6)), RISK)
    assert s.burst and s.last_hour == 4


# ----------------------------------------------------------------------------- alert text

def test_alert_message_is_masked_and_complete():
    r = redact({"channel": "kits", "text": "<b>Kit</b> 18k call 9200041736 pay kit77@ybl Jaipur"}, RED)
    msg = format_alert(AlertView(masked_text=r.text, category="account_sale", score=82.4, channel="kits",
                                 link="https://t.me/kits/12", district="Jaipur", linked=2,
                                 case_url="http://x/case/5", cues=["kit"]))
    assert "9200041736" not in msg and "kit77@ybl" not in msg and "[PHONE]" in msg
    for part in ("score 82", "Account Sale", "@kits", "District: Jaipur", "Linked identifiers: 2",
                 "https://t.me/kits/12", "http://x/case/5", "&lt;b&gt;Kit"):
        assert part in msg
    long = format_alert(AlertView("y" * 1000, "payout_mule", 75, "c", "l"), 100)
    assert "y" * 101 not in long and "District: not identified" in long


def test_reasons_have_no_values():
    sig = Signals(new_keys=("PHONE:abc",), places=("Kota",), burst=True, last_hour=5, mean_hourly=0.2,
                  cross_channel=("PHONE:abc",), max_channels=4)
    lines = reasons(cls("account_sale", 0.9), sig, risk_score(cls("account_sale", 0.9), sig, RISK)[1])
    text = " ".join(lines)
    assert "PHONE:abc" not in text and "4 channels" in text and "Kota" in text


# ----------------------------------------------------------------------------- scheduling and replay

def test_adaptive_interval():
    t = CFG["telegram"]
    assert next_interval(T0 - timedelta(hours=1), T0, t) == 120
    assert next_interval(T0 - timedelta(hours=7), T0, t) == 900
    assert next_interval(None, T0, t) == 900


def test_parse_speed():
    assert parse_speed("50x") == 50 and parse_speed("2.5") == 2.5
    with pytest.raises(ValueError):
        parse_speed("fast")


# ----------------------------------------------------------------------------- saved research models

def test_best_saved_model_is_highest_f1_with_a_checkpoint(tmp_path):
    from models.tfidf_lr import TfidfLR
    runs = tmp_path / "results" / "runs"
    runs.mkdir(parents=True)
    (tmp_path / "checkpoints").mkdir()
    texts = ["current account kit for sale", "passbook atm kit", "full kit available",
             "beware of fraud report 1930", "bank holiday monday", "new fd rates today"]
    labels = ["mule_account_sale"] * 3 + ["awareness", "benign", "benign"]
    m = TfidfLR({"min_df": 1}).fit(texts, labels)
    m.save(tmp_path / "checkpoints" / "tfidf_lr_time_s13")
    for name, f1, split in (("tfidf_lr", 0.71, "time"), ("xlmr", 0.88, "time"), ("tfidf_lr", 0.50, "channel")):
        (runs / f"{name}_{split}.json").write_text(json.dumps(
            {"model": name, "type": "tfidf_lr" if name == "tfidf_lr" else "hf", "split": split, "seed": 13,
             "test_set": "test", "macro_f1": f1}))
    got = best_saved(tmp_path, CFG["classifier"]["class_map"])     # xlmr has no checkpoint: skipped
    assert isinstance(got, SklearnModel) and "0.710" in got.name
    probs, words = got.predict("atm kit available")
    assert max(probs, key=probs.get) == "account_sale" and abs(sum(probs.values()) - 1) < 1e-6
    assert any("kit" in w for w in words)
    assert best_saved(tmp_path / "nothing", {}) is None


def test_unmapped_research_class_is_refused():
    from sklearn.dummy import DummyClassifier
    from sklearn.pipeline import Pipeline
    pipe = Pipeline([("clf", DummyClassifier())]).fit([[0], [1]], ["new_class", "benign"])
    with pytest.raises(ValueError):
        SklearnModel(pipe, CFG["classifier"]["class_map"], "x")
    assert pickle.dumps(pipe)


def test_cues_are_shown_as_written_in_the_post():
    from watcher.classifier import as_written, cues
    text = "एटीएम कार्ड पिन के साथ, call [PHONE]. Full kit ready"
    assert as_written(text, "एट एम") == "एटीएम"              # the tokenizer splits Devanagari at vowel signs
    assert as_written(text, "full kit") == "Full kit"
    assert as_written(text, "kit full") == ""
    words = cues(text, "unrelated", ["एट एम", "phone", "full kit", "स थ"], 6)
    assert "एटीएम" in words and "Full kit" in words and "स थ" not in words and "PHONE" not in words
