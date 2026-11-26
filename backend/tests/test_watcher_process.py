"""Watcher end to end against the command center's database, with Telethon mocked:
    cd backend && python -m pytest -q tests/test_watcher_process.py"""
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("MW_DATA_DIR", tempfile.mkdtemp())
os.environ["MW_SCREENSHOTS"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import auth  # noqa: E402
from app.config import DATA_DIR  # noqa: E402
from app.main import app  # noqa: E402
from app.db import Alert, EvidenceFile, Post, SessionLocal, WatchChannel, WatchIdent, WatchPost, init_db  # noqa: E402
from app.pipeline import recompute_all, rescore_all  # noqa: E402
from watcher import config  # noqa: E402
from watcher import telegram as wtg  # noqa: E402
from watcher.process import Processor, raw_bytes  # noqa: E402
from watcher.replay import replay  # noqa: E402

from pii.redact import Redactor  # noqa: E402

CFG = config.merge(config.load(), {"llm": {"enabled": False}})
RED = Redactor(b"unit-test-salt-0123456789")
NOW = datetime.now(timezone.utc).replace(microsecond=0)
KIT = "SBI current account kit, passbook + ATM + net banking, 18k. Call 98290 41736, UPI kit77@ybl. Jaipur"


def kit(n: int) -> str:
    """The kit ad with identifiers of its own, so earlier tests don't make them 'seen before'."""
    return KIT.replace("98290 41736", f"98290 {n:05d}").replace("kit77@ybl", f"kit{n}@ybl")


class KeywordModel:
    """Deterministic stand-in for the classifier."""
    name = "keyword-test-model"

    def predict(self, text):
        t = text.lower()
        if "kit" in t:
            return {"account_sale": 0.95, "unrelated": 0.05}, ["kit"]
        if "payout" in t:
            return {"payout_mule": 0.7, "unrelated": 0.3}, ["payout"]
        return {"unrelated": 0.97, "account_sale": 0.03}, []


class Sent(list):
    def __call__(self, text):
        self.append(text)
        return True


def setup_module():
    init_db()
    auth.ensure_demo_users()


def proc(**kw):
    sent = Sent()
    return Processor(CFG, RED, KeywordModel(), llm=None, sender=sent, **kw), sent


def rec(channel, mid, text, minutes_ago=0, ocr=""):
    return {"post_id": f"tg:{channel}:{mid}", "message_id": mid, "channel": channel,
            "date": (NOW - timedelta(minutes=minutes_ago)).isoformat(), "text": text, "ocr_text": ocr,
            "media_type": "photo" if ocr else "none", "views": 10, "source": "telegram_public",
            "collected_at": NOW.isoformat()}


# ----------------------------------------------------------------------------- routing and alerts

def test_high_post_becomes_case_alert_evidence_and_masked_telegram():
    p, sent = proc()
    out = p.handle(rec("rt_high", 1, KIT, ocr="passbook photo"))
    # 60 * 0.95 * 1.0 + 15 (new identifiers) + 10 (Jaipur) = 82
    assert (out.route, out.score, out.category) == ("HIGH", 82.0, "account_sale")
    with SessionLocal() as s:
        post = s.get(Post, out.post_id)
        assert post.source == "watcher" and post.url == "https://t.me/rt_high/1" and post.author == "@rt_high"
        assert (post.risk_score, post.risk_level, post.category) == (82.0, "Critical", "Account Sale")
        assert post.ocr_text == "passbook photo" and post.text == KIT          # the raw post is the evidence
        assert (post.jurisdiction or {}).get("district") == "Jaipur"
        assert post.reasons[0].startswith("Telegram watcher: Account Sale")
        alert = s.query(Alert).filter_by(post_id=post.id).one()
        assert alert.id == out.alert_id and alert.channel == "telegram" and alert.delivered
        wp = s.get(WatchPost, out.watch_post_id)
        assert wp.route == "HIGH" and wp.district == "Jaipur" and "98290" not in wp.masked_text
        ev = s.query(EvidenceFile).filter_by(post_id=post.id, kind="post_json").one()
        blob = (DATA_DIR / ev.path).read_bytes()
        assert ev.sha256 == wp.raw_sha256 == hashlib.sha256(blob).hexdigest()
        stored = json.loads(blob)
        assert stored["link"] == "https://t.me/rt_high/1" and stored["date"] and stored["ocr_text"] == "passbook photo"
        assert stored["text"] == KIT
    assert out.pushed is True and len(sent) == 1
    msg = sent[0]
    assert "98290" not in msg and "41736" not in msg and "kit77@ybl" not in msg and "[PHONE]" in msg
    assert "Account Sale" in msg and "@rt_high" in msg and "https://t.me/rt_high/1" in msg and "Jaipur" in msg
    assert "Linked identifiers: 0" in msg and f"/case/{out.post_id}" in msg


def test_medium_goes_to_review_queue_and_low_is_stored_only():
    p, sent = proc()
    med = p.handle(rec("rt_med", 1, "Gaming payout partner needed"))     # 60 * 0.7 = 42
    low = p.handle(rec("rt_med", 2, "Good morning everyone"))
    assert (med.route, med.score) == ("MEDIUM", 42.0) and med.post_id and med.alert_id is None
    assert (low.route, low.post_id) == ("LOW", None)
    with SessionLocal() as s:
        assert s.get(Post, med.post_id).risk_level == "Medium"
        assert s.query(Alert).filter_by(post_id=med.post_id).count() == 0
        assert s.get(WatchPost, low.watch_post_id).masked_text == "Good morning everyone"
    assert sent == []


def test_same_post_never_alerts_twice():
    p, sent = proc()
    first = p.handle(rec("rt_dup", 7, kit(101)))
    assert first.route == "HIGH"
    assert p.handle(rec("rt_dup", 7, kit(101))) is None
    assert Processor(CFG, RED, KeywordModel(), sender=sent).handle(rec("rt_dup", 7, kit(101))) is None   # new process
    with SessionLocal() as s:
        assert s.query(WatchPost).filter_by(uid="tg:rt_dup:7").count() == 1
        assert s.query(Alert).filter_by(post_id=first.post_id).count() == 1
    assert len(sent) == 1 and p.counts["duplicate"] == 1


def test_identifier_novelty_and_linking_across_channels():
    p, _ = proc()
    text = "Payout account available, pay novel11@ybl"
    a = p.handle(rec("rt_nov_a", 1, text, minutes_ago=30))
    b = p.handle(rec("rt_nov_b", 1, text, minutes_ago=20))
    c = p.handle(rec("rt_nov_c", 1, text, minutes_ago=10))
    with SessionLocal() as s:
        parts = [s.get(WatchPost, o.watch_post_id).breakdown for o in (a, b, c)]
        assert s.query(WatchIdent).filter(WatchIdent.channel.like("rt_nov_%")).count() == 3
    assert [x["new_identifier"] for x in parts] == [15, 0, 0]          # only the first sighting is new
    assert [x["linked"] for x in parts] == [0, 1, 1]
    assert [x["cross_channel"] for x in parts] == [0, 0, 5]             # third channel with the same UPI
    assert (a.score, b.score, c.score) == (57.0, 42.0, 47.0)


def test_backend_rescoring_keeps_watcher_cases():
    p, sent = proc()
    out = p.handle(rec("rt_keep", 1, kit(102)))
    with SessionLocal() as s:
        watched = s.query(Alert).join(Post, Post.id == Alert.post_id).filter(Post.source == "watcher")
        before = {a.id for a in watched}
        rescore_all(s, alert=True)
        recompute_all(s, alert=True)
        post = s.get(Post, out.post_id)
        assert (post.risk_score, post.risk_level, post.category) == (out.score, "Critical", "Account Sale")
        # maybe_alert never re-alerts them (its message carries raw contacts). The only alerts the backend adds
        # to a watcher case are complaint matches and reappearances, and those name no identifier value.
        added = [a.reason for a in watched if a.id not in before]
        assert all(r.startswith(("Identifiers match", "Reappeared after takedown")) for r in added), added
        assert not any(re.search(r"\+?\d[\d ]{8,}\d|@", r) for r in added), added
    assert len(sent) == 1


def test_logs_have_no_post_text_or_identifiers(caplog):
    p, _ = proc()
    with caplog.at_level(logging.DEBUG):
        p.handle(rec("rt_logs", 1, kit(41736) + " secret-marker-words"))
    text = caplog.text
    assert "rt_logs/1 -> HIGH" in text
    for raw in ("98290", "41736", "kit41736@ybl", "secret-marker-words", "passbook"):
        assert raw not in text


def test_log_filter_masks_values_that_slip_through(caplog):
    from watcher.logs import RedactFilter
    log = logging.getLogger("watcher.test")
    log.addFilter(RedactFilter())
    with caplog.at_level(logging.INFO):
        log.info("oops %s", "call 9829041736 or kit77@ybl")
    assert "9829041736" not in caplog.text and "kit77@ybl" not in caplog.text and "[PHONE]" in caplog.text


# ----------------------------------------------------------------------------- mocked Telethon

def msg(mid, text, minutes_ago=0, photo=None):
    return SimpleNamespace(id=mid, date=NOW - timedelta(minutes=minutes_ago), message=text, media=photo,
                           photo=photo, document=None, action=None, views=5, forwards=0, edit_date=None)


class FakeClient:
    def __init__(self, history):
        self.history = history          # newest last
        self.calls = []

    async def get_entity(self, name):
        self.calls.append(("get_entity", name))
        return SimpleNamespace(username=name)

    async def get_messages(self, entity, limit=100, min_id=0, reverse=False):
        self.calls.append(("get_messages", min_id))
        msgs = [m for m in self.history if m.id > min_id]
        if reverse:
            return msgs[:limit]
        return list(reversed(msgs))[:limit]

    async def download_media(self, m, file=bytes):
        self.calls.append(("download_media", m.id))
        return b"image-bytes"


class NoWait:
    async def wait(self):
        return None


@pytest.fixture
def channels(monkeypatch):
    import collect.telegram_public as tp
    monkeypatch.setattr(tp, "is_public_channel", lambda e: True)
    chans = []
    monkeypatch.setattr(wtg, "approved_channels", lambda cfg: chans)
    return chans


def run(coro):
    return asyncio.run(coro)


def test_mocked_telegram_updates_produce_expected_alerts(channels):
    channels.append({"username": "RT_Live", "label": "likely_fraud"})
    old = [msg(1, "Hello channel", 600), msg(2, kit(104), 500)]
    client = FakeClient(old)
    p, sent = proc()
    poller = wtg.Poller(CFG, p, client, limiter=NoWait(), ocr=lambda data: "UPI kit105@ybl")
    assert run(poller.cycle()) == 2          # first poll: the newest posts, recorded but never pushed
    assert sent == []
    with SessionLocal() as s:
        ch = s.query(WatchChannel).filter_by(username="rt_live").one()
        assert ch.last_id == 2 and ch.last_error == "" and ch.label == "likely_fraud"
        first = s.query(WatchPost).filter_by(uid="tg:rt_live:2").one()
        assert first.route == "HIGH" and s.query(Alert).filter_by(post_id=first.post_id).count() == 1
        ch.next_poll_at = datetime.utcnow() - timedelta(seconds=1)
        s.commit()

    client.history += [msg(3, "Gaming payout partner needed", 2),
                       msg(4, kit(105).replace("98290", "70148"), 1, photo=SimpleNamespace(sizes=[]))]
    assert run(poller.cycle()) == 2
    assert ("get_messages", 2) in client.calls and ("download_media", 4) in client.calls
    with SessionLocal() as s:
        rows = {w.message_id: w for w in s.query(WatchPost).filter_by(channel="rt_live")}
        assert rows[3].route == "MEDIUM" and rows[4].route == "HIGH"
        assert "[UPI]" in rows[4].masked_ocr
        assert s.query(WatchChannel).filter_by(username="rt_live").one().last_id == 4
        assert s.query(Alert).filter_by(post_id=rows[4].post_id).count() == 1
    assert len(sent) == 1 and "70148" not in sent[0] and "@rt_live" in sent[0]

    # nothing new and not due yet: no request at all
    n = len(client.calls)
    assert run(poller.cycle()) == 0 and len(client.calls) == n


def test_quiet_and_active_channels_get_different_intervals(channels):
    channels += [{"username": "rt_quiet"}, {"username": "rt_busy"}]
    p, _ = proc()

    class Two(FakeClient):
        async def get_messages(self, entity, **kw):
            self.calls.append(("get_messages", entity.username))
            return [msg(1, "hello", 60 * 24)] if entity.username == "rt_quiet" else [msg(1, "hello", 5)]
    run(wtg.Poller(CFG, p, Two([]), limiter=NoWait()).cycle())
    with SessionLocal() as s:
        q = s.query(WatchChannel).filter_by(username="rt_quiet").one()
        b = s.query(WatchChannel).filter_by(username="rt_busy").one()
        assert (q.interval_s, b.interval_s) == (900, 120)


def test_flood_wait_pauses_every_channel(channels):
    from telethon.errors import FloodWaitError
    channels += [{"username": "rt_flood1"}, {"username": "rt_flood2"}]
    p, _ = proc()

    class Flood(FakeClient):
        async def get_messages(self, entity, **kw):
            self.calls.append(("get_messages", entity.username))
            raise FloodWaitError(request=None, capture=600)
    client = Flood([])
    poller = wtg.Poller(CFG, p, client, limiter=NoWait())
    run(poller.cycle())
    assert [c for c in client.calls if c[0] == "get_messages"] == [("get_messages", "rt_flood1")]
    assert poller.flood_until > datetime.utcnow() + timedelta(seconds=500)
    with SessionLocal() as s:
        assert "FloodWait 600s" in s.query(WatchChannel).filter_by(username="rt_flood1").one().last_error
    n = len(client.calls)
    assert run(poller.cycle()) == 0 and len(client.calls) == n


def test_pause_flag_stops_polling(channels):
    from app.db import set_setting
    channels.append({"username": "rt_paused"})
    client = FakeClient([msg(1, kit(106))])
    p, _ = proc()
    set_setting("watcher_paused", "1")
    try:
        assert run(wtg.Poller(CFG, p, client, limiter=NoWait()).cycle()) == 0 and client.calls == []
        assert run(wtg.Poller(config.merge(CFG, {"paused": True}), p, client, limiter=NoWait()).cycle()) == 0
    finally:
        set_setting("watcher_paused", None)


# ----------------------------------------------------------------------------- replay

def test_replay_paces_posts_and_never_realerts(tmp_path):
    f = tmp_path / "telegram.jsonl"
    rows = [rec("rt_replay", 3, kit(107), minutes_ago=10),
            rec("rt_replay", 1, "Good morning", minutes_ago=60),
            rec("rt_replay", 2, "Gaming payout partner needed", minutes_ago=59)]
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    p, sent = proc()
    sleeps = []
    out = replay(f, p, speed=60, max_gap=5, sleep=sleeps.append)
    assert sleeps == [1.0, 5]            # 60 s / 60x, then 49 min / 60x capped at 5 s
    assert (out["HIGH"], out["MEDIUM"], out["LOW"], out["posts"]) == (1, 1, 1, 3)
    assert sent == []                     # replay pushes to Telegram only with --push
    with SessionLocal() as s:
        wp = s.query(WatchPost).filter_by(uid="tg:rt_replay:3").one()
        assert wp.mode == "replay" and s.query(Alert).filter_by(post_id=wp.post_id).count() == 1
        n_alerts = s.query(Alert).count()
    again = replay(f, Processor(CFG, RED, KeywordModel(), sender=sent), speed=60, sleep=lambda s: None)
    assert again["duplicate"] == 3
    with SessionLocal() as s:
        assert s.query(Alert).count() == n_alerts


def test_replay_window_uses_older_posts_as_history(tmp_path):
    f = tmp_path / "telegram.jsonl"
    same = kit(108)
    rows = [rec("rt_window", 1, same, minutes_ago=60 * 30),               # 30 h before the newest post
            rec("rt_window", 2, kit(109), minutes_ago=60 * 26),
            rec("rt_window", 3, same.replace("18k", "17k"), minutes_ago=60)]   # same identifiers, in the window
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    p, sent = proc()
    sleeps = []
    from watcher.replay import estimate
    est = estimate(f, speed=60, max_gap=5, window_hours=24)
    assert (est["history_posts"], est["posts"], est["replay_minutes"]) == (2, 1, 0)
    out = replay(f, p, speed=60, max_gap=5, sleep=sleeps.append, window_hours=24)
    assert out["history"] == 2 and out["history_posts"] == 2 and out["posts"] == 1
    assert sleeps == []                                                   # history goes through without pauses
    with SessionLocal() as s:
        hist = s.query(WatchPost).filter(WatchPost.channel == "rt_window", WatchPost.mode == "history").all()
        assert len(hist) == 2 and all(w.post_id is None for w in hist)    # no case, no alert
        assert all(w.route == "HIGH" for w in hist)                       # but scored as they would be
        live = s.query(WatchPost).filter_by(uid="tg:rt_window:3").one()
        assert live.mode == "replay" and live.post_id
        assert live.breakdown["new_identifier"] == 0                      # seen in the history
    c = TestClient(app)
    c.post("/api/auth/login", json={"username": "analyst", "password": auth.DEMO_PASSWORD})
    feed = c.get("/api/watcher/alerts", params={"route": "HIGH,MEDIUM", "limit": 500}).json()["items"]
    assert [i["post_id"] for i in feed if i["channel"] == "rt_window"] == [live.post_id]


def test_raw_bytes_are_stable():
    r = rec("x", 1, "a")
    assert raw_bytes(r) == raw_bytes(dict(reversed(list(r.items()))))
