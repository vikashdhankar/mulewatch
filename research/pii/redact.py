"""Find and mask personal identifiers in posts, keeping keyed hashes so they can still be linked.

    python -m pii.redact store/raw/telegram.jsonl --out store/redacted/posts.jsonl

Masked (placeholder in the text -> type in `entities`):
    [PHONE]    Indian mobiles in any grouping, +91/0 prefixes, Devanagari digits, wa.me links, other +CC numbers
    [UPI]      UPI IDs  name@bank, name(at)bank
    [ACCOUNT]  bank account numbers: labelled (a/c, khata, खाता) or any bare run of 9-18 digits
    [CARD]     13-19 digit card numbers (grouped 4-4-4-4 or Luhn-valid) and masked forms (XXXX XXXX XXXX 1234)
    [ID]       Aadhaar (12 digits after "aadhaar"/"आधार") and PAN
    [EMAIL]    e-mail addresses
    [URL]      links and bare domains (short links included)
    [HANDLE]   @usernames and t.me/<username> links (the same seller written either way links up)

Not masked: IFSC codes (they name a bank branch, not a person), prices, the payment app of a UPI ID
(kept as `meta.psp`), and the domain of a link or e-mail (kept as `meta.domain`).

Each entity gets hash = HMAC-SHA256(RESEARCH_HASH_SALT, "<TYPE>:<normalised value>")[:16]. The salt is a
secret kept out of any released data; without it the hashes cannot be reversed by trying all phone numbers.
Normalising first means "+91 92000-41736", "092000 41736" and "wa.me/919200041736" get the same hash.
"""
import argparse
import hashlib
import hmac
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field

from common.io import iter_jsonl, load_env, write_jsonl
from common.lang import detect_language

REDACTION_VERSION = 1

# Devanagari, Arabic-Indic and full-width digits -> ASCII, one character for one (offsets stay valid)
_DIGITS = str.maketrans({**{chr(0x0966 + i): str(i) for i in range(10)},
                         **{chr(0x06F0 + i): str(i) for i in range(10)},
                         **{chr(0x0660 + i): str(i) for i in range(10)},
                         **{chr(0xFF10 + i): str(i) for i in range(10)}})

_TLDS = ("com|in|net|org|io|me|ly|co|xyz|link|app|site|online|info|gy|gd|cc|to|top|club|shop|store|live|"
         "biz|us|uk|pro|tech|click|page|ws|su|ru|vip|win|fun|space")
_SEP = r"[ \-.]"          # one separator between digit groups (no newlines)

RX = {
    "whatsapp": re.compile(r"(?:https?://)?(?:www\.)?(?:wa\.me/|api\.whatsapp\.com/send/?\?phone=)\+?(\d{10,13})\S*", re.I),
    "tme": re.compile(r"(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(?:s/)?(?!joinchat\b)([A-Za-z][A-Za-z0-9_]{3,31})(?:/\d+)?(?![\w/+])", re.I),
    "email": re.compile(r"(?<![\w.+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}(?![\w@])"),
    "url": re.compile(r"(?:\bhttps?://|\bwww\.)[^\s<>\"'\]\[(){}]+"
                      rf"|(?<![\w@.\-])(?:[a-z0-9\-]+\.)+(?:{_TLDS})(?:/[^\s<>\"']*)?(?![\w\-])", re.I),
    "upi": re.compile(r"(?<![\w.\-@])([A-Za-z0-9][A-Za-z0-9._\-]{1,63})(?:@|\s?\(at\)\s?|\s?\[at\]\s?)([A-Za-z][A-Za-z0-9]{1,20})(?![\w@]|\.[A-Za-z])", re.I),
    "handle": re.compile(r"(?<![\w@.])@([A-Za-z][A-Za-z0-9_]{3,31})(?!\w)"),
    "card_masked": re.compile(rf"(?<![\dXx*])(?:(?:\d{{4}}|[Xx*]{{4}}){_SEP}?){{3}}\d{{4}}(?![\dXx*])"),
    "card": re.compile(r"(?<!\d)\d(?:[ \-]?\d){12,18}(?!\d)"),
    "pan": re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    "phone_in": re.compile(rf"(?<![\d+])(?:(?:\+|00)?91{_SEP}?|0)?[6-9](?:{_SEP}?\d){{9}}(?!\d)"),
    "phone_intl": re.compile(rf"(?<![\d\w])(?:\+|00)(?!91)[1-9]\d{{0,2}}(?:{_SEP}?\d){{7,12}}(?!\d)"),
    "aadhaar": re.compile(r"(?:aadhaa?r|aadhar|adhar|आधार|uid)\D{0,15}?([2-9]\d{3}[ \-]?\d{4}[ \-]?\d{4})(?!\d)", re.I),
    "account_labelled": re.compile(r"(?:\ba/?c\b|\bacc(?:ount|t)?\b|\bkhaa?ta\b|खाता)\s*(?:no\.?|number|num|sankhya|संख्या|#)?"
                                   r"\s*[:.\-#]?\s*(\d(?:[ \-]?\d){8,17})(?!\d)", re.I),
    "account": re.compile(r"(?<!\d)\d(?:[ \-]?\d){8,17}(?!\d)"),
}

PLACEHOLDER = {t: f"[{t}]" for t in ("PHONE", "UPI", "ACCOUNT", "CARD", "ID", "EMAIL", "URL", "HANDLE")}


@dataclass
class Entity:
    type: str
    start: int
    end: int
    value: str                       # normalised value: used for the hash, never written out
    meta: dict = field(default_factory=dict)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _luhn(num: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(num)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _norm_phone(raw: str) -> str:
    d = _digits(raw)
    if d.startswith("00"):
        d = d[2:]
    if len(d) >= 10 and d[-10] in "6789" and (len(d) == 10 or d[:-10] in ("91", "0", "091")):
        return "+91" + d[-10:]
    return "+" + d


def _norm_url(raw: str) -> tuple[str, str]:
    u = raw.rstrip(".,;:!?)]}'\"")
    u = re.sub(r"^https?://", "", u, flags=re.I)
    u = re.sub(r"^www\.", "", u, flags=re.I)
    host, _, rest = u.partition("/")
    host = host.lower()
    rest = rest.rstrip("/")
    return (host + ("/" + rest if rest else "")), host


class Redactor:
    def __init__(self, salt):
        if isinstance(salt, str):
            salt = salt.encode()
        if not salt or len(salt) < 16:
            raise ValueError("hash salt must be at least 16 bytes (set RESEARCH_HASH_SALT)")
        self._salt = salt

    def hash(self, etype: str, value: str) -> str:
        return hmac.new(self._salt, f"{etype}:{value}".encode(), hashlib.sha256).hexdigest()[:16]

    # ------------------------------------------------------------------ detection

    def find(self, text: str) -> list[Entity]:
        if not text:
            return []
        t = text.translate(_DIGITS)             # same length as text
        found: list[Entity] = []

        def free(a, b):
            return all(b <= e.start or a >= e.end for e in found)

        def add(etype, a, b, value, **meta):
            if a < b and free(a, b):
                found.append(Entity(etype, a, b, value, meta))
                return True
            return False

        for m in RX["whatsapp"].finditer(t):
            add("PHONE", m.start(), m.end(), _norm_phone(m.group(1)), via="whatsapp_link")
        for m in RX["tme"].finditer(t):
            add("HANDLE", m.start(), m.end(), m.group(1).lower(), via="t.me")
        for m in RX["email"].finditer(t):
            add("EMAIL", m.start(), m.end(), m.group(0).lower(), domain=m.group(0).split("@")[1].lower())
        for m in RX["url"].finditer(t):
            raw = m.group(0)
            trimmed = raw.rstrip(".,;:!?)]}'\"")
            if re.fullmatch(r"[\d.]+", trimmed):          # "1.5" or a version number, not a domain
                continue
            norm, host = _norm_url(trimmed)
            add("URL", m.start(), m.start() + len(trimmed), norm, domain=host)
        for m in RX["upi"].finditer(t):
            local, psp = m.group(1), m.group(2)
            if local.isdigit() and len(local) < 6:          # "2@rs50" style noise, not a VPA
                continue
            add("UPI", m.start(), m.end(), f"{local.lower()}@{psp.lower()}", psp=psp.lower())
        for m in RX["handle"].finditer(t):
            add("HANDLE", m.start(), m.end(), m.group(1).lower(), via="@")
        for m in RX["card_masked"].finditer(t):
            raw = m.group(0)
            norm = re.sub(rf"{_SEP}", "", raw).lower().replace("*", "x")
            if "x" in norm:
                add("CARD", m.start(), m.end(), norm, partial=True)
            else:
                add("CARD", m.start(), m.end(), norm)          # grouped 4-4-4-4: a card even if not Luhn-valid
        for m in RX["card"].finditer(t):
            d = _digits(m.group(0))
            if 13 <= len(d) <= 19 and _luhn(d) and not (len(d) == 13 and d[0] in "6789"):
                add("CARD", m.start(), m.end(), d)
        for m in RX["pan"].finditer(t):
            add("ID", m.start(), m.end(), m.group(0).upper(), kind="pan")
        for m in RX["aadhaar"].finditer(t):
            add("ID", m.start(1), m.end(1), _digits(m.group(1)), kind="aadhaar")
        for m in RX["phone_in"].finditer(t):
            add("PHONE", m.start(), m.end(), _norm_phone(m.group(0)))
        for m in RX["phone_intl"].finditer(t):
            add("PHONE", m.start(), m.end(), _norm_phone(m.group(0)))
        for m in RX["account_labelled"].finditer(t):
            if re.fullmatch(r"\d{1,6}-\d{1,6}", m.group(1)):      # "account 15000-20000": a price range
                continue
            add("ACCOUNT", m.start(1), m.end(1), _digits(m.group(1)), labelled=True)
        for m in RX["account"].finditer(t):
            d = _digits(m.group(0))
            groups = re.split(r"[ \-]", m.group(0))
            if len(groups) == 2 and all(len(g) <= 6 for g in groups):     # "15000-20000": a price range
                continue
            if 9 <= len(d) <= 18:
                add("ACCOUNT", m.start(), m.end(), d)

        found.sort(key=lambda e: e.start)
        return found

    # ------------------------------------------------------------------ masking

    def redact(self, text: str, field_name: str = "text") -> tuple[str, list[dict]]:
        """Return (masked text, entity records). Records carry the span of the placeholder in the
        masked text, the keyed hash and the non-identifying metadata; never the value itself."""
        ents = self.find(text)
        out, records, pos = [], [], 0
        length = 0
        for e in ents:
            chunk = text[pos:e.start]
            out.append(chunk)
            length += len(chunk)
            ph = PLACEHOLDER[e.type]
            records.append({"type": e.type, "hash": self.hash(e.type, e.value), "field": field_name,
                            "start": length, "end": length + len(ph), **({"meta": e.meta} if e.meta else {})})
            out.append(ph)
            length += len(ph)
            pos = e.end
        out.append(text[pos:])
        return "".join(out), records

    def redact_post(self, post: dict, hash_channel: bool = False) -> dict:
        text, ents = self.redact(post.get("text") or "", "text")
        ocr, ocr_ents = self.redact(post.get("ocr_text") or "", "ocr_text")
        channel = post.get("channel", "")
        post_id = post.get("post_id", "")
        if hash_channel and channel:
            hc = "ch_" + self.hash("CHANNEL", channel.lower())
            post_id = post_id.replace(f":{channel.lower()}:", f":{hc}:")
            channel = hc
        out = {k: post[k] for k in ("date", "media_type", "views", "forwards", "source") if k in post}
        out.update({"post_id": post_id, "channel": channel, "text": text, "ocr_text": ocr,
                    "lang": detect_language(text + " " + ocr), "entities": ents + ocr_ents,
                    "redaction_version": REDACTION_VERSION})
        return out


def residual_pii(text: str) -> list[str]:
    """Identifiers still present in already-redacted text (should be empty). Placeholders are ignored."""
    stripped = re.sub(r"\[(?:%s)\]" % "|".join(PLACEHOLDER), " ", text or "")
    probe = Redactor(b"residual-check-salt-not-secret")
    return [stripped[e.start:e.end] for e in probe.find(stripped)]


def get_salt() -> str:
    load_env()
    salt = os.environ.get("RESEARCH_HASH_SALT", "")
    if len(salt) < 16:
        raise SystemExit("set RESEARCH_HASH_SALT (32+ random hex chars) in research/.env; see .env.example")
    return salt


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mask PII in collected posts, keeping keyed hashes")
    ap.add_argument("inputs", nargs="+", help="raw JSONL files from the collector")
    ap.add_argument("--out", default="store/redacted/posts.jsonl")
    ap.add_argument("--hash-channels", action="store_true",
                    help="also replace channel names with keyed hashes (use for any data that leaves the team)")
    args = ap.parse_args(argv)

    red = Redactor(get_salt())
    seen, counts, rows, leaks = set(), Counter(), [], 0
    for path in args.inputs:
        for post in iter_jsonl(path):
            if post.get("post_id") in seen:            # reruns of the collector may append duplicates
                continue
            seen.add(post.get("post_id"))
            r = red.redact_post(post, hash_channel=args.hash_channels)
            counts.update(e["type"] for e in r["entities"])
            leaks += bool(residual_pii(r["text"]) or residual_pii(r["ocr_text"]))
            rows.append(r)
    n = write_jsonl(args.out, rows, private=True)
    print(f"{n} posts -> {args.out}", file=sys.stderr)
    for k, v in counts.most_common():
        print(f"  {k:8s} {v}", file=sys.stderr)
    if leaks:
        print(f"WARNING: {leaks} posts still look like they contain identifiers; check before sharing",
              file=sys.stderr)


if __name__ == "__main__":
    main()
