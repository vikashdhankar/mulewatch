"""Reporting bot logic, driven with a fake Telegram API:  python -m pytest -q tests"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("MW_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import reportbot  # noqa: E402
from app.db import Post, Report, SessionLocal, init_db  # noqa: E402
from app.ml import model, retrain  # noqa: E402
from app.pipeline import base_training_set  # noqa: E402

POSTER = Path(__file__).resolve().parents[2] / "forum" / "seed" / "images" / "kit_poster_v2.png"


class FakeTG:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text, reply_to=None, markup=None):
        if text == reportbot.ASK_PHONE:              # the optional phone question, kept apart from replies
            self.asks = getattr(self, "asks", []) + [(chat_id, markup)]
            return
        self.sent.append((chat_id, text))

    def typing(self, chat_id):
        pass

    def download(self, file_id):
        return POSTER.read_bytes()


def upd(chat, text=None, **extra):
    msg = {"message_id": 1, "chat": {"id": chat, "type": "private"}, "from": {"id": chat, "first_name": "Asha"}}
    if text is not None:
        msg["text"] = text
    msg.update(extra)
    return {"update_id": 1, "message": msg}


def setup_module():
    init_db()
    if not model().trained:
        retrain(base_training_set())


def test_reporting_flow():
    tg = FakeTG()
    reportbot.handle_update(upd(101, "/start"), tg)
    assert "report suspicious financial ads" in tg.sent[-1][1]

    ad = "SBI current account full kit available, ATM + passbook + net banking, KYC done. 15k. Call 92000 41736"
    reportbot.handle_update(upd(101, ad), tg)
    reply = tg.sent[-1][1]
    assert "scam" in reply and "MW-" in reply and "1930" in reply

    # same ad from another person -> same case, counted twice
    reportbot.handle_update(upd(202, ad.replace("15k", "16k")), tg)
    assert "Already reported by 2 people" in tg.sent[-1][1]

    # forwarded from a public channel: the channel becomes an identifier that links posts
    reportbot.handle_update(upd(303, "Fresh current account kit ready, DM now", forward_origin={
        "type": "channel", "chat": {"id": -100, "type": "channel", "title": "Kit Wala", "username": "kitwala_jpr"}}), tg)
    with SessionLocal() as s:
        p = s.query(Post).order_by(Post.id.desc()).first()
        assert "t.me/kitwala_jpr" in p.entities.get("telegram", [])
        assert any("Forwarded from channel Kit Wala" in r for r in p.reasons)

    # screenshot only
    reportbot.handle_update(upd(404, None, photo=[{"file_id": "small"}, {"file_id": "big"}]), tg)
    assert "scam" in tg.sent[-1][1].lower()

    # harmless message
    reportbot.handle_update(upd(505, "Is this the right number for SBI customer care? Need help with my passbook"), tg)
    assert "No signs of account or card selling" in tg.sent[-1][1]

    reportbot.handle_update(upd(101, "/status"), tg)
    assert "Your recent reports" in tg.sent[-1][1] and "under review" in tg.sent[-1][1]

    with SessionLocal() as s:
        assert s.query(Report).count() == 5
        reported = {r.post_id for r in s.query(Report).all()}
        assert {p.source for p in s.query(Post).filter(Post.id.in_(reported)).all()} == {"citizen"}


def test_rate_limit(monkeypatch):
    monkeypatch.setattr(reportbot, "REPORTS_PER_HOUR", 2)
    tg = FakeTG()
    for i in range(3):
        reportbot.handle_update(upd(999, f"some message number {i} about nothing in particular"), tg)
    assert "a lot of reports" in tg.sent[-1][1]


def test_link_alerts_with_code():
    from app.alerts import alert_chat_id
    tg = FakeTG()
    reportbot.handle_update(upd(4242, "/alerts 000000"), tg)
    assert "followed by the code" in tg.sent[-1][1] and alert_chat_id() == ""
    reportbot.handle_update(upd(4242, f"/alerts {reportbot.ALERT_CODE}"), tg)
    assert "Linked" in tg.sent[-1][1] and alert_chat_id() == "4242"
    reportbot.handle_update(upd(4242, "/alerts off"), tg)
    assert "turned off" in tg.sent[-1][1] and alert_chat_id() == ""


def test_victim_report_is_a_fraud_attempt():
    tg = FakeTG()
    reportbot.handle_update(upd(7070, "I want to report fraud. This random guy called me and was asking for my ATM "
                                      "car d number and PIN number. He was telling my card will be blocked"), tg)
    reply = tg.sent[-1][1]
    assert "This is a fraud attempt" in reply and "1930" in reply and "Looks OK" not in reply
    with SessionLocal() as s:
        p = s.query(Post).order_by(Post.id.desc()).first()
        assert p.category == "Reported Fraud Attempt" and p.risk_level in ("High", "Critical")


def test_startup_rescore_upgrades_old_citizen_reports():
    from app.db import Alert
    from app.pipeline import ingest, rescore_all
    text = "Someone called from SBI KYC department and asked me to share OTP, said account will be blocked"
    with SessionLocal() as s:
        p = ingest(s, text=text, source="manual")      # scored the old way (no victim rules)
        assert p.risk_level == "Low"
        p.source = "citizen"
        s.commit()
        rescore_all(s, alert=True)
        p = s.get(Post, p.id)
        assert p.category == "Reported Fraud Attempt" and p.risk_level in ("High", "Critical")
        assert s.query(Alert).filter_by(post_id=p.id).count() == 1


def test_reporter_identity_is_stored_and_shown_to_analyst_with_audit():
    import json
    from fastapi.testclient import TestClient
    from app import auth
    from app.db import AuditLog
    from app.main import app
    auth.ensure_demo_users()
    tg = FakeTG()
    ad = "Bank khata kiraye pe do, 30k monthly, ATM + passbook bhejo. WhatsApp +91 01148 25519"
    u = upd(303, ad)
    u["message"]["from"] = {"id": 7000000303, "first_name": "Ravi", "last_name": "Demo", "username": "ravi_demo_reporter"}
    reportbot.handle_update(u, tg)
    assert "investigators" in reportbot.WELCOME and "username" in reportbot.WELCOME
    with SessionLocal() as s:
        r = s.query(Report).filter_by(reporter_username="ravi_demo_reporter").one()
        assert r.reporter_user_id == "7000000303" and r.reporter_name == "Ravi Demo"
        pid = r.post_id
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": "analyst", "password": auth.DEMO_PASSWORD}).status_code == 200
    rep = [x for x in c.get(f"/api/posts/{pid}").json()["citizen_reports"] if x["username"] == "ravi_demo_reporter"][0]
    assert rep["user_id"] == "7000000303" and rep["name"] == "Ravi Demo"          # not masked for analysts
    assert rep["profile"] == "https://t.me/ravi_demo_reporter"
    with SessionLocal() as s:
        a = s.query(AuditLog).filter_by(action="reporters.viewed", case_id=pid).order_by(AuditLog.id.desc()).first()
        assert a is not None and "ravi_demo_reporter" in json.dumps(a.detail)
    assert any(x["by"]["username"] == "ravi_demo_reporter" for x in c.get("/api/bot").json()["recent"])



def test_phone_is_optional_own_number_only_and_blocking_stops_reports():
    from fastapi.testclient import TestClient
    from app import auth
    from app.db import AuditLog, Reporter
    from app.main import app
    auth.ensure_demo_users()
    tg = FakeTG()
    who = {"id": 7000000404, "first_name": "Meena", "username": "meena_demo"}

    def send(**m):
        u = upd(7000000404, m.pop("text", None), **m)
        u["message"]["from"] = who
        reportbot.handle_update(u, tg)

    send(text="Current account kit for sale, ATM + passbook + SIM, 18k. WhatsApp +91 01148 25520")
    assert "MW-" in tg.sent[-1][1]
    assert tg.asks == [(7000000404, reportbot.PHONE_KB)]             # asked once, after the verdict
    send(text="Savings account on rent, 25k per month, passbook + ATM. Telegram @kit_rent_demo")
    assert "MW-" in tg.sent[-1][1] and len(tg.asks) == 1             # not asked again the same day

    send(text=reportbot.SKIP_BTN)                                     # the button text is not filed as a report
    assert "keep reporting" in tg.sent[-1][1]
    send(contact={"phone_number": "919200011223", "user_id": 7000000999, "first_name": "Someone else"})
    assert "your own" in tg.sent[-1][1]
    send(contact={"phone_number": "919200011223", "user_id": 7000000404, "first_name": "Meena"})
    with SessionLocal() as s:
        assert s.get(Reporter, "7000000404").phone == "+919200011223"
        pid = s.query(Report).filter_by(reporter_user_id="7000000404").first().post_id

    c = TestClient(app)
    c.post("/api/auth/login", json={"username": "analyst", "password": auth.DEMO_PASSWORD})
    r = [x for x in c.get(f"/api/posts/{pid}").json()["citizen_reports"] if x["user_id"] == "7000000404"][0]
    assert r["phone"] != "+919200011223" and r["username"] == "meena_demo"          # masked for analysts
    assert c.post("/api/reporters/7000000404/block", json={"reason": "spam"}).status_code == 403
    c.post("/api/auth/login", json={"username": "io", "password": auth.DEMO_PASSWORD})
    r = [x for x in c.get(f"/api/posts/{pid}").json()["citizen_reports"] if x["user_id"] == "7000000404"][0]
    assert r["phone"] == "+919200011223"
    assert c.post("/api/reporters/7000000404/block", json={"reason": "spam"}).status_code == 403

    c.post("/api/auth/login", json={"username": "sho", "password": auth.DEMO_PASSWORD})
    assert c.post("/api/reporters/7000000404/block", json={"reason": "spam and abuse"}).status_code == 200
    with SessionLocal() as s:
        before = s.query(Report).count()
    send(text="Another kit for sale, 20k, ATM + passbook, call +91 01148 25521")
    send(text="/start")
    with SessionLocal() as s:
        assert s.query(Report).count() == before                      # nothing filed while blocked
        assert s.query(AuditLog).filter_by(action="reporter.blocked").count() >= 1
    assert tg.sent[-1][1] == reportbot.BLOCKED
    r = [x for x in c.get(f"/api/posts/{pid}").json()["citizen_reports"] if x["user_id"] == "7000000404"][0]
    assert r["blocked"] and r["blocked_by"] == "sho" and r["block_reason"] == "spam and abuse"
    assert c.delete("/api/reporters/7000000404/block").status_code == 200
    send(text="Another kit for sale, 20k, ATM + passbook, call +91 01148 25521")
    with SessionLocal() as s:
        assert s.query(Report).count() == before + 1
