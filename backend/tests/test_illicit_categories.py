"""Drugs, arms and fake documents (Rajasthan Police problem statement): sale ads are flagged and categorised,
while news, awareness, prescriptions and everyday shops using the same words stay low. Made-up text only."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("MW_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ml import retrain  # noqa: E402
from app.pipeline import base_training_set  # noqa: E402
from app.scoring import analyze, categorize  # noqa: E402


def setup_module():
    retrain(base_training_set())


def _score(text):
    a = analyze(text)
    return a["base_score"], categorize(set(a["groups"]), a["entities"], a["base_score"])


@pytest.mark.parametrize("text,category", [
    ("Malana cream 🍁 aur OG available, Jaipur home delivery, DM for rate. WhatsApp +91 01000 33333", "Drug Sale"),
    ("❄️❄️ pure maal ready, discreet packing, all india delivery 📦 Telegram @snow_demo_jpr", "Drug Sale"),
    ("गांजा और चरस उपलब्ध, होम डिलीवरी, संपर्क +91 01000 55555", "Drug Sale"),
    ("Desi katta 315 bore available, kartoos bhi milenge. No licence needed. DM @arms_demo", "Arms Sale"),
    ("🔫 9mm pistol ready stock, safe delivery Rajasthan. Price inbox karo", "Arms Sale"),
    ("Fake aadhaar aur PAN card bina documents 2 din mein, DL without test. WhatsApp +91 01000 66666", "Fake Documents"),
])
def test_illicit_sale_ads_are_flagged(text, category):
    score, cat = _score(text)
    assert score >= 55 and cat == category, (score, cat)


@pytest.mark.parametrize("text", [
    "Jaipur police ne 5 kg ganja ke saath do logon ko giraftar kiya, NDPS act mein case darj",
    "Nasha mukti abhiyan: say no to drugs. Drug free Rajasthan ke liye call karein",
    "Snowfall in Shimla today ❄️❄️ so beautiful, planning a trip next week",
    "Toy gun 🔫 and water pistol for Holi, home delivery available, order now",
    "Holi special: water guns 🔫 aur pichkari, home delivery. Water pistol, toy gun, gulal combo. Wholesale rate, ready stock",
    "Aadhaar update camp at CSC centre tomorrow, bring original documents. Visit official website uidai",
    "HP ink cartridges available, home delivery, best rate list in Jaipur",
    "9mm plywood sheets ready stock, home delivery all Jaipur",
    "1 katta gehun 50 kg available, home delivery Sikar",
    "Corex syrup available only with prescription at our licensed pharmacy",
    "Fresh mint leaves 🌿🍃 and organic veggies, home delivery Udaipur, order now",
    "AC sale ❄️ 1.5 ton, home delivery and free installation, DM for price",
])
def test_same_words_in_everyday_posts_stay_low(text):
    score, cat = _score(text)
    assert score < 30 and cat == "Benign", (score, cat)


def test_toy_words_do_not_hide_a_weapon_ad():
    score, cat = _score("Toy gun nahi, asli pistol chahiye? 9mm ready stock, no licence needed. DM t.me/x_demo")
    assert score >= 55 and cat == "Arms Sale", (score, cat)


def test_banking_category_wins_when_both_appear():
    _, cat = _score("Ganja bhi milega aur SBI current account full kit ATM + passbook, 18k. WhatsApp +91 01000 77777")
    assert cat in ("Mule Account Sale", "Card Sale", "Account-Holder Recruitment")
