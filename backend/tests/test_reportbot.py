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

POSTER = Path(__file__).resolve().parents[2] / "forum" / "seed" / "images" / "kit_poster.png"


class FakeTG:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text, reply_to=None):
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

    ad = "SBI current account full kit available, ATM + passbook + net banking, KYC done. 15k. Call 98290 41736"
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
