"""Command-center endpoints for the Telegram watcher:  cd backend && python -m pytest -q tests/test_watcher_api.py"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("MW_DATA_DIR", tempfile.mkdtemp())
os.environ["MW_SCREENSHOTS"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, watcher_api  # noqa: E402
from app.db import AlertDecision, Post, SessionLocal, User, init_db  # noqa: E402
from app.main import app  # noqa: E402
from watcher import config  # noqa: E402
from watcher.process import Processor  # noqa: E402

from pii.redact import Redactor  # noqa: E402

CFG = config.merge(config.load(), {"llm": {"enabled": False}})
NOW = datetime.now(timezone.utc).replace(microsecond=0)
OUT = {}


class KeywordModel:
    name = "keyword-test-model"

    def predict(self, text):
        t = text.lower()
        if "kit" in t:
            return {"account_sale": 0.95, "unrelated": 0.05}, ["kit"]
        if "usdt" in t:
            return {"usdt_p2p": 0.9, "unrelated": 0.1}, ["usdt"]
        if "payout" in t:
            return {"payout_mule": 0.7, "unrelated": 0.3}, ["payout"]
        return {"unrelated": 0.97}, []


def rec(channel, mid, text, minutes_ago):
    return {"post_id": f"tg:{channel}:{mid}", "message_id": mid, "channel": channel, "text": text, "ocr_text": "",
            "date": (NOW - timedelta(minutes=minutes_ago)).isoformat(), "media_type": "none"}


def setup_module():
    init_db()
    auth.ensure_demo_users()
    p = Processor(CFG, Redactor(b"api-test-salt-0123456789"), KeywordModel(), sender=lambda t: None)
    OUT["kota"] = p.handle(rec("api_a", 1, "Current account kit 20k Kota, call 94140 77001", 300))
    OUT["usdt"] = p.handle(rec("api_b", 1, "USDT P2P buy sell, call 94140 77001, Jaipur", 200))
    OUT["med"] = p.handle(rec("api_b", 2, "Gaming payout partner needed", 100))
    OUT["same"] = p.handle(rec("api_c", 1, "Account kit ready, call 94140 77001, pay same5@ybl", 50))
    for i in range(4):          # a burst on api_c
        p.handle(rec("api_c", 10 + i, "hello", 10 - i))


def client(user):
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": user, "password": auth.DEMO_PASSWORD}).status_code == 200
    return c


def test_routes_as_expected():
    assert (OUT["kota"].route, OUT["usdt"].route, OUT["med"].route) == ("HIGH", "MEDIUM", "MEDIUM")
    # 0.9 * 0.7 * 60 = 37.8, + 10 Jaipur, no new identifier (seen in api_a) -> 47.8
    assert OUT["usdt"].score == 47.8
    # 0.95 * 60 = 57, + 15 (the UPI ID is new) + 5 (the phone is now in 3 channels) -> 77
    assert (OUT["same"].route, OUT["same"].score) == ("HIGH", 77.0)


def test_alert_feed_filters_by_district_and_category():
    c = client("analyst")
    d = c.get("/api/watcher/alerts").json()
    mine = [i for i in d["items"] if i["channel"].startswith("api_")]
    assert {i["channel"] for i in mine} == {"api_a", "api_b", "api_c"}
    assert all("77001" not in i["text"] for i in mine) and any("[PHONE]" in i["text"] for i in mine)
    kota = c.get("/api/watcher/alerts", params={"district": "Kota"}).json()["items"]
    assert [i["post_id"] for i in kota] == [OUT["kota"].post_id]
    assert kota[0]["category_label"] == "Account Sale" and kota[0]["alert_id"] and kota[0]["level"] in ("High", "Critical")
    usdt = c.get("/api/watcher/alerts", params={"category": "usdt_p2p"}).json()["items"]
    assert [i["post_id"] for i in usdt] == [OUT["usdt"].post_id]
    assert ["Kota", 1] in d["districts"] and any(x[0] == "usdt_p2p" for x in d["categories"])
    high = c.get("/api/watcher/alerts", params={"route": "HIGH"}).json()["items"]
    assert all(i["route"] == "HIGH" for i in high)


def test_alert_decisions_are_stored_with_reviewer_and_time():
    io = client("io")
    aid = OUT["kota"].alert_id
    assert io.post(f"/api/alerts/{aid}/decision", json={"decision": "maybe"}).status_code == 400
    r = io.post(f"/api/alerts/{aid}/decision", json={"decision": "needs_info", "note": "ask for the bank"}).json()
    assert r["decision"] == "needs_info" and r["reviewer"] == "io" and r["at"]
    with SessionLocal() as s:
        assert s.get(Post, OUT["kota"].post_id).label is None
    r = io.post(f"/api/alerts/{aid}/decision", json={"decision": "confirm"}).json()
    hist = io.get(f"/api/posts/{OUT['kota'].post_id}/decisions").json()
    assert [h["decision"] for h in hist] == ["needs_info", "confirm"] and hist[0]["note"] == "ask for the bank"
    with SessionLocal() as s:
        assert s.get(Post, OUT["kota"].post_id).label == "confirmed"
    alerts = io.get("/api/alerts").json()
    assert next(a for a in alerts if a["id"] == aid)["decision"]["decision"] == "confirm"
    feed = io.get("/api/watcher/alerts", params={"district": "Kota"}).json()["items"]
    assert feed[0]["decision"]["decision"] == "confirm" and feed[0]["decision"]["reviewer"] == "io"


def test_review_queue_decision():
    c = client("analyst")
    before = c.get("/api/watcher/health").json()["review_queue"]
    r = c.post(f"/api/watcher/queue/{OUT['med'].post_id}/decision", json={"decision": "false_alarm"})
    assert r.status_code == 200
    assert c.get("/api/watcher/health").json()["review_queue"] == before - 1
    with SessionLocal() as s:
        assert s.get(Post, OUT["med"].post_id).label == "false_positive"
    undecided = c.get("/api/watcher/alerts", params={"decided": "no"}).json()["items"]
    assert OUT["med"].post_id not in [i["post_id"] for i in undecided]


def test_entity_view():
    c = client("analyst")
    top = c.get("/api/watcher/entities").json()
    phone = next(e for e in top if e["kind"] == "PHONE" and e["channels"] == 3)
    assert phone["posts"] == 3 and "77001" not in json.dumps(top)
    d = c.get(f"/api/watcher/entities/{phone['hash']}").json()
    assert d["first_channel"] == "api_a" and {x["channel"] for x in d["channels"]} == {"api_a", "api_b", "api_c"}
    assert len(d["posts"]) == 3 and d["posts"][-1]["channel"] == "api_a" and d["first_seen"]
    assert c.get("/api/watcher/entities/PHONE:nope").status_code == 404


def test_burst_chart():
    c = client("analyst")
    b = c.get("/api/watcher/bursts", params={"channel": "api_c", "hours": 24}).json()[0]
    assert len(b["counts"]) == 24 and sum(b["counts"]) == 5 and b["peak"] >= 4 and b["mean_hourly"] > 0
    assert any(x["channel"] == "api_a" for x in c.get("/api/watcher/bursts").json())


def test_health_and_pause():
    sho, analyst = client("sho"), client("analyst")
    h = analyst.get("/api/watcher/health").json()
    names = {ch["username"] for ch in h["channels"]}
    assert {"api_a", "api_b", "api_c"} <= names and "queue_lag_s" in h and h["paused"] is False
    assert analyst.post("/api/watcher/pause", json={"paused": True}).status_code == 403
    assert sho.post("/api/watcher/pause", json={"paused": True}).json()["paused"] is True
    assert sho.post("/api/watcher/pause", json={"paused": False}).json()["paused"] is False


def test_evidence_pdf_pack():
    io, analyst = client("io"), client("analyst")
    pid = OUT["kota"].post_id
    assert analyst.get(f"/api/posts/{pid}/evidence-pack.pdf").status_code == 403
    r = io.get(f"/api/posts/{pid}/evidence-pack.pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and r.headers["x-pack-sha256"]
    with SessionLocal() as s:
        post = s.get(Post, pid)
        text = watcher_api.evidence_text(s, post, s.query(User).filter_by(username="io").one())
        from app.db import WatchPost
        sha = s.query(WatchPost).filter_by(post_id=pid).one().raw_sha256
    assert "https://t.me/api_a/1" in text and sha in text and "Published (UTC)" in text
    assert "telegram_post.json" in text and "SECTION 63" in text and "[[" in text    # fields to complete


def test_feedback_export(tmp_path):
    io = client("io")
    io.post(f"/api/alerts/{OUT['same'].alert_id}/decision", json={"decision": "needs_info"})
    with SessionLocal() as s:
        res = watcher_api.export_feedback(s, str(tmp_path))
    assert res["needs_info"] >= 1
    posts = [json.loads(x) for x in (tmp_path / "posts.jsonl").read_text().splitlines()]
    decs = {d["post_id"]: d for d in map(json.loads, (tmp_path / "decisions.jsonl").read_text().splitlines())}
    gold = {g["post_id"]: g for g in map(json.loads, (tmp_path / "gold.jsonl").read_text().splitlines())}
    assert decs["tg:api_a:1"]["category"] == "account_sale" and gold["tg:api_a:1"]["label"] == "mule_account_sale"
    assert decs["tg:api_b:2"]["category"] == "unrelated" and gold["tg:api_b:2"]["label"] == "benign"
    assert "tg:api_c:1" not in decs                                   # needs info: not labelled
    assert decs["tg:api_a:1"]["reviewer"] != "io"
    blob = (tmp_path / "posts.jsonl").read_text()
    assert "77001" not in blob and "[PHONE]" in blob and all(p["entities"] for p in posts if "[PHONE]" in p["text"])
    assert (tmp_path / "gold.jsonl").stat().st_mode & 0o077 == 0
    with SessionLocal() as s:
        assert s.query(AlertDecision).count() >= 3
