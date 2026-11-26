"""Hybrid, explainable risk scoring.

final = noisy-OR( rule engine , text classifier , image cues , [LLM] ) * 100
        + coordination boost (ring membership) + watchlist floor        (applied in pipeline)

Every component is stored so the UI can show *why* a post was flagged."""
import re

from .extract import LEXICON, extract_entities, find_keywords
from .imaging import image_cues
from .ml import model

GROUPS = LEXICON["groups"]
RISK_GROUPS = {"mule_kit", "card_sale", "payout_lure", "evasion", "financial_object", "sale_intent",
               "drug_term", "drug_emoji", "arms_term", "arms_emoji", "fake_doc", "illicit_sale_cue", "covert_cue"}
# illegal goods other than banking material (problem statement: drugs, arms, fake documents)
ILLICIT_TERMS = {"drug_term", "arms_term", "fake_doc"}
ILLICIT_EMOJI = {"drug_emoji", "arms_emoji"}


def term_multiplier(term: str, stats: dict) -> float:
    """Feedback-adapted weight: Laplace-smoothed precision mapped to 0.3 .. 1.5."""
    s = stats.get(term)
    if not s:
        return 1.0
    conf, fp = s
    precision = (conf + 1) / (conf + fp + 2)
    return round(0.3 + 1.2 * precision, 3)


# "I will give 10000 for ...", "5k dunga account ke liye", "paying ₹2000 per card"
PAY_OFFER = re.compile(r"\b(?:give|pay|paying|offer|offering|dunga|denge|milenge?)\b[^.\n]{0,15}?(?:₹|rs\.?|inr)?\s?\d[\d,]*\s?k?\b"
                       r"|(?:₹|rs\.?|inr)?\s?\d[\d,]*\s?k?\s+(?:dunga|denge|milenge?)\b", re.I)


def rule_engine(hits: list[dict], entities: dict, stats: dict, text_for_rules: str = "") -> tuple[float, list[dict], list[str]]:
    by_group: dict[str, set] = {}
    for h in hits:
        by_group.setdefault(h["group"], set()).add(h["term"])

    # delivery / covert-sale words describe how goods change hands: on their own they are every shop's ad
    # ("home delivery", "ready stock"), so they only count next to drugs, arms or documents, or (covert cues
    # only) next to a drug or weapon emoji code
    illicit_present = bool(ILLICIT_TERMS & set(by_group))
    gated = set()
    if not illicit_present:
        gated.add("illicit_sale_cue")
        if not ILLICIT_EMOJI & set(by_group):
            gated.add("covert_cue")
    # an emoji code (❄ 🍁 🔫) means something only next to the goods or a covert cue
    if not {"drug_term", "covert_cue"} & set(by_group):
        gated.add("drug_emoji")
    if not {"arms_term", "covert_cue"} & set(by_group):
        gated.add("arms_emoji")

    points, parts, reasons = 0.0, [], []
    for group, terms in by_group.items():
        if group in gated:
            continue
        spec = GROUPS[group]
        raw = sum(spec["weight"] * term_multiplier(t, stats) for t in terms)
        capped = max(raw, spec["cap"]) if spec["cap"] < 0 else min(raw, spec["cap"])
        points += capped
        parts.append({"name": spec["label"], "points": round(capped, 1), "terms": sorted(terms)})
        if group in ("mule_kit", "card_sale", "payout_lure", "money_lure", "drug_term", "arms_term", "fake_doc",
                     "drug_emoji", "arms_emoji"):
            ctx = " (quoted inside an awareness message)" if "awareness" in by_group else ""
            reasons.append(f"{spec['label']}{ctx}: " + ", ".join(f"“{t}”" for t in sorted(terms)[:5]))
        elif group == "awareness":
            reasons.append("Looks like awareness / legitimate context: " + ", ".join(sorted(terms)[:3]))

    awareness = "awareness" in by_group
    for combo in LEXICON["combos"]:
        if not awareness and all(g in by_group for g in combo["all"]):
            points += combo["bonus"]
            parts.append({"name": combo["label"], "points": combo["bonus"], "terms": []})
            reasons.append(combo["label"])

    strong = {"mule_kit", "card_sale", "payout_lure", "money_lure"} & set(by_group)
    # drugs / arms / fake documents: the name alone is news or chat; with sale or delivery language it is an ad.
    # An emoji code needs the delivery language itself (❄ or 🍁 on their own are everyday).
    illicit_sale = bool(illicit_present and {"illicit_sale_cue", "covert_cue", "sale_intent"} & set(by_group)) or \
        bool(ILLICIT_EMOJI & set(by_group) and "covert_cue" in by_group)
    risky_language = not awareness and bool(
        strong or illicit_sale or ({"financial_object", "sale_intent"} <= set(by_group))
        or ({"financial_object", "evasion"} <= set(by_group)))
    contact = [k for k in ("phone", "phone_like", "whatsapp", "telegram", "upi", "handle") if entities.get(k)]
    if PAY_OFFER.search(text_for_rules) and ("financial_object" in by_group or "card_sale" in by_group) and not awareness:
        points += 20
        parts.append({"name": "Offers money for a bank account or card", "points": 20, "terms": []})
        reasons.append("Offers money in exchange for a bank account or card")
    if "money_lure" in by_group and contact and not awareness:
        points += 27
        parts.append({"name": "Easy-money lure with a contact", "points": 27, "terms": entities[contact[0]][:2]})
        reasons.append("Easy-money offer with a contact: " + ", ".join(map(str, entities[contact[0]][:2])))
    ent_rules = [
        ("card_number", 22, "Card number pattern present", False),
        ("crypto_wallet", 8, "Crypto wallet address (USDT/BTC payouts)", True),
        ("upi", 8, "UPI payment ID given for payment", True),
        ("ifsc", 6, "IFSC code shared", True),
        ("telegram", 8, "Moves buyers to Telegram", True),
        ("whatsapp", 7, "Moves buyers to WhatsApp", True),
        ("handle", 3, "Contact handle given", True),
        ("phone", 6, "Phone number for contact", True),
        ("phone_like", 5, "Number given for contact (not a valid mobile format)", True),
        ("price", 7, "Price quoted per item", True),
    ]
    for kind, pts, label, needs_language in ent_rules:
        if entities.get(kind) and (risky_language or not needs_language):
            points += pts
            parts.append({"name": label, "points": pts, "terms": entities[kind][:3]})
            reasons.append(f"{label}: {', '.join(map(str, entities[kind][:3]))}")
    if any(d in ("bit.ly", "tinyurl.com", "cutt.ly", "t.ly", "rb.gy", "is.gd") for d in entities.get("domains", [])) and risky_language:
        points += 5
        parts.append({"name": "Shortened link hides destination", "points": 5, "terms": []})

    return max(0.0, min(1.0, points / 100)), parts, reasons, risky_language


# Citizen reports are often not ads at all but a victim describing a scam attempt ("he called and asked
# for my ATM card number and PIN"). These cues only apply to citizen reports.
_SECRET = r"(?:o\s?t\s?p|p\s?i\s?n|cvv|card\s*(?:no|number|details)|car\s?d\s*(?:no|number)|atm|password|upi\s*pin|" \
          r"account\s*(?:no|number|details)|net\s*banking|aadhaa?r|pan\s*card|ओटीपी|पिन|कार्ड)"
FRAUD_ATTEMPT = [
    ("Someone asked for card, PIN, OTP or account details",
     re.compile(r"\b(?:ask\w*|demand\w*|want\w*|wanted|maang\w*|requested|share|bata\w*|tell me)\b.{0,50}?" + _SECRET, re.I | re.S)),
    ("Someone asked for card, PIN, OTP or account details",
     re.compile(_SECRET + r".{0,40}?\b(?:ask\w*|maang\w*|share karo|batao|bata do|demand\w*)", re.I | re.S)),
    ("Caller or message pretending to be a bank, KYC team or official",
     re.compile(r"\b(?:call\w*|phone\w*|messag\w*|sms|whatsapp\w*|link)\b.{0,60}?\b(?:bank|kyc|rbi|sbi|hdfc|icici|axis|"
                r"customer care|executive|officer|police|cbi|customs|courier)\b", re.I | re.S)),
    ("Threat that the account or card will be blocked",
     re.compile(r"\b(?:account|card|sim|kyc)\b.{0,30}?\b(?:block\w*|suspend\w*|expire\w*|band ho|deactivat\w*)", re.I | re.S)),
    ("Asked to install a screen-sharing or remote app",
     re.compile(r"\b(?:anydesk|teamviewer|quick\s?support|screen\s?shar\w*|remote app)\b", re.I)),
    ("Victim reports losing money or being cheated",
     re.compile(r"\b(?:lost|deducted|debited|cheated|scammed|duped|thug\w*|money (?:was )?taken)\b|ठग|धोखा|पैसे कट", re.I)),
    ("Reporter says it is fraud",
     re.compile(r"\b(?:report (?:a )?fraud|fraud call|fake call|scam call|fraudster|scammer)\b", re.I)),
]


def fraud_attempt_cues(text: str) -> list[str]:
    return list(dict.fromkeys(label for label, rx in FRAUD_ATTEMPT if rx.search(text or "")))


def categorize(by_group: set, entities: dict, score: float) -> str:
    if "fraud_attempt" in by_group and score >= 30:
        return "Reported Fraud Attempt"
    if score < 30:
        return "Benign"
    if not by_group & {"mule_kit", "card_sale", "payout_lure"}:     # banking categories win when both appear
        if "arms_term" in by_group or {"arms_emoji", "covert_cue"} <= by_group:
            return "Arms Sale"
        if "drug_term" in by_group or {"drug_emoji", "covert_cue"} <= by_group:
            return "Drug Sale"
        if "fake_doc" in by_group:
            return "Fake Documents"
    if "money_lure" in by_group and not by_group & {"mule_kit", "card_sale", "payout_lure", "financial_object"}:
        return "Easy-Money Lure"
    if "card_sale" in by_group or entities.get("card_number"):
        return "Card Sale"
    if "payout_lure" in by_group:
        return "Account-Holder Recruitment"
    if by_group & {"mule_kit"}:
        return "Mule Account Sale"
    if "evasion" in by_group:
        return "KYC Fraud"
    return "Suspicious Financial Ad"


def analyze(text: str, ocr_text: str = "", stats: dict | None = None, llm: dict | None = None,
            citizen: bool = False) -> dict:
    stats = stats or {}
    text_hits = find_keywords(text)
    ocr_hits = [dict(h, source="image") for h in find_keywords(ocr_text)] if ocr_text else []
    entities = extract_entities(text + ("\n" + ocr_text if ocr_text else ""))
    spans = entities.pop("_spans")
    text_spans = [s for s in spans if s["end"] <= len(text)]

    r, parts, reasons, risky_language = rule_engine(text_hits + ocr_hits, entities, stats, text + "\n" + ocr_text)

    groups = {h["group"] for h in text_hits + ocr_hits}
    awareness = "awareness" in groups

    combined = (text + " " + ocr_text).strip()
    p = model().predict_proba(combined) if combined else 0.5
    m = max(0.0, (p - 0.5) * 2) * (0.4 if awareness else 1.0)
    # the n-gram model is a supporting signal: on its own (no risky wording or identifiers found) and
    # especially on very short texts like comments it is too easily swayed, so it counts for less
    if not risky_language:
        m *= 0.35
    m *= min(1.0, 0.35 + len(combined) / 120)
    ml_features = model().top_features(combined) if p > 0.6 else []
    if m > 0.3:
        reasons.append(f"Text classifier confidence {p:.0%} (signals: {', '.join(ml_features[:4])})")

    cues = image_cues(ocr_text) if ocr_text else []
    sale_context = bool(groups & {"mule_kit", "card_sale", "payout_lure", "evasion", "sale_intent"}) and not awareness
    i = 0.0
    if cues:
        # banking material in an image is only risky next to sale / rent language;
        # a student proudly posting a new card is not a seller
        i = min(1.0, 0.18 * len(cues)) if sale_context else min(0.12, 0.03 * len(cues))
        reasons.append(("Image shows banking material: " if sale_context else
                        "Image shows card/bank details (no sale language): ") + ", ".join(cues[:5]))
    if ocr_hits and not awareness and any(h["group"] in ("mule_kit", "card_sale", "payout_lure") for h in ocr_hits):
        i = min(1.0, i + 0.3)
        reasons.append("Sale language found inside the image (OCR)")

    l_score = 0.0
    if llm and "score" in llm:
        l_score = max(0.0, min(1.0, llm["score"] / 100))
        if llm.get("rationale"):
            reasons.append("AI analyst: " + llm["rationale"])

    noisy_or = 1 - (1 - r) * (1 - 0.75 * m) * (1 - 0.6 * i) * (1 - 0.8 * l_score)
    base = round(noisy_or * 100, 1)

    if citizen:
        cues = fraud_attempt_cues(text + "\n" + ocr_text)
        asked = ("Someone asked for card, PIN, OTP or account details" in cues
                 or "Victim reports losing money or being cheated" in cues)
        if asked or len(cues) >= 2:
            groups.add("fraud_attempt")
            # a victim was targeted: always needs an investigator, whatever the ad-scoring says
            base = max(base, 85.0 if asked and len(cues) >= 2 else 70.0)
            reasons.insert(0, "Fraud attempt reported by a citizen: " + "; ".join(cues))

    return {
        "matches": [{k: h[k] for k in ("term", "group", "start", "end", "text", "obfuscated")} | {"source": "text"} for h in text_hits]
                   + [{k: h[k] for k in ("term", "group", "start", "end", "text")} | {"source": "image"} for h in ocr_hits],
        "entities": entities,
        "entity_spans": text_spans,
        "groups": sorted(groups),
        "reasons": reasons,
        "base_score": base,
        "scores": {
            "rule": round(r * 100, 1),
            "ml": round(p * 100, 1),
            "image": round(i * 100, 1),
            "llm": round(l_score * 100, 1) if llm else None,
            "rule_parts": parts,
            "ml_features": ml_features,
            "image_cues": cues,
            "base": base,
        },
    }


def finalize(base: float, coord_boost: float, watch_hits: list[str]) -> float:
    score = min(100.0, base + coord_boost)
    if watch_hits:
        score = max(score, 88.0)
    return round(score, 1)
