"""Recruiter priority: who to go after first.

Many people who sell a single account are themselves students or poor account holders who were lured in.
The people worth the most police time are the recruiters and resellers: they post in bulk, run rings of
linked posts, ask for many accounts, pay commission, and rotate contact numbers. This score (0-100) ranks
the case queue so those come first. It only applies to cases already at Medium risk or above."""
import re
from collections import Counter, defaultdict

from .config import LEVEL_RANK

PHRASES = [
    (r"\bwe\s+buy\b|\bbuying\s+(?:bank\s+)?(?:accounts?|a/?cs?|khat[ae])\b|accounts?\s+(?:wanted|required|chahiye)", "asks to buy accounts"),
    (r"\bcommission\b|कमीशन", "offers commission"),
    (r"\bper\s+(?:account|a/?c|khata|kit)\b|\bprati\s+khata\b", "pays per account"),
    (r"\bagents?\b|\bresellers?\b|\bdealers?\b", "looks for agents or resellers"),
    (r"\bbulk\b|\bthok\b|थोक", "deals in bulk"),
    (r"har\s+mahine|monthly\s+(?:income|payment|rent)|per\s+month|हर\s+महीने", "promises a monthly payout"),
    (r"account\s+holders?\s+(?:needed|required|chahiye)|need\s+(?:savings|current)?\s*account\s+holders?", "recruits account holders"),
    (r"students?\b.*\b(?:earn|kamao|income)|(?:earn|kamao|income)\b.*\bstudents?", "targets students"),
]
_RX = [(re.compile(p, re.I | re.S), why) for p, why in PHRASES]
CONTACT = ("phone", "upi", "telegram", "whatsapp")


def compute(posts) -> dict[int, tuple[float, list[str]]]:
    by_author = defaultdict(list)
    by_cluster = defaultdict(list)
    for p in posts:
        if p.author and LEVEL_RANK.get(p.risk_level, 0) >= LEVEL_RANK["High"]:
            by_author[p.author.lower()].append(p)
        if p.cluster_id is not None:
            by_cluster[p.cluster_id].append(p)
    out = {}
    for p in posts:
        if LEVEL_RANK.get(p.risk_level, 0) < LEVEL_RANK["Medium"] or p.label == "false_positive":
            out[p.id] = (0.0, [])
            continue
        score, why = 0.0, []
        groups = set((p.scores or {}).get("groups", []))
        if "payout_lure" in groups:
            score += 30
            why.append("Recruits people to rent or hand over their accounts")
        blob = (p.text or "") + "\n" + (p.ocr_text or "")
        hits = [w for rx, w in _RX if rx.search(blob)]
        if hits:
            score += min(20, 7 * len(hits))
            why.append("Wording: " + ", ".join(hits))
        mine = by_author.get((p.author or "").lower(), [])
        if len(mine) >= 2:
            score += 25 if len(mine) >= 4 else 15
            why.append(f"Same author posted {len(mine)} high-risk ads")
        members = by_cluster.get(p.cluster_id, [p]) if p.cluster_id is not None else [p]
        if len(members) >= 3:
            score += 15
            why.append(f"Part of a ring of {len(members)} linked posts")
        if len({m.platform.split(' · ')[0] for m in members}) > 1:
            score += 5
            why.append("Ring spans more than one platform")
        ids = Counter(f"{k}:{v}" for m in members for k in CONTACT for v in (m.entities or {}).get(k, []))
        if len(ids) >= 3:
            score += 10
            why.append(f"Uses {len(ids)} different contact or payment identifiers")
        if p.complaint_count:
            score += 15
            why.append("Linked to victim complaints")
        out[p.id] = (min(100.0, round(score, 1)), why)
    return out
