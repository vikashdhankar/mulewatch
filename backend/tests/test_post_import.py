"""Dataset import: CSV / JSON / JSONL / Telegram export / ZIP with images -> scored cases (made-up data only)."""
import io
import json
import os
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

os.environ.setdefault("MW_DATA_DIR", tempfile.mkdtemp())
os.environ["MW_SCREENSHOTS"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, post_import  # noqa: E402
from app.db import Post, SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.ml import retrain  # noqa: E402
from app.pipeline import base_training_set  # noqa: E402

MULE = "Apna bank khata kiraye pe do, har mahine 30k commission. ATM + passbook + SIM bhejo. WhatsApp 92008 25519"
KIT = "SBI current account kit available, ATM + passbook + net banking, KYC done. 18k per account. call 92000 41736"
NORMAL = "Good morning everyone, the Jaipur book fair opens on Sunday at 10 am."


def setup_module():
    init_db()
    auth.ensure_demo_users()
    retrain(base_training_set())


def _client(user="io"):
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": user, "password": auth.DEMO_PASSWORD}).status_code == 200
    return c


def _wait(c, jid):
    for _ in range(300):
        j = c.get(f"/api/import/jobs/{jid}").json()
        if j["status"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.1)
    raise AssertionError("import did not finish")


def test_parse_time_formats():
    assert post_import.parse_time("2026-11-20T10:15:00+05:30") == datetime(2026, 11, 20, 4, 45)
    assert post_import.parse_time("1700000000") == datetime(2023, 11, 14, 22, 13, 20)
    assert post_import.parse_time("1700000000000") == datetime(2023, 11, 14, 22, 13, 20)
    assert post_import.parse_time("20/11/2026 14:30") == datetime(2026, 11, 20, 9, 0)      # no zone: IST
    assert post_import.parse_time("2026-11-20 14:30:00Z") == datetime(2026, 11, 20, 14, 30)
    assert post_import.parse_time("") is None and post_import.parse_time("yesterday") is None


def test_guess_mapping_csv_headers():
    m = post_import.guess_mapping(["message_id", "Channel", "Date", "Message", "Sender", "Media", "label"], {})
    assert m == {"message_id": "external_id", "Channel": "channel", "Date": "time", "Message": "text",
                 "Sender": "author", "Media": "image", "label": ""}


def test_csv_import_scores_keeps_time_and_channel_and_dedupes():
    c = _client()
    csv = ("post_id,channel,date,text\n"
           f"1,@kit_wala_test,2026-10-01 09:30,\"{KIT}\"\n"
           f"2,@kit_wala_test,2026-10-02 11:00,\"{MULE}\"\n"
           f"3,@bookfair_test,2026-10-03 08:00,\"{NORMAL}\"\n"
           "4,@bookfair_test,2026-10-03 08:05,\n")
    up = c.post("/api/import/upload", files={"file": ("posts.csv", csv.encode(), "text/csv")}).json()
    assert up["rows"] == 4 and up["format"] == "CSV"
    assert up["mapping"] == {"post_id": "external_id", "channel": "channel", "date": "time", "text": "text"}
    r = c.post("/api/import/start", json={"token": up["token"], "mapping": up["mapping"], "platform": "Telegram"})
    assert r.status_code == 200, r.text
    j = _wait(c, r.json()["id"])
    assert j["status"] == "done" and j["added"] == 3 and j["empty"] == 1 and j["errors"] == 0, j
    top = j["top"][0]
    assert top["risk_level"] in ("High", "Critical") and top["platform"] == "Telegram · @kit_wala_test"
    with SessionLocal() as s:
        kit = s.get(Post, top["id"])
        assert kit.source == "import" and kit.posted_at == datetime(2026, 10, 1, 4, 0)   # 09:30 IST
        assert "+919200041736" in kit.entities.get("phone", []) and kit.evidence_hash
        normal = s.query(Post).filter(Post.source == "import", Post.text == NORMAL).one()
        assert normal.risk_level == "Low"
    # the same file again adds nothing
    up2 = c.post("/api/import/upload", files={"file": ("posts.csv", csv.encode(), "text/csv")}).json()
    j2 = _wait(c, c.post("/api/import/start", json={"token": up2["token"], "mapping": up2["mapping"],
                                                    "platform": "Telegram"}).json()["id"])
    assert j2["added"] == 0 and j2["duplicates"] == 3


def test_telegram_export_zip_with_image():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(buf, "PNG")
    export = {"name": "Khata Kiraya Test", "type": "public_channel", "id": 1, "messages": [
        {"id": 10, "type": "message", "date": "2026-09-05T12:00:00", "date_unixtime": "1788000000", "from": "Khata Kiraya Test",
         "text": ["Account ", {"type": "bold", "text": "kiraye pe do"}, " - 30k monthly, ATM + passbook bhejo"],
         "photo": "photos/photo_1.png"},
        {"id": 11, "type": "service", "date": "2026-09-05T12:01:00", "action": "pin_message"},
    ]}
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("ChatExport/result.json", json.dumps(export))
        zf.writestr("ChatExport/photos/photo_1.png", buf.getvalue())
    c = _client()
    up = c.post("/api/import/upload", files={"file": ("export.zip", z.getvalue(), "application/zip")}).json()
    assert up["format"] == "Telegram export in a ZIP" and up["rows"] == 1 and up["images"] == 1
    assert up["platform"] == "Telegram" and up["channel"] == "Khata Kiraya Test"
    assert up["mapping"]["text"] == "text" and up["mapping"]["photo"] == "image" and up["mapping"]["date_unixtime"] == "time" and up["mapping"]["date"] == ""
    j = _wait(c, c.post("/api/import/start", json={"token": up["token"], "mapping": up["mapping"]}).json()["id"])
    assert j["added"] == 1 and j["images"] == 1, j
    with SessionLocal() as s:
        p = s.get(Post, j["top"][0]["id"])
        assert p.text.startswith("Account kiraye pe do") and p.image_path.startswith("import_") and p.image_phash
        assert p.platform == "Telegram · Khata Kiraya Test" and p.posted_at == datetime.utcfromtimestamp(1788000000)


def test_jsonl_and_json_list_and_errors():
    recs = [{"message": MULE + " (jsonl)", "created_at": "2026-08-01T10:00:00Z", "user": {"name": "seller_x"}}]
    data = "\n".join(json.dumps(r) for r in recs + recs).encode()
    c = _client("analyst")
    up = c.post("/api/import/upload", files={"file": ("p.jsonl", data, "application/json")}).json()
    assert up["format"] == "JSON lines" and up["rows"] == 2
    assert up["mapping"]["message"] == "text" and up["mapping"]["user.name"] == "author"
    j = _wait(c, c.post("/api/import/start", json={"token": up["token"], "mapping": up["mapping"],
                                                   "platform": "Instagram"}).json()["id"])
    assert j["added"] == 1 and j["duplicates"] == 1                    # identical row inside one file
    up = c.post("/api/import/upload", files={"file": ("p.json", json.dumps({"posts": recs}).encode(), "x")}).json()
    assert up["format"] == "JSON" and up["rows"] == 1
    bad = c.post("/api/import/upload", files={"file": ("p.pdf", b"%PDF", "application/pdf")})
    assert bad.status_code == 400
    no_text = c.post("/api/import/start", json={"token": up["token"], "mapping": {"message": ""}})
    assert no_text.status_code == 400 and "text" in no_text.json()["detail"]
