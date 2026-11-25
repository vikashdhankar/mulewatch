"""Redaction: every identifier is masked, the masked text keeps the rest of the post, and the same
identifier written differently gets the same keyed hash."""
import pytest

from pii.redact import Redactor, residual_pii

SALT = "test-salt-0123456789abcdef"


@pytest.fixture(scope="module")
def red():
    return Redactor(SALT)


def types(red, text):
    return [e.type for e in red.find(text)]


def masked(red, text):
    return red.redact(text)[0]


# ----------------------------------------------------------------------------- English

@pytest.mark.parametrize("text,expected_types", [
    ("Current account kit available, call +91 98290 41736 now", ["PHONE"]),
    ("WhatsApp 9829041736 for details", ["PHONE"]),
    ("Contact 098290-41736", ["PHONE"]),
    ("Pay advance to rahul.kits@ybl and send screenshot", ["UPI"]),
    ("Email me at seller.kits99@gmail.com", ["EMAIL"]),
    ("Join https://bit.ly/3xYzAbc for more", ["URL"]),
    ("Card 4111 1111 1111 1111 with PIN", ["CARD"]),
    ("Card no 4111111111111111 exp 09/29", ["CARD"]),
    ("Debit card XXXX XXXX XXXX 1234 ready", ["CARD"]),
    ("A/c no: 50100234567890 IFSC HDFC0001234", ["ACCOUNT"]),
    ("Account 3456 7890 1234 savings", ["ACCOUNT"]),
    ("DM @kit_seller_official on telegram", ["HANDLE"]),
    ("Channel t.me/kit_seller_official", ["HANDLE"]),
    ("Chat on wa.me/919829041736", ["PHONE"]),
    ("Call +44 7700 900123 abroad", ["PHONE"]),
    ("PAN ABCDE1234F and aadhaar 2345 6789 0123 provided", ["ID", "ID"]),
])
def test_english(red, text, expected_types):
    assert types(red, text) == expected_types
    assert residual_pii(masked(red, text)) == []


def test_english_post_keeps_context(red):
    text = "Corporate current account kit ₹25,000. Contact +91-98290-41736 or pay to kits@okaxis. IFSC SBIN0001234"
    out = masked(red, text)
    assert out == "Corporate current account kit ₹25,000. Contact [PHONE] or pay to [UPI]. IFSC SBIN0001234"


# ----------------------------------------------------------------------------- Hinglish

@pytest.mark.parametrize("text,expected", [
    ("Apna khata do aur 2000 roz kamao, call karo 98290 41736 pe",
     "Apna khata do aur 2000 roz kamao, call karo [PHONE] pe"),
    ("Paise rahul123@paytm pe bhejo bhai", "Paise [UPI] pe bhejo bhai"),
    ("Khata no. 3456 7890 1234 wala account chahiye", "Khata no. [ACCOUNT] wala account chahiye"),
    ("ATM card milega 5000 me, msg karo @atm_wala_bhai", "ATM card milega 5000 me, msg karo [HANDLE]"),
    ("Naya current account 15000-20000 me milega, WhatsApp wa.me/918875936612",
     "Naya current account 15000-20000 me milega, WhatsApp [PHONE]"),
    ("UPI: kitwala(at)ybl pe advance", "UPI: [UPI] pe advance"),
    ("Number 9 8 2 9 0 4 1 7 3 6 pe sampark kare", "Number [PHONE] pe sampark kare"),
])
def test_hinglish(red, text, expected):
    assert masked(red, text) == expected


# ----------------------------------------------------------------------------- Hindi

@pytest.mark.parametrize("text,expected", [
    ("खाता किराये पर दें, संपर्क करें 9829041736", "खाता किराये पर दें, संपर्क करें [PHONE]"),
    ("संपर्क: ९८२९०४१७३६", "संपर्क: [PHONE]"),                       # Devanagari digits
    ("खाता संख्या 123456789012 पर पैसे आएँगे", "खाता संख्या [ACCOUNT] पर पैसे आएँगे"),
    ("भुगतान kit.wala@oksbi पर करें", "भुगतान [UPI] पर करें"),
    ("आधार 2345 6789 0123 चाहिए", "आधार [ID] चाहिए"),
    ("एटीएम कार्ड 4111-1111-1111-1111 उपलब्ध", "एटीएम कार्ड [CARD] उपलब्ध"),
    ("टेलीग्राम पर जुड़ें t.me/khata_seller", "टेलीग्राम पर जुड़ें [HANDLE]"),
])
def test_hindi(red, text, expected):
    assert masked(red, text) == expected


# ----------------------------------------------------------------------------- not PII

@pytest.mark.parametrize("text", [
    "Price ₹25,000 only, 2 kits left",
    "Range 15000-20000 per account",
    "IFSC SBIN0001234 branch Jaipur",
    "Meeting at 10:30 on 25-11-2026",
    "Beware of fake job offers. Never share your account with anyone. Report on 1930.",
    "₹1.5 lakh daily earning",
    "खाता किराये पर देना अपराध है",
])
def test_no_false_positives(red, text):
    assert red.find(text) == []


# ----------------------------------------------------------------------------- hashing and linking

def test_same_phone_any_format_same_hash(red):
    variants = ["+91 98290 41736", "098290-41736", "9829041736", "wa.me/919829041736", "९८२९०४१७३६",
                "0091 9829041736"]
    hashes = {red.redact(v)[1][0]["hash"] for v in variants}
    assert len(hashes) == 1


def test_handle_and_tme_link_same_hash(red):
    a = red.redact("@Kit_Seller")[1][0]["hash"]
    b = red.redact("https://t.me/kit_seller/123")[1][0]["hash"]
    assert a == b


def test_hash_depends_on_salt_and_type():
    a = Redactor(SALT).redact("9829041736")[1][0]["hash"]
    b = Redactor(SALT + "x").redact("9829041736")[1][0]["hash"]
    assert a != b
    r = Redactor(SALT)
    assert r.hash("PHONE", "123456789") != r.hash("ACCOUNT", "123456789")


def test_records_never_carry_value(red):
    text = "pay rahul.kits@ybl or 9829041736, card 4111 1111 1111 1111"
    out, ents = red.redact(text)
    blob = repr(ents)
    for secret in ("rahul", "9829041736", "4111"):
        assert secret not in blob
    assert {e["type"] for e in ents} == {"UPI", "PHONE", "CARD"}
    assert next(e for e in ents if e["type"] == "UPI")["meta"]["psp"] == "ybl"
    for e in ents:                                    # spans point at the placeholder in the masked text
        assert out[e["start"]:e["end"]] == f"[{e['type']}]"


def test_short_salt_refused():
    with pytest.raises(ValueError):
        Redactor("short")


def test_redact_post_fields(red):
    post = {"post_id": "tg:somechan:5", "channel": "somechan", "date": "2026-01-01T00:00:00+00:00",
            "text": "Current account chahiye? call 9829041736", "ocr_text": "UPI kits@ybl",
            "media_type": "photo", "views": 10, "message_id": 5}
    r = red.redact_post(post)
    assert r["text"] == "Current account chahiye? call [PHONE]"
    assert r["ocr_text"] == "UPI [UPI]"
    assert [e["field"] for e in r["entities"]] == ["text", "ocr_text"]
    assert r["lang"] == "hinglish"
    h = red.redact_post(post, hash_channel=True)
    assert h["channel"].startswith("ch_") and "somechan" not in h["post_id"]


def test_cli_dedupes_and_writes_private_file(tmp_path, monkeypatch):
    import json
    import os
    import stat

    from pii import redact as mod
    raw = tmp_path / "raw.jsonl"
    post = {"post_id": "tg:c:1", "channel": "c", "date": "2026-01-01T00:00:00+00:00",
            "text": "call 9829041736", "ocr_text": ""}
    raw.write_text((json.dumps(post) + "\n") * 2)
    monkeypatch.setenv("RESEARCH_HASH_SALT", SALT)
    out = tmp_path / "red.jsonl"
    mod.main([str(raw), "--out", str(out)])
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["text"] == "call [PHONE]"
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o600
