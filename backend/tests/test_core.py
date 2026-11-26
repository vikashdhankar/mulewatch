"""Core detection tests:  cd backend && python -m pytest -q"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("MW_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.coordination import compute  # noqa: E402
from app.extract import extract_entities, find_keywords  # noqa: E402
from app.ml import retrain  # noqa: E402
from app.pipeline import base_training_set  # noqa: E402
from app.scoring import analyze  # noqa: E402

retrain(base_training_set())


def test_entities():
    e = extract_entities("Call 92000 41736 or +91-9200 93 6612, pay kit77@ybl, t.me/kitwala_jpr, wa.me/919200825519 "
                         "IFSC SBIN0001234, USDT TQ7Xk2YpZ6bM1rJ9aV8fW3eN4cL5hG2sD1, mail a@b.com")
    assert "+919200041736" in e["phone"] and "+919200936612" in e["phone"]
    assert e["upi"] == ["kit77@ybl"]
    assert e["telegram"] == ["t.me/kitwala_jpr"]
    assert "+919200825519" in e["whatsapp"]
    assert e["ifsc"] == ["SBIN0001234"]
    assert e["crypto_wallet"] and e["email"] == ["a@b.com"]


def test_obfuscation_and_hindi():
    terms = {h["term"] for h in find_keywords("fr3sh acc0unt kit r3ady, a.t.m card with pin")}
    assert {"account kit", "card with pin"} <= terms
    assert any(h["term"] == "किराये पर खाता" for h in find_keywords("गेमिंग के लिए किराये पर खाता उपलब्ध"))


SUSPICIOUS = [
    "SBI current account available, full kit with ATM passbook net banking, KYC done 15k. t.me/fastkit_99",
    "Bhai apna khata kiraye pe do, har mahine 25k. Sirf gaming ke liye. WhatsApp 92005 43210",
    "Debit cards with PIN available, bulk, replacement guarantee. Pay kit@okaxis",
    "बैंक खाता उपलब्ध है, पूरा किट मिलेगा। संपर्क 9200543210",
]
BENIGN = [
    "Never sell or rent your bank account — it makes you a money mule. Report to 1930.",
    "Lost my ATM card, how do I block it quickly?",
    "Selling my old cycle for 3000, call 9200456780",
    "Which bank is best for a current account for my small shop?",
    "Opened my first savings account today and got a debit card!",
]


def test_separation():
    for t in SUSPICIOUS:
        assert analyze(t)["base_score"] >= 80, t
    for t in BENIGN:
        assert analyze(t)["base_score"] < 30, t


def test_card_photo_without_sale_language_is_low():
    ocr = "NAGAR SAHAKARI BANK PLATINUM 4718 XXXX XXXX 2041 VALID THRU 08/29 DEBIT RuPay"
    assert analyze("Finally got my first debit card!", ocr)["base_score"] < 30
    assert analyze("DM for details", ocr + " ATM CARD WITH PIN AVAILABLE")["base_score"] >= 55


def test_rings():
    P = lambda i, text: SimpleNamespace(id=i, text=text, ocr_text="", image_phash="", entities=extract_entities(text))
    posts = [P(1, "kit available call 92000 41736"), P(2, "ready account, WA 9200041736"),
             P(3, "unrelated post about momos"), P(4, "join t.me/abc_kit"), P(5, "full kit t.me/abc_kit")]
    c = compute(posts)
    assert c[1]["cluster"] == c[2]["cluster"] and c[4]["cluster"] == c[5]["cluster"]
    assert c[3]["cluster"] is None or c[3]["cluster"] not in (c[1]["cluster"], c[4]["cluster"])


def test_fetcher_page_parsing_and_ssrf_guard(monkeypatch):
    import pytest

    from app.fetcher import FetchError, _check_host, _from_page, _Page, platform_for
    html = """<html><head><title>Ad</title><meta property="og:title" content="Current account full kit">
    <meta property="og:description" content="ATM + passbook, KYC done. Call 92000 41736">
    <meta property="og:image" content="/poster.png"><script>var x=1</script></head>
    <body><nav>Menu</nav><article><p>Telegram t.me/kitwala_jpr</p></article><footer>c</footer></body></html>"""
    page = _Page()
    page.feed(html)
    info = _from_page(page, "https://example.com/ad/1")
    assert info["title"] == "Current account full kit"
    assert "92000 41736" in info["text"] and "t.me/kitwala_jpr" in info["text"]
    assert "var x" not in info["text"] and "Menu" not in info["text"]
    assert info["images"][0] == "/poster.png"

    ld = """<script type="application/ld+json">{"@type":"SocialMediaPosting","headline":"Earn 30k",
    "articleBody":"Apna khata kiraye pe do","author":{"name":"seller1"},"image":"/a.png"}</script>"""
    page = _Page()
    page.feed("<html><head>" + ld + "</head><body>Loading</body></html>")
    info = _from_page(page, "https://example.com/p/2")
    assert info["text"] == "Apna khata kiraye pe do" and info["author"] == "seller1"

    assert platform_for("https://m.facebook.com/groups/1") == "Facebook"
    monkeypatch.delenv("ALLOW_PRIVATE_URLS", raising=False)
    monkeypatch.setenv("FORUM_URL", "https://charcha.openhippo.in")
    for bad in ("http://127.0.0.1:8000/api/stats", "http://localhost/", "http://192.168.1.10/", "file:///etc/passwd"):
        with pytest.raises(FetchError):
            _check_host(bad)


def test_comment_style_texts():
    assert analyze("Contact 767824655 to earn money")["base_score"] >= 55        # malformed number still counts
    assert analyze("Students! Earn 2000 daily from home, no investment. WhatsApp 92000 01122")["base_score"] >= 55
    for ok in ("Thanks, very helpful post!", "dm kiya bhai", "Interested!",
               "Part-time food delivery partners needed, weekly payout. Call 9200501234"):
        assert analyze(ok)["base_score"] < 30, ok


def test_buyer_side_card_data_request():
    t = "I will give 10000 for ATM Card details. It will not be used for Frauds. Contact 0123456789"
    assert analyze(t)["base_score"] >= 80
    assert analyze("Need ATM card, 5k dunga, koi risk nahi. DM")["base_score"] >= 55
    for ok in ("Never share your card details or OTP with anyone. Report fraud to 1930.",
               "I will pay the rent via UPI tomorrow, please share account details",
               "Which bank is best for a current account for my boutique? Need a current account with UPI QR."):
        assert analyze(ok)["base_score"] < 30, ok
