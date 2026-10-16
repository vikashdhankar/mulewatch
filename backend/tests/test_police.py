"""Police workflow tests:  cd backend && python -m pytest -q tests"""
import io
import os
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("MW_DATA_DIR", tempfile.mkdtemp())
os.environ["MW_SCREENSHOTS"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import audit, auth, banks, complaints, jurisdiction, legal, workflow  # noqa: E402
from app.db import Post, SessionLocal, User, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.masking import mask_text  # noqa: E402
from app.ml import retrain  # noqa: E402
from app.pipeline import base_training_set, ingest, recompute_all  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "docs" / "samples" / "sample_ncrp_complaints.csv"
KIT_AD = ("SBI current account kit available, ATM + passbook + net banking, KYC done. 18k per account. "
          "Telegram t.me/kitwala_jpr or call 98290 41736. Jaipur delivery")
RENT_AD = "Apna khata kiraye pe do, har mahine 30k. Payment UPI se: earnfast21@ybl WhatsApp 70148 25519"


def setup_module():
    init_db()
    auth.ensure_demo_users()
    retrain(base_training_set())


def client(user: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": user, "password": auth.DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    return c


def new_case(text: str, **kw) -> int:
    with SessionLocal() as s:
        p = ingest(s, text=text, platform="Charcha forum", author=kw.pop("author", "seller1"),
                   url=kw.pop("url", "http://forum.test/p/1"), source="forum", **kw)
        s.commit()
        return p.id


# ----------------------------------------------------------------------------- normalisers

def test_complaint_normalisers():
    assert complaints.norm_values("phone", "98290 41736 / +91-70148-25519") == [
        ("phone", "+919829041736"), ("phone", "+917014825519")]
    assert complaints.norm_values("upi", "EarnFast21@YBL") == [("upi", "earnfast21@ybl")]
    assert complaints.norm_values("account", "5010-0234-5678-12") == [("account", "50100234567812")]
    assert ("handle", "kitwala_jpr") in complaints.norm_values("url", "https://t.me/kitwala_jpr")
    assert ("handle", "cardzone_x") in complaints.norm_values("url", "@cardzone_x")
    assert complaints.norm_values("phone", "NA") == []


def test_mapping_guess_skips_victim_columns():
    m = complaints.guess_mapping(["Acknowledgement No", "Complainant Name", "Victim Mobile", "Suspect Mobile",
                                  "Suspect UPI / VPA", "Amount Lost (Rs)", "District", "Suspect Bank A/c No"])
    assert m["Acknowledgement No"] == "complaint_id"
    assert m["Complainant Name"] == "" and m["Victim Mobile"] == ""
    assert m["Suspect Mobile"] == "phone" and m["Suspect UPI / VPA"] == "upi"
    assert m["Suspect Bank A/c No"] == "account" and m["Amount Lost (Rs)"] == "amount"


# ----------------------------------------------------------------------------- banks & jurisdiction

def test_ifsc_and_upi_mapping():
    i = banks.ifsc_info("SBIN0000001")
    assert i["bank"] == "State Bank of India" and i["found"]
    assert banks.upi_info("earnfast21@ybl")["bank"] == "Yes Bank"
    assert banks.upi_info("x@okaxis")["app"] == "Google Pay"
    p = Post(entities={"upi": ["a@ybl", "b@oksbi"], "ifsc": ["HDFC0000001"], "bank_account": ["50100234567812"]})
    groups = {g["bank_code"]: g for g in banks.routes(p)}
    assert set(groups) >= {"YESB", "SBIN", "HDFC"}
    assert any(it["kind"] == "account" for it in groups["HDFC"]["items"])


def test_jurisdiction_from_places_and_handles():
    p = Post(text="Kit available, Malviya Nagar delivery. t.me/kitwala_jpr", entities={})
    j = jurisdiction.suggest(p)
    assert j["district"] == "Jaipur" and "approximate" in j["note"].lower() or j["district"] == "Jaipur"
    assert jurisdiction.suggest(Post(text="जोधपुर में खाता उपलब्ध", entities={}))["district"] == "Jodhpur"
    assert jurisdiction.suggest(Post(text="nothing here", entities={}))["district"] == ""
    assert jurisdiction.district_for_name("CHITTAURGARH") == "Chittorgarh"


# ----------------------------------------------------------------------------- roles & audit

def test_login_roles_and_audit_chain():
    anon = TestClient(app)
    assert anon.get("/api/stats").status_code == 401
    assert anon.post("/api/auth/login", json={"username": "io", "password": "wrong"}).status_code == 401
    analyst, io, sho = client("analyst"), client("io"), client("sho")
    assert analyst.get("/api/auth/me").json()["role"] == "ANALYST"
    pid = new_case(KIT_AD)
    assert analyst.get(f"/api/posts/{pid}").status_code == 200
    assert analyst.patch(f"/api/posts/{pid}/case", json={"status": "VERIFIED"}).status_code == 403
    assert analyst.get(f"/api/posts/{pid}/drafts/takedown").status_code == 403
    assert io.get("/api/audit").status_code == 403
    assert sho.get("/api/audit").status_code == 200
    assert io.post("/api/users", json={"username": "x1", "name": "X", "role": "IO", "password": "abc12345"}).status_code == 403
    r = sho.post("/api/users", json={"username": "si_meena", "name": "SI Meena", "role": "IO", "password": "Pass@1234"})
    assert r.status_code == 200 and r.json()["must_change_password"]
    v = sho.get("/api/audit/verify").json()
    assert v["ok"] and v["rows"] > 3
    with SessionLocal() as s:          # the database itself refuses edits
        import sqlalchemy
        try:
            s.execute(sqlalchemy.text("UPDATE audit_log SET username='x' WHERE id=1"))
            s.commit()
            raise AssertionError("audit log was editable")
        except sqlalchemy.exc.DatabaseError:
            s.rollback()


def test_analyst_sees_masked_numbers():
    pid = new_case(KIT_AD)
    a = client("analyst").get(f"/api/posts/{pid}").json()
    o = client("io").get(f"/api/posts/{pid}").json()
    assert "98290 41736" in o["text"] and "98290 41736" not in a["text"]
    assert len(a["text"]) == len(o["text"])                 # highlights stay aligned
    assert all("•" in v for v in a["entities"]["phone"])
    assert mask_text("+919829041736") == "+9198••••••36"


# ----------------------------------------------------------------------------- workflow & clock

def test_status_flow_and_takedown_clock():
    io = client("io")
    pid = new_case(KIT_AD)
    assert io.patch(f"/api/posts/{pid}/case", json={"status": "CONTENT_REMOVED"}).status_code == 400
    assert io.patch(f"/api/posts/{pid}/case", json={"status": "VERIFIED", "assigned_to": None}).status_code == 200
    me = io.get("/api/auth/me").json()
    assert io.patch(f"/api/posts/{pid}/case", json={"assigned_to": me["id"]}).json()["assigned_to"]["id"] == me["id"]
    assert io.patch(f"/api/posts/{pid}/case", json={"status": "FIR_LINKED"}).status_code == 400   # needs a number
    r = io.patch(f"/api/posts/{pid}/case", json={"status": "NOTICE_SENT"}).json()
    assert r["clock"]["state"] == "running" and r["clock"]["window_hours"] == 3
    with SessionLocal() as s:
        p = s.get(Post, pid)
        sent = p.notice_sent_at
        assert workflow.clock(p, sent + timedelta(hours=2, minutes=40))["state"] == "warn"
        assert workflow.clock(p, sent + timedelta(hours=3, minutes=1))["state"] == "overdue"
        p.notice_sent_at = datetime.utcnow() - timedelta(hours=3, minutes=5)
        s.commit()
        assert workflow.check_clocks(s) == 1
        assert workflow.check_clocks(s) == 0                  # alerts once
    r = io.patch(f"/api/posts/{pid}/case", json={"status": "CONTENT_REMOVED"}).json()
    assert r["clock"]["state"] == "late"


def test_repost_after_takedown_is_detected():
    io = client("io")
    pid = new_case("Fresh kit ready, current account + ATM, contact t.me/repost_seller_77 or 9988776655 bulk available",
                   author="seller_a", url="http://forum.test/p/50")
    for st in ("VERIFIED", "NOTICE_SENT", "CONTENT_REMOVED"):
        assert io.patch(f"/api/posts/{pid}/case", json={"status": st}).status_code == 200
    new = new_case("Account kit available again, new id. DM t.me/repost_seller_77 fast service",
                   author="seller_b", url="http://forum.test/p/51")
    with SessionLocal() as s:
        p = s.get(Post, new)
        assert p.repost_of == pid
        assert p.risk_score >= 85
        assert "Reappeared" in p.scores["repost"]


# ----------------------------------------------------------------------------- complaints

def test_complaint_import_and_match():
    io = client("io")
    pid = new_case(RENT_AD, author="earnfast", url="http://forum.test/p/60")
    up = io.post("/api/complaints/upload", files={"file": ("ncrp.csv", SAMPLE.read_bytes(), "text/csv")}).json()
    assert up["rows"] >= 10 and up["mapping"]["Suspect UPI / VPA"] == "upi"
    res = io.post("/api/complaints/import", json={"token": up["token"], "mapping": up["mapping"], "label": "test"}).json()
    assert res["added"] >= 10
    again = io.post("/api/complaints/upload", files={"file": ("ncrp.csv", SAMPLE.read_bytes(), "text/csv")}).json()
    assert io.post("/api/complaints/import", json={"token": again["token"], "mapping": again["mapping"]}).json()["added"] == 0
    with SessionLocal() as s:
        p = s.get(Post, pid)
        assert p.complaint_count >= 1 and p.complaint_amount > 0 and p.risk_score >= 90
    view = io.get(f"/api/posts/{pid}/police").json()
    assert view["complaints"]["items"] and view["complaints"]["items"][0]["complaint_id"].startswith("DEMO-")
    analyst = client("analyst").get(f"/api/posts/{pid}/police").json()
    assert analyst["complaints"]["count"] >= 1 and analyst["complaints"]["items"] is None
    with SessionLocal() as s:              # stored encrypted
        from app.db import Complaint
        c = s.query(Complaint).first()
        assert "DEMO-" not in c.payload and "earnfast" not in c.payload


# ----------------------------------------------------------------------------- drafts & evidence

def test_legal_drafts_and_evidence_pack():
    io = client("io")
    pid = new_case(KIT_AD + " a/c 50100234567812 IFSC HDFC0000001 pay kit77@ybl", url="http://forum.test/p/70")
    assert io.patch(f"/api/posts/{pid}/case", json={"status": "VERIFIED"}).status_code == 200
    for kind in legal.KINDS:
        for lang in ("en", "hi"):
            d = io.get(f"/api/posts/{pid}/drafts/{kind}", params={"lang": lang}).json()
            assert f"MW-{pid:05d}" in d["text"] and "[[" in d["text"]
            for fmt in ("docx", "pdf"):
                r = io.post(f"/api/posts/{pid}/drafts/{kind}/export", json={"text": d["text"], "lang": lang, "format": fmt})
                assert r.status_code == 200 and len(r.content) > 1500
                if fmt == "docx":
                    xml = zipfile.ZipFile(io_bytes(r.content)).read("word/header1.xml").decode()
                    assert "DRAFT" in xml
                else:
                    assert r.content[:4] == b"%PDF"
    bank = io.get(f"/api/posts/{pid}/drafts/bank", params={"bank": "HDFC"}).json()
    assert "HDFC Bank" in bank["text"] and "50100234567812" in bank["text"]
    assert {b["code"] for b in bank["banks"]} >= {"HDFC", "YESB"}
    with SessionLocal() as s:
        assert s.get(Post, pid).status == "NOTICE_DRAFTED"
    view = io.get(f"/api/posts/{pid}/police").json()
    kinds = {f["kind"] for f in view["evidence"]}
    assert {"text", "html"} <= kinds or "text" in kinds
    assert all(f["intact"] for f in view["evidence"])
    pack = io.get(f"/api/posts/{pid}/evidence-pack.zip")
    z = zipfile.ZipFile(io_bytes(pack.content))
    names = z.namelist()
    assert "manifest.json" in names and "chain_of_custody.csv" in names
    assert any(n.startswith("Section63") for n in names)
    assert "evidence.pack_exported" in [r["action"] for r in client("sho").get(f"/api/audit?case={pid}").json()["items"]]


def test_brief_pdf_both_languages():
    sho = client("sho")
    for lang in ("en", "hi"):
        r = sho.get("/api/brief.pdf", params={"lang": lang})
        assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert client("io").get("/api/brief.pdf").status_code == 403


def test_recruiter_ranks_bulk_recruiter_above_single_seller():
    single = new_case("Selling my SBI savings account, KYC done, 8k. call 9123400001", author="one_timer",
                      url="http://forum.test/p/80")
    recruit = new_case("Need savings account holders! Rent your account, har mahine 25k, commission per account. "
                       "Agents wanted, bulk. Students earn easy. WhatsApp 9123400002", author="recruiter_x",
                       url="http://forum.test/p/81")
    with SessionLocal() as s:
        recompute_all(s, alert=False)
        assert s.get(Post, recruit).recruiter_score > s.get(Post, single).recruiter_score


def io_bytes(b: bytes):
    return io.BytesIO(b)


# ----------------------------------------------------------------------------- tier 2/3 additions

def test_phone_circle_hint():
    sug = jurisdiction.suggest(Post(text="Account kit milega", entities={"phone": ["+919829041736"]}))
    assert "Rajasthan" in sug["circles"]
    assert "Rajasthan circle" in sug["note"]
    other = jurisdiction.suggest(Post(text="call now", entities={"phone": ["+919810012345"]}))
    assert "Rajasthan" not in other["circles"] and other["circles"]
    assert "outside Rajasthan" in other["note"]


def test_brief_by_district():
    sho = client("sho")
    r = sho.get("/api/brief.pdf", params={"lang": "hi", "district": "Jaipur"})
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert sho.get("/api/brief.pdf", params={"district": "Atlantis"}).status_code == 400


def test_bulk_link_extraction():
    from app import bulk
    links = bulk.extract_links("https://t.me/kitwala/12  complaint 3120926\nwww.example.com/ad, and t.me/kitwala/12\nno link here")
    assert links[0] == ("https://t.me/kitwala/12", "complaint 3120926")
    assert links[1][0] == "https://www.example.com/ad"
    assert len(links) == 2                                   # duplicates dropped
    csv = "url,note\nhttps://olx.test/item/9,from patrol\n".encode()
    assert bulk.links_from_file("x.csv", csv)[0][0] == "https://olx.test/item/9"


def test_bulk_job_runs_and_makes_cases(monkeypatch):
    import time as _t
    from app import bulk, fetcher

    def fake_fetch(url):
        if "dead" in url:
            raise fetcher.FetchError("Page not found (404)")
        return {"url": url, "final_url": url, "platform": "Web", "author": "", "title": "", "posted_at": "",
                "text": KIT_AD if "kit" in url else "Fresh mangoes for sale in Jaipur, call today",
                "image_paths": [], "how": "test", "note": "", "html": ""}

    monkeypatch.setattr(fetcher, "fetch_url", fake_fetch)
    monkeypatch.setattr(bulk, "PAUSE", 0)
    analyst = client("analyst")
    r = analyst.post("/api/bulk", json={"text": "https://bulk.test/kit-ad  NCRP 999\nhttps://bulk.test/mango\nhttps://bulk.test/dead",
                                         "label": "test list"})
    assert r.status_code == 200, r.text
    jid = r.json()["id"]
    for _ in range(120):
        j = analyst.get(f"/api/bulk/{jid}").json()
        if j["status"] == "done":
            break
        _t.sleep(0.25)
    assert j["status"] == "done", j
    by = {i["url"]: i for i in j["items"]}
    assert by["https://bulk.test/dead"]["status"] == "error"
    kit = by["https://bulk.test/kit-ad"]
    assert kit["status"] == "done" and kit["post"]["risk_level"] in ("High", "Critical")
    assert "XXXX" in kit["post"]["excerpt"] or "41736" not in kit["post"]["excerpt"]   # masked for analysts
    with SessionLocal() as s:
        p = s.get(Post, kit["post"]["id"])
        assert p.source == "bulk" and any("NCRP 999" in x for x in p.reasons)
    # the same link again is reported as an existing case, not a duplicate
    r2 = analyst.post("/api/bulk", json={"text": "https://bulk.test/kit-ad"}).json()
    for _ in range(80):
        j2 = analyst.get(f"/api/bulk/{r2['id']}").json()
        if j2["status"] == "done":
            break
        _t.sleep(0.25)
    assert j2["items"][0]["status"] == "existing"
    assert analyst.post("/api/bulk", json={"text": "nothing here"}).status_code == 400
