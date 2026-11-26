"""Generate the labelled training corpus for the text classifier.

The corpus is template-generated (English, Hinglish, Hindi) and is deliberately DIFFERENT from the
Charcha forum demo posts, so what the command center catches on the forum is unseen data.
All phone numbers are demo numbers (+91 0..., never assignable); UPI IDs / handles are synthetic.

    python training/generate_training.py   ->  training/training_data.jsonl
"""
import json
import random
from pathlib import Path

random.seed(7)

PRODUCTS = ["current account", "savings account", "saving a/c", "corporate account", "bank account",
            "current a/c", "firm account", "business current account", "khata", "account"]
BANKS = ["SBI", "HDFC", "ICICI", "Axis", "Kotak", "PNB", "BOB", "Canara", "IndusInd", "Yes Bank", "IDFC",
         "AU Bank", "Equitas", "Fino", "Airtel Payments Bank"]
KIT = ["full kit", "complete kit", "ATM + passbook + cheque book", "netbanking + ATM", "kit with SIM",
       "IB + ATM + SIM", "passbook ATM chequebook sim sab milega"]
EXTRA = ["KYC done", "no KYC needed", "pre-activated", "old account 2 year", "high limit", "Aadhaar linked",
         "unlimited limit", "100% working", "replacement guarantee", "trusted seller", "bulk available"]
USE = ["gaming", "betting", "USDT P2P", "crypto withdrawal", "cash out", "online game payout", "trading"]
CONTACT = ["DM", "Telegram only", "WhatsApp", "inbox", "call", "msg"]
PRICE = ["₹8000", "₹12,000", "15k", "₹25000 per account", "20k only", "Rs 18000", "₹9,500/-"]


def phone():
    """A demo number: +91 0XXXXXXXXX. No Indian number starts with 0, so it can never be someone's real mobile."""
    d = "0" + "".join(random.choice("0123456789") for _ in range(9))
    return random.choice(["+91 {}{}{}{}{} {}{}{}{}{}", "+91-{}{}{}{}{}{}{}{}{}{}", "+91{}{}{}{}{}{}{}{}{}{}", "+91 {}{}{}{} {}{} {}{}{}{}"]).format(*d)


def upi():
    return random.choice(["kit", "acc", "bank", "rk", "sonu", "deal", "fast"]) + str(random.randint(10, 999)) + "@" + \
        random.choice(["ybl", "okaxis", "paytm", "ibl", "oksbi", "axl"])


def tg():
    return "t.me/" + random.choice(["acc", "kit", "bank", "ca", "mule", "fast", "trusted"]) + \
        random.choice(["_hub", "_store", "_deal", "wala", "_india", "_seller"]) + str(random.randint(1, 99))


def suspicious():
    p, b = random.choice(PRODUCTS), random.choice(BANKS)
    forms = [
        lambda: f"{b} {p} available with {random.choice(KIT)}. {random.choice(EXTRA)}. {random.choice(PRICE)}. {random.choice(CONTACT)} {tg()}",
        lambda: f"Selling {b} {p} for {random.choice(USE)} work. {random.choice(EXTRA)}, {random.choice(KIT)}. Contact {phone()}",
        lambda: f"{p} kiraye pe chahiye? {b} ka {random.choice(KIT)} ready hai. {random.choice(PRICE)} me. Whatsapp {phone()}",
        lambda: f"Apna bank account do, har mahine {random.choice(['20k', '30k', '₹15000', '50k'])} kamao. Sirf {random.choice(USE)} transactions. Safe hai bhai. DM {tg()}",
        lambda: f"Rent your {p} and earn {random.choice(['₹2000/day', '30k per month', '₹1500 daily'])}. We only use it for {random.choice(USE)}. Payment via {upi()}",
        lambda: f"ATM cards with PIN available, {b} debit card for sale. {random.choice(EXTRA)}. Pay {upi()}",
        lambda: f"Live CC and debit card with CVV available. {random.choice(['Dumps', 'Fullz', 'Cards'])} {random.choice(PRICE)}. {tg()}",
        lambda: f"{b} ka current account chahiye toh contact karo, {random.choice(KIT)}, {random.choice(EXTRA)}. Delivery all India. {phone()}",
        lambda: f"बैंक खाता उपलब्ध है, पूरा किट मिलेगा — एटीएम पासबुक चेकबुक। {random.choice(PRICE)}। संपर्क {phone()}",
        lambda: f"किराये पर खाता चाहिए? गेमिंग के लिए करंट अकाउंट उपलब्ध। व्हाट्सएप {phone()}",
        lambda: f"Need {p} holders urgently. Give your account for {random.choice(USE)} and get commission on your account. {random.choice(CONTACT)} {phone()}",
        lambda: f"F.r.e.s.h {p} r3ady, {random.choice(KIT)}, n0 kyc. {tg()} {random.choice(PRICE)}",
        lambda: f"BULK {p.upper()} AVAILABLE — {b}, {random.choice(BANKS)}, {random.choice(BANKS)}. {random.choice(KIT)}. USDT accepted {random.choice(['TQ7Xk2YpZ6bM1rJ9aV8fW3eN4cL5hG2sD1', '0x9f3a2b1c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a'])}",
        lambda: f"Corporate account available for {random.choice(USE)}, net banking + ATM, {random.choice(EXTRA)}, IFSC {random.choice(['SBIN', 'HDFC', 'ICIC', 'UTIB'])}0{random.randint(100000, 999999)}. {phone()}",
    ]
    return random.choice(forms)()


def benign():
    b = random.choice(BANKS)
    forms = [
        lambda: f"Open a zero balance savings account with {b} through the official app. Visit your nearest branch for details.",
        lambda: "Beware! Never sell or rent your bank account — it is a crime and makes you a money mule. Report to 1930 or cybercrime.gov.in",
        lambda: f"I lost my {b} ATM card yesterday, how to block it? Customer care not responding.",
        lambda: f"{b} credit card annual fee waived for first year, apply online on the official website.",
        lambda: f"Selling my old iPhone 12, 128GB, good condition, ₹28000. Contact {phone()}",
        lambda: f"Room available for rent near Malviya Nagar, ₹7000 per month, students preferred. Call {phone()}",
        lambda: f"Hiring: accountant with 2 years experience, Tally & GST knowledge. Send CV to hr@{random.choice(['abcfoods', 'ravitraders', 'jaipurtex'])}.com",
        lambda: "Which bank is best for opening a current account for a small shop? Need UPI and low charges.",
        lambda: f"My debit card was blocked after 3 wrong PIN attempts, how long does unblock take at {b}?",
        lambda: f"Fraud alert: someone is calling and asking for OTP in the name of {b} KYC update. Don't share!",
        lambda: f"Bike for sale — Honda Activa 2019, single owner, ₹42000. WhatsApp {phone()}",
        lambda: "Study group for GATE CSE starting this Sunday at central library, everyone welcome.",
        lambda: f"Kisi ko pata hai {b} me passbook update kaise hota hai? Machine kaam nahi kar rahi.",
        lambda: "Mera account freeze ho gaya bina kisi reason ke, kya karun? Branch walon ne cyber cell bola.",
        lambda: "सावधान! अपना बैंक खाता किसी को किराये पर न दें, यह अपराध है। 1930 पर शिकायत करें।",
        lambda: f"Second hand books for sale — engineering 3rd year, half price. Contact {phone()}",
        lambda: f"Got my {b} credit card limit increased after 1 year of usage, anyone else?",
        lambda: f"Tiffin service available in Mansarovar, home-made food, ₹2500/month. Call {phone()}",
        lambda: f"How to link Aadhaar with savings account online? Is it mandatory for {b}?",
        lambda: f"Job alert: {b} PO recruitment 2026 notification out, apply online before the last date.",
        lambda: f"Pay rent via UPI {upi()} — landlord asked to share screenshot after payment.",
        lambda: "Workshop on cyber safety: how money mule networks recruit students via Telegram. Register free.",
    ]
    return random.choice(forms)()


# --- illegal goods other than banking material (drugs, arms, fake documents) -----------------------------
# Appended AFTER the original 660 rows so those stay identical. Hard negatives matter most here: police news,
# de-addiction drives, prescriptions, toy guns, printer cartridges, a "katta" (sack) of grain, plants, snow.
CITIES = ["Jaipur", "Jodhpur", "Kota", "Ajmer", "Udaipur", "Bikaner", "Alwar", "Sikar", "Bhilwara", "Barmer"]
DRUG = ["ganja", "charas", "Malana cream", "smack", "MD powder", "mephedrone", "MDMA pills", "LSD blotter",
        "afeem", "doda post", "codeine syrup", "nitro tabs", "hash oil", "OG kush", "heroin", "गांजा", "स्मैक", "अफीम"]
DRUG_EMOJI = ["🍁", "🌿🍃", "💊", "❄️", "🍄", "🔌"]
ARMS = ["desi katta", "tamancha", "country made pistol", "9mm pistol", "315 bore", "32 bore revolver", "mauser",
        "kartoos", "live cartridges", "देसी कट्टा", "तमंचा", "पिस्टल", "कारतूस"]
DOCS = ["fake aadhaar", "duplicate aadhar", "fake PAN card", "fake marksheet", "fake degree", "backdated degree",
        "fake driving licence", "DL without test", "fake voter ID", "फर्जी आधार", "फर्जी मार्कशीट", "फर्जी डिग्री"]
CUE = ["home delivery", "discreet packing", "all india delivery", "same day delivery", "cash on delivery",
       "DM for rate", "price list inbox", "ready stock", "100% pure", "no police tension", "bina licence",
       "stealth shipping", "wholesale rate", "fresh stock", "होम डिलीवरी", "माल उपलब्ध"]
QTY = ["1 gram", "5 gm", "10 gm", "per tola", "per piece", "per sheet", "1 kg", "per strip", "per bottle"]
IPRICE = ["₹800", "₹1500", "2k", "₹3,500", "Rs 600", "₹12000", "25k", "₹45,000", "8k only"]


def illicit():
    c, cue = random.choice(CITIES), random.choice(CUE)
    d, a, f, e = random.choice(DRUG), random.choice(ARMS), random.choice(DOCS), random.choice(DRUG_EMOJI)
    forms = [
        lambda: f"{e} {d} available in {c}, {cue}. {random.choice(IPRICE)} {random.choice(QTY)}. {random.choice(CONTACT)} {tg()}",
        lambda: f"{d} aur {random.choice(DRUG)} milega, {cue}, {c} mein same din. WhatsApp {phone()}",
        lambda: f"Party ke liye {e} {d} ready hai bhai, {cue}. Rate {random.choice(IPRICE)}. Call {phone()}",
        lambda: f"{c} {e}{e} maal ready, {random.choice(['discreet packing', 'stealth shipping', 'no police tension'])}, "
                f"{random.choice(['all india delivery', 'cash on delivery'])}. {tg()}",
        lambda: f"{d} {random.choice(QTY)} {random.choice(IPRICE)} — {cue}. Payment {upi()}",
        lambda: f"{a} available, {random.choice(['bina licence', 'no licence needed', 'ready stock'])}. {c} delivery. "
                f"Price {random.choice(IPRICE)}. DM {tg()}",
        lambda: f"🔫 {a} + {random.choice(['kartoos', 'live rounds', '20 cartridges'])} milenge, {cue}. Contact {phone()}",
        lambda: f"{a} bechna hai, {random.choice(['naya', 'fresh piece', 'used par sahi'])}, {c} mein hand delivery. Rate {random.choice(IPRICE)}. {phone()}",
        lambda: f"{random.choice(ARMS)} aur {random.choice(ARMS)} ka maal ready, police ka dar nahi. WhatsApp {phone()}",
        lambda: f"{f} {random.choice(['2 din mein', 'same day', '24 ghante mein'])}, {random.choice(['bina documents', 'without any document', 'no verification'])}. "
                f"{random.choice(IPRICE)}. {random.choice(CONTACT)} {phone()}",
        lambda: f"{f} aur {random.choice(DOCS)} banwao, {random.choice(['any university', 'any state', 'all India valid'])}. Price inbox. {tg()}",
        lambda: f"Need {f}? Original jaisa, scanning mein pass. {cue}. UPI {upi()}",
        lambda: f"{d} उपलब्ध है, {random.choice(['होम डिलीवरी', 'माल उपलब्ध', 'बिना लाइसेंस'])}, संपर्क करें {phone()}",
        lambda: f"{random.choice(['देसी कट्टा', 'तमंचा', 'पिस्टल'])} बिक्री के लिए, कारतूस भी, संपर्क {phone()}",
        lambda: f"{random.choice(['फर्जी आधार', 'फर्जी मार्कशीट', 'फर्जी डिग्री'])} बिना दस्तावेज़, 2 दिन में, संपर्क {phone()}",
    ]
    return random.choice(forms)()


def illicit_benign():
    c = random.choice(CITIES)
    forms = [
        lambda: f"{c} police ne {random.randint(2, 40)} kg {random.choice(DRUG)} ke saath {random.randint(1, 5)} logon ko giraftar kiya, NDPS act mein case darj.",
        lambda: f"{c} mein {random.choice(['desi katta', 'tamancha', 'illegal arms'])} ke saath yuvak pakda gaya, police ne kartoos bhi baramad kiye.",
        lambda: f"Fake marksheet racket busted in {c}: police arrested {random.randint(2, 6)} people and seized fake degrees.",
        lambda: f"Nasha mukti abhiyan {c}: say no to drugs. De-addiction help 14446 par call karein.",
        lambda: f"Anti-narcotics awareness rally in {c} schools tomorrow. Drug free Rajasthan!",
        lambda: f"Codeine syrup and tramadol are sold only with prescription at our licensed pharmacy in {c}.",
        lambda: f"{c} medical store: home delivery of medicines with doctor's prescription, call {phone()}",
        lambda: f"Toy gun 🔫 and water pistol sale for Holi, {random.choice(['home delivery', 'ready stock', 'wholesale rate'])}. {c} Toy Mart {phone()}",
        lambda: f"Nerf guns and toy pistols for kids' birthday, {random.choice(IPRICE)}, home delivery in {c}.",
        lambda: f"HP and Canon ink cartridges {random.choice(['ready stock', 'wholesale rate', 'home delivery'])}, {c}. Call {phone()}",
        lambda: f"1 katta {random.choice(['gehun', 'chawal', 'cement', 'khad'])} {random.choice(['50 kg', '25 kg'])} {random.choice(IPRICE)}, home delivery {c}.",
        lambda: f"Fresh {random.choice(['mint 🌿', 'tulsi 🌿', 'curry leaves 🍃', 'methi 🍃'])} and organic veggies, home delivery in {c}, order now.",
        lambda: f"Maple 🍁 wood furniture sale, {random.choice(['ready stock', 'home delivery', 'all india delivery'])}. {c} Furnishers.",
        lambda: f"Snowfall in Shimla ❄️❄️ trip from {c}, 3 nights package {random.choice(IPRICE)}. DM for details.",
        lambda: f"AC and fridge ❄️ sale, home delivery and installation in {c}. Price list inbox.",
        lambda: f"Aadhaar update camp at CSC centre {c}, bring original documents. Visit the official UIDAI website.",
        lambda: f"PAN card apply online on the official website, CSC centre {c} helps with documents.",
        lambda: f"Driving licence test slots open at RTO {c}, apply online with documents.",
        lambda: f"Arms licence renewal camp at collectorate {c} on Monday, bring your old licence.",
        lambda: f"{c} shooting academy: air rifle and pistol training for national trials, admissions open.",
        lambda: f"Mushroom 🍄 farming training in {c}, home delivery of oyster mushroom, {random.choice(IPRICE)} per kg.",
        lambda: f"सावधान! फर्जी आधार और फर्जी डिग्री बनाने वाले गिरोह से बचें, शिकायत 1930 पर करें।",
        lambda: f"{c} पुलिस ने {random.randint(2, 30)} किलो गांजा जब्त किया, दो आरोपी गिरफ्तार।",
        lambda: f"नशा मुक्ति केंद्र {c}: नशा छोड़ने के लिए संपर्क करें {phone()}",
    ]
    return random.choice(forms)()


def main():
    rows = [{"text": suspicious(), "label": 1} for _ in range(330)] + [{"text": benign(), "label": 0} for _ in range(330)]
    random.shuffle(rows)
    extra = [{"text": illicit(), "label": 1} for _ in range(180)] + [{"text": illicit_benign(), "label": 0} for _ in range(180)]
    random.shuffle(extra)
    rows += extra
    out = Path(__file__).parent / "training_data.jsonl"
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} samples -> {out}")


if __name__ == "__main__":
    main()
