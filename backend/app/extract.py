"""Indicator extraction: keywords (with character spans), phone numbers, UPI IDs, URLs,
Telegram / WhatsApp handles, IFSC codes, card numbers, crypto wallets and prices."""
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

LEXICON = json.loads((Path(__file__).parent / "lexicon.json").read_text(encoding="utf-8"))

# --------------------------------------------------------------------------- keywords

def _term_regex(term: str) -> re.Pattern:
    """ASCII terms: word-boundary aware, flexible whitespace/punctuation between words.
    Non-ASCII (Devanagari) terms: plain substring with flexible spaces."""
    parts = [re.escape(p) for p in term.split()]
    body = r"[\s\-_.,:|*]*".join(parts) if len(parts) > 1 else parts[0]
    if term.isascii():
        return re.compile(r"(?<![a-z0-9])" + body + r"(?![a-z0-9])", re.IGNORECASE)
    return re.compile(body)


_COMPILED = {
    g: [(t, _term_regex(t)) for t in spec["terms"]]
    for g, spec in LEXICON["groups"].items()
}

# common obfuscations used to dodge filters: acc0unt, a.t.m, k!t
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "@": "a", "$": "s", "!": "i"})


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    # strip emoji / symbols but keep Devanagari & basic punctuation
    return "".join(ch for ch in text if not unicodedata.category(ch).startswith("S") or ch in "₹+/@#").strip()


def deobfuscate(text: str) -> str:
    """Second pass text where leetspeak inside alphabetic words is undone (a.t.m -> atm)."""
    def fix(word: re.Match) -> str:
        w = word.group(0)
        if any(c.isalpha() for c in w) and any(c in "0134$!" for c in w):
            return w.translate(_LEET)
        return w
    # a.t.m -> "atm  " (padded so character offsets stay aligned with the original text)
    t = re.sub(r"\b(?:[a-zA-Z]\.){2,}[a-zA-Z]?\b",
               lambda m: m.group(0).replace(".", "").ljust(len(m.group(0))), text)
    return re.sub(r"[A-Za-z0-9$!]+", fix, t)


def find_keywords(text: str) -> list[dict]:
    """Return keyword hits: {term, group, start, end}. Spans refer to `text`."""
    hits, seen = [], set()
    variants = [text]
    deob = deobfuscate(text)
    if deob != text and len(deob) == len(text):
        variants.append(deob)          # same length -> spans still valid
    for variant in variants:
        for group, terms in _COMPILED.items():
            for term, rx in terms:
                for m in rx.finditer(variant):
                    key = (group, term, m.start())
                    if key in seen:
                        continue
                    seen.add(key)
                    hits.append({"term": term, "group": group, "start": m.start(), "end": m.end(),
                                 "text": text[m.start():m.end()],
                                 "obfuscated": variant is not text})
    hits.sort(key=lambda h: (h["start"], -(h["end"] - h["start"])))
    return hits


# --------------------------------------------------------------------------- entities

RX = {
    "telegram": re.compile(r"(?:https?://)?(?:t|telegram)\.me/(?:joinchat/|\+)?([A-Za-z0-9_+\-]{4,64})", re.I),
    "whatsapp": re.compile(r"(?:https?://)?(?:wa\.me/(\+?\d{10,13})|chat\.whatsapp\.com/([A-Za-z0-9]{10,40})|api\.whatsapp\.com/send\?phone=(\d{10,13}))", re.I),
    "url": re.compile(r"\b(?:https?://|www\.)[^\s<>\"')\]]+|\b(?:bit\.ly|tinyurl\.com|cutt\.ly|t\.ly|rb\.gy|is\.gd)/[A-Za-z0-9_\-]+", re.I),
    "email": re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+\.[A-Za-z0-9.\-]{2,}\b"),
    "upi": re.compile(r"(?<![\w.\-@])([A-Za-z0-9][A-Za-z0-9.\-_]{1,60}@[A-Za-z]{2,15})(?![\w.@])"),
    "handle": re.compile(r"(?<![\w@./])@([A-Za-z][A-Za-z0-9_]{4,31})\b"),
    # Indian mobile: 10 digits starting 6-9, any single space/dot/dash grouping (98290 41736, 8875 93 6612)
    "phone": re.compile(r"(?<![\d])(?:\+?91[\s\-.]?|0)?[6-9](?:[\s\-.]?\d){9}(?![\d])"),
    "ifsc": re.compile(r"\b([A-Z]{4}0[A-Z0-9]{6})\b"),
    "card_number": re.compile(r"(?<!\d)((?:\d{4}[\s\-]?){3}\d{4}|(?:\d{4}[\s\-]?){2}[Xx*]{4}[\s\-]?\d{4}|(?:[Xx*]{4}[\s\-]?){3}\d{4})(?!\d)"),
    # a bank account number given with a label (a/c, account no, khata sankhya ...); bare digit runs are too ambiguous
    "bank_account": re.compile(r"(?:\ba/?c|\bacc(?:ount|t)?|\bkhata|खाता)\s*(?:no\.?|number|num|sankhya|संख्या|#)?\s*[:.\-#]?\s*(\d(?:[\s\-]?\d){8,17})(?!\d)", re.I),
    "crypto_wallet": re.compile(r"\b(T[1-9A-HJ-NP-Za-km-z]{33}|0x[a-fA-F0-9]{40}|bc1[a-z0-9]{25,59})\b"),
    # a number offered for contact that isn't a valid Indian mobile (typo or deliberately broken)
    "phone_like": re.compile(r"(?:contact|call|whatsapp|wa|msg|message|dm|ping|sampark|संपर्क)\D{0,8}?(\+?\d[\d\s-]{6,14}\d)", re.I),
    "price": re.compile(r"(?:₹|rs\.?|inr)\s?(\d[\d,]*(?:\.\d+)?\s?k?)|(\d[\d,]*\s?k?)\s?(?:/-|rs\b|rupees|₹)", re.I),
}

# Payment-app handles that look like emails are UPI IDs; common UPI PSP suffixes
UPI_SUFFIXES = {
    "ybl", "ibl", "axl", "okaxis", "okhdfcbank", "okicici", "oksbi", "paytm", "apl", "upi", "ptyes",
    "ptsbi", "pthdfc", "ptaxis", "axisbank", "icici", "sbi", "hdfcbank", "kotak", "fbl", "yesbank",
    "jupiteraxis", "slc", "freecharge", "airtel", "idfcbank", "indus", "pnb", "boi", "cnrb", "barodampay",
    "unionbank", "waaxis", "wahdfcbank", "waicici", "wasbi", "abfspay", "jio", "naviaxis", "superyes",
}
BENIGN_DOMAINS = {"rbi.org.in", "cybercrime.gov.in", "sachet.rbi.org.in", "npci.org.in", "gov.in"}


def _luhn_ok(num: str) -> bool:
    digits = [int(c) for c in num if c.isdigit()]
    if len(digits) != 16:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return total % 10 == 0


def _norm_phone(p: str) -> str:
    d = re.sub(r"\D", "", p)
    return "+91" + d[-10:]


def extract_entities(text: str) -> dict:
    out: dict[str, list] = {k: [] for k in
                            ("phone", "upi", "telegram", "whatsapp", "url", "email", "ifsc", "bank_account",
                             "card_number", "crypto_wallet", "price", "handle", "phone_like")}
    spans: list[dict] = []

    def add(kind, value, m, group=0):
        if value and value not in out[kind]:
            out[kind].append(value)
        spans.append({"kind": kind, "value": value, "start": m.start(group), "end": m.end(group)})

    consumed = []   # spans already claimed (avoid phone inside wa.me link double counting as url)

    for m in RX["telegram"].finditer(text):
        add("telegram", "t.me/" + m.group(1).lower(), m)
        consumed.append((m.start(), m.end()))
    for m in RX["whatsapp"].finditer(text):
        num = m.group(1) or m.group(3)
        if num:
            add("whatsapp", _norm_phone(num), m)
            if _norm_phone(num) not in out["phone"]:
                out["phone"].append(_norm_phone(num))
        else:
            add("whatsapp", "chat.whatsapp.com/" + m.group(2), m)
        consumed.append((m.start(), m.end()))

    def free(m):
        return not any(a <= m.start() < b for a, b in consumed)

    for m in RX["email"].finditer(text):
        if free(m):
            add("email", m.group(0).lower(), m)
            consumed.append((m.start(), m.end()))
    for m in RX["url"].finditer(text):
        if free(m):
            url = m.group(0).rstrip(".,;")
            add("url", url, m)
            consumed.append((m.start(), m.end()))
    for m in RX["upi"].finditer(text):
        if free(m):
            vpa = m.group(1)
            suffix = vpa.split("@")[1].lower()
            if suffix in UPI_SUFFIXES or re.search(r"upi|pay|bank", suffix):
                add("upi", vpa.lower(), m, 1)
                consumed.append((m.start(), m.end()))
    for m in RX["handle"].finditer(text):
        if free(m):
            add("handle", "@" + m.group(1).lower(), m)
    for m in RX["card_number"].finditer(text):
        if free(m):
            raw = re.sub(r"[\s\-]", "", m.group(1))
            masked = raw[:4] + "********" + raw[-4:] if raw[:4].isdigit() else "************" + raw[-4:]
            if not raw.isdigit() or _luhn_ok(raw) or True:   # keep even non-Luhn: often fake samples
                add("card_number", masked, m, 1)
                consumed.append((m.start(), m.end()))
    for m in RX["bank_account"].finditer(text):
        digits = re.sub(r"\D", "", m.group(1))
        if free(m) and not (len(digits) == 10 and digits[0] in "6789"):
            add("bank_account", digits, m, 1)
            consumed.append((m.start(1), m.end(1)))
    for m in RX["phone"].finditer(text):
        if free(m):
            add("phone", _norm_phone(m.group(0)), m)
    for m in RX["phone_like"].finditer(text):
        digits = re.sub(r"\D", "", m.group(1))
        if free(m) and "+91" + digits[-10:] not in out["phone"] and 8 <= len(digits) <= 13:
            add("phone_like", digits, m, 1)
    for m in RX["ifsc"].finditer(text):
        add("ifsc", m.group(1), m, 1)
    for m in RX["crypto_wallet"].finditer(text):
        add("crypto_wallet", m.group(1), m, 1)
    for m in RX["price"].finditer(text):
        add("price", (m.group(1) or m.group(2) or "").strip(), m)

    out["domains"] = sorted({_domain(u) for u in out["url"] if _domain(u)})
    out = {k: v for k, v in out.items() if v}
    out["_spans"] = spans
    return out


def _domain(url: str) -> str:
    if not url.startswith("http"):
        url = "http://" + url
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return ""
    return host.lower().removeprefix("www.")


def detect_language(text: str) -> str:
    dev = sum(1 for c in text if "ऀ" <= c <= "ॿ")
    letters = sum(1 for c in text if c.isalpha()) or 1
    if dev / letters > 0.4:
        return "hi"
    hinglish = re.findall(r"\b(hai|kar|karo|ke|ki|ka|pe|par|milega|chahiye|bhai|wala|kiraye|khata|paisa|kamao|apna|sirf|turant)\b",
                          text, re.I)
    if dev or len(hinglish) >= 2:
        return "hinglish"
    return "en"
