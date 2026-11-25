"""Find candidate public channels for collection, score them, and write a list for a human to approve.

    python -m collect.discover_channels --out config/channels.discovered.yaml -v
    python -m collect.discover_channels --dry-run          # show the plan; no Telegram requests

Read-only: it uses the same ReadOnlyTelegramClient as the collector (join, send, forward, read-receipt
and contact requests are blocked inside the client). It searches Telegram's public directory
(contacts.SearchRequest), resolves the seed usernames, and reads the last N posts of each candidate.
It never opens links found in posts.

Nothing from the posts is kept. Each candidate gets aggregate numbers only:
  score        mean weighted count of fraud-ad cues per post (bank names, account / kit / payout / rent /
               sale / USDT / commission terms in English, Hinglish and Devanagari; awareness wording such
               as "beware" or "1930" counts against), plus contact_weight x the share of posts with a phone
               number, UPI ID or Telegram contact (only counted, never stored), plus title cues
  lang_mix     share of word tokens that are Devanagari, romanised Hindi, or English
  last_post, subscribers, kind (broadcast / megagroup), Telegram's verified and scam flags
and a label: likely_fraud (score >= likely_fraud), likely_legit (score < likely_legit, or a
Telegram-verified channel), otherwise unclear. Channels found by the legit keywords are negatives:
they are labelled likely_legit unless their score says otherwise, in which case they are unclear.

Channel titles are written with identifiers masked. Post text and contact values are never printed,
logged or written.

Output: the YAML file (same format as channels.yaml, every entry approved: false, sorted by score),
a CSV next to it for review, and a per-keyword CSV. The collector only reads entries a person has
set to approved: true whose label is likely_fraud or likely_legit.
"""
import argparse
import asyncio
import csv
import logging
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from collect.telegram_public import RateLimiter, load_config as load_channels_config, make_client, normalize_username
from common.io import load_env
from common.lang import HINGLISH_MARKERS
from pii.redact import Redactor

log = logging.getLogger("collect.discover")

# --------------------------------------------------------------------------- cues

BANKS = ["sbi", "hdfc", "icici", "axis", "kotak", "rbl", "pnb", "bob", "bank of baroda", "baroda", "canara",
         "union bank", "idfc", "indusind", "yes bank", "au bank", "au small finance", "federal bank", "bandhan",
         "idbi", "indian bank", "central bank", "uco", "paytm", "airtel payments", "fino", "jio payments",
         "equitas", "ujjivan", "dbs", "esaf", "एसबीआई", "एचडीएफसी", "आईसीआईसीआई", "एक्सिस", "कोटक", "पीएनबी",
         "बड़ौदा", "केनरा"]

CUES: dict[str, list[str]] = {
    # selling / renting accounts and kits, payout rails
    "strong": ["kit", "kits", "mule", "payout", "payin", "pay-in", "pay in", "escrow", "usdt", "on rent", "for rent",
               "kiraye", "kiraya", "kiraaye", "full kit", "net banking", "netbanking", "passbook",
               "corporate account", "current account", "merchant account", "gateway account", "fresh account",
               "old account", "account sale", "account sell", "atm kit", "sim kit", "firm account",
               "किराये", "किराए", "किराया", "करंट अकाउंट", "कॉर्पोरेट", "पासबुक", "नेट बैंकिंग", "किट", "रेंट"],
    "sale": ["sale", "sell", "selling", "seller", "buy", "available", "becho", "bechna", "bechne", "commission",
             "rent", "daily payment", "per transaction", "bulk", "बेच", "बेचें", "खरीद", "कमीशन", "उपलब्ध"],
    "bank": BANKS + ["upi", "a/c", "account", "accounts", "khata", "khaata", "atm", "debit card", "credit card",
                     "sim", "ifsc", "खाता", "खाते", "अकाउंट", "बैंक", "एटीएम", "कार्ड", "सिम"],
    "lure": ["ghar baithe", "part time", "work from home", "daily income", "task", "kamai", "kamao", "earn",
             "earning", "घर बैठे", "पार्ट टाइम", "कमाई", "कमाएं"],
    # awareness / official wording: a cyber-police or bank channel warning about mule accounts
    "awareness": ["beware", "cyber crime", "cybercrime", "1930", "awareness", "never share", "report fraud",
                  "cyber dost", "sanchar saathi", "cybercrime.gov.in", "sachet", "सावधान", "जागरूक",
                  "साइबर अपराध", "धोखाधड़ी से बचें", "ठगी से बचें"],
    # market / regulator news: legit finance channels
    "finance_news": ["nifty", "sensex", "mutual fund", "ipo", "repo rate", "interest rate", "monetary policy",
                     "circular", "press release", "निफ्टी", "सेंसेक्स", "म्यूचुअल फंड"],
}
WEIGHTS = {"strong": 3.0, "sale": 2.0, "bank": 1.0, "lure": 1.0, "awareness": -3.0, "finance_news": -1.0}


def _rx(term: str) -> re.Pattern:
    body = r"[\s\-_.]*".join(re.escape(p) for p in term.split())
    if term.isascii():
        return re.compile(r"(?<![a-z0-9])" + body + r"(?![a-z0-9])", re.I)
    return re.compile(body)


_CUE_RX = [(g, t, _rx(t)) for g, terms in CUES.items() for t in terms]


def cue_score(text: str, cap: float = 10.0) -> float:
    """Weighted count of distinct cue terms in one text, capped so one long post can't dominate."""
    if not text:
        return 0.0
    hits = {(g, t) for g, t, rx in _CUE_RX if rx.search(text)}
    # "account" inside "current account", "kit" inside "full kit": count only the longer term
    terms = {t for _, t in hits}
    hits = {(g, t) for g, t in hits if not any(t != o and t in o for o in terms)}
    s = sum(WEIGHTS[g] for g, _ in hits)
    return max(min(s, cap), -cap)


# count-only: the probe's salt is irrelevant because the hashes are never kept
_PROBE = Redactor(b"discovery-count-only-not-a-secret")
_CONTACT_TYPES = {"PHONE", "UPI", "HANDLE"}
_TG_LINK = re.compile(r"(?:t|telegram)\.me/", re.I)


def has_contact(text: str) -> bool:
    if not text:
        return False
    if _TG_LINK.search(text):
        return True
    return any(e.type in _CONTACT_TYPES for e in _PROBE.find(text))


def mask_title(title: str) -> str:
    return _PROBE.redact(title or "")[0]


_DEV_WORD = re.compile(r"[ऀ-ॿ]+")
_LAT_WORD = re.compile(r"[A-Za-z]+")


def lang_mix(texts: list[str]) -> dict:
    dev = rom = eng = 0
    for t in texts:
        dev += len(_DEV_WORD.findall(t or ""))
        for w in _LAT_WORD.findall(t or ""):
            if w.lower() in HINGLISH_MARKERS:
                rom += 1
            else:
                eng += 1
    total = dev + rom + eng
    if not total:
        return {"devanagari": 0.0, "roman_hindi": 0.0, "english": 0.0}
    return {"devanagari": round(dev / total, 3), "roman_hindi": round(rom / total, 3),
            "english": round(eng / total, 3)}


# --------------------------------------------------------------------------- candidates

@dataclass
class Candidate:
    id: int
    username: str
    title: str
    kind: str
    found_by: list = field(default_factory=list)
    role: str = "fraud"                 # which search found it first: fraud keywords, seeds, or legit
    subscribers: int | None = None
    verified: bool = False
    tg_scam_flag: bool = False
    posts_sampled: int = 0
    last_post: str = ""
    cue_score: float = 0.0
    contact_share: float = 0.0
    score: float = 0.0
    lang_mix: dict = field(default_factory=dict)
    label: str = "unclear"
    error: str = ""


def public_username(entity) -> str | None:
    if getattr(entity, "username", None):
        return entity.username
    for u in getattr(entity, "usernames", None) or []:
        if getattr(u, "active", False) and getattr(u, "username", None):
            return u.username
    return None


def channel_kind(entity) -> str | None:
    """'broadcast' or 'megagroup' for a public channel / supergroup, None for anything else."""
    from telethon.tl.types import Channel
    if not isinstance(entity, Channel) or not public_username(entity):
        return None
    if getattr(entity, "broadcast", False):
        return "broadcast"
    if getattr(entity, "megagroup", False):
        return "megagroup"
    return None


def label_for(c: Candidate, s: dict) -> str:
    if c.posts_sampled == 0:
        return "unclear"
    if c.verified and c.score < s["likely_fraud"]:
        return "likely_legit"
    if c.role == "legit":
        return "likely_legit" if c.score < s["likely_fraud"] else "unclear"
    if c.score >= s["likely_fraud"]:
        return "likely_fraud"
    if c.score < s["likely_legit"]:
        return "likely_legit"
    return "unclear"


def score_candidate(c: Candidate, texts: list[str], dates: list[datetime], s: dict) -> None:
    """Fill in the aggregate fields from the sampled posts. `texts` is dropped by the caller afterwards."""
    with_text = [t for t in texts if t and t.strip()]
    c.posts_sampled = len(texts)
    c.last_post = max(dates).date().isoformat() if dates else ""
    if with_text:
        c.cue_score = sum(cue_score(t, s["post_cap"]) for t in with_text) / len(with_text)
        c.contact_share = sum(has_contact(t) for t in with_text) / len(with_text)
    title_part = s["title_weight"] * cue_score(c.title, s["post_cap"])
    c.score = round(c.cue_score + s["contact_weight"] * c.contact_share + title_part, 3)
    c.cue_score = round(c.cue_score, 3)
    c.contact_share = round(c.contact_share, 3)
    c.lang_mix = lang_mix(with_text)
    c.label = label_for(c, s)


# --------------------------------------------------------------------------- telegram calls

class Discoverer:
    def __init__(self, client, settings: dict, limiter: RateLimiter, sleep=asyncio.sleep, max_retries: int = 3):
        self.client, self.s, self.limiter, self.sleep = client, settings, limiter, sleep
        self.max_retries = max_retries
        self.by_id: dict[int, Candidate] = {}
        self.requests = 0

    async def _call(self, fn, *args, **kwargs):
        from telethon.errors import FloodWaitError
        for attempt in range(self.max_retries + 1):
            await self.limiter.wait()
            self.requests += 1
            try:
                return await fn(*args, **kwargs)
            except FloodWaitError as e:
                if attempt == self.max_retries:
                    raise
                log.warning("FloodWait %ss; sleeping", e.seconds)
                await self.sleep(e.seconds + 1)

    def _add(self, entity, found_by: str, role: str) -> Candidate | None:
        kind = channel_kind(entity)
        if not kind:
            return None
        if entity.id in self.by_id:
            c = self.by_id[entity.id]
            if found_by not in c.found_by:
                c.found_by.append(found_by)
            return None
        c = Candidate(id=entity.id, username=public_username(entity), title=mask_title(entity.title), kind=kind,
                      found_by=[found_by], role=role, subscribers=getattr(entity, "participants_count", None),
                      verified=bool(getattr(entity, "verified", False)),
                      tg_scam_flag=bool(getattr(entity, "scam", False) or getattr(entity, "fake", False)))
        c._entity = entity
        self.by_id[entity.id] = c
        return c

    async def search(self, q: str, role: str) -> tuple[int, list[Candidate]]:
        from telethon.tl.functions.contacts import SearchRequest
        found = await self._call(self.client, SearchRequest(q=q, limit=int(self.s["search_limit"])))
        chats = list(getattr(found, "chats", []) or [])
        new = [c for c in (self._add(ch, f"keyword '{q}'", role) for ch in chats) if c]
        return len(chats), new

    async def seed(self, username: str) -> Candidate | None:
        try:
            entity = await self._call(self.client.get_entity, username)
        except Exception as e:                      # unknown / deleted / private username
            log.warning("seed %s: %s", username, type(e).__name__)
            return None
        c = self._add(entity, "seed list", "seed")
        if c is None and entity.id not in self.by_id:
            log.warning("seed %s: not a public channel or supergroup", username)
        return c

    async def inspect(self, c: Candidate) -> None:
        from telethon.tl.functions.channels import GetFullChannelRequest
        entity = c._entity
        try:
            msgs = await self._call(self.client.get_messages, entity, limit=int(self.s["posts_per_channel"]))
            msgs = [m for m in msgs if not getattr(m, "action", None)]
            texts = [getattr(m, "message", "") or "" for m in msgs]
            dates = [m.date for m in msgs if getattr(m, "date", None)]
            score_candidate(c, texts, dates, self.s)
            del texts, msgs
            if c.subscribers is None:
                full = await self._call(self.client, GetFullChannelRequest(channel=entity))
                c.subscribers = getattr(full.full_chat, "participants_count", None)
        except Exception as e:                      # private since search, banned, history hidden ...
            c.error = type(e).__name__
            c.label = "unclear"
            log.warning("%s: %s", c.username, c.error)
        log.debug("%-32s %-9s %-12s score=%5.2f contacts=%.0f%% posts=%d", c.username, c.kind, c.label, c.score,
                  100 * c.contact_share, c.posts_sampled)

    def count(self, label: str, role: str | None = None) -> int:
        return sum(c.label == label and (role is None or c.role == role) for c in self.by_id.values())


# --------------------------------------------------------------------------- config / output

def load_discovery_config(keywords_path, seeds_path) -> dict:
    kw = yaml.safe_load(Path(keywords_path).read_text(encoding="utf-8")) or {}
    seeds = (yaml.safe_load(Path(seeds_path).read_text(encoding="utf-8")) or {}).get("seeds", []) \
        if seeds_path and Path(seeds_path).exists() else []
    scoring = {"posts_per_channel": 30, "contact_weight": 4.0, "title_weight": 0.5, "post_cap": 10.0,
               "likely_fraud": 5.0, "likely_legit": 2.0, **(kw.get("scoring") or {})}
    if scoring["likely_legit"] > scoring["likely_fraud"]:
        raise ValueError("scoring.likely_legit must not be above scoring.likely_fraud")

    def flat(section):
        out = []
        for group, terms in (kw.get(section) or {}).items():
            out += [(group, t.strip()) for t in terms or [] if t and t.strip()]
        return out
    return {"fraud": flat("fraud"), "legit": flat("legit"), "seeds": [normalize_username(s) for s in seeds],
            "settings": {**scoring, "search_limit": int(kw.get("search_limit", 100))}}


def _entry(c: Candidate, today: str) -> dict:
    first = c.found_by[0]
    return {"username": c.username, "title": c.title, "approved": False, "label": c.label, "score": c.score,
            "subscribers": c.subscribers, "last_post": c.last_post or None, "lang_mix": c.lang_mix,
            "kind": c.kind, "verified": c.verified, "tg_scam_flag": c.tg_scam_flag,
            "contact_share": c.contact_share, "posts_sampled": c.posts_sampled,
            "found_by": c.found_by, "reason": f"auto-discovered {today} by {first}",
            **({"error": c.error} if c.error else {})}


def write_outputs(out: Path, cands: list[Candidate], keyword_rows: list[dict], settings: dict,
                  collector_settings: dict) -> None:
    today = date.today().isoformat()
    cands = sorted(cands, key=lambda c: (-c.score, c.username.lower()))
    doc = {"generated": today,
           "note": "Candidates for human review. Set approved: true only after checking a channel by hand. "
                   "The collector reads only approved likely_fraud / likely_legit broadcast channels.",
           "scoring": {k: settings[k] for k in ("posts_per_channel", "contact_weight", "title_weight",
                                                "likely_fraud", "likely_legit")},
           "channels": [_entry(c, today) for c in cands],
           "settings": collector_settings}
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    tmp.replace(out)

    cols = ["username", "title", "kind", "label", "score", "cue_score", "contact_share", "subscribers", "last_post",
            "posts_sampled", "devanagari", "roman_hindi", "english", "verified", "tg_scam_flag", "role", "found_by",
            "error", "approved"]
    with open(out.with_suffix(".csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for c in cands:
            w.writerow({"username": c.username, "title": c.title, "kind": c.kind, "label": c.label, "score": c.score,
                        "cue_score": c.cue_score, "contact_share": c.contact_share, "subscribers": c.subscribers,
                        "last_post": c.last_post, "posts_sampled": c.posts_sampled, **c.lang_mix,
                        "verified": c.verified, "tg_scam_flag": c.tg_scam_flag, "role": c.role,
                        "found_by": "; ".join(c.found_by), "error": c.error, "approved": False})
    with open(out.with_name(out.stem + ".keywords.csv"), "w", newline="", encoding="utf-8") as f:
        cols = ["role", "group", "keyword", "results", "new_public", "likely_fraud", "unclear", "likely_legit"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(keyword_rows)


# --------------------------------------------------------------------------- run

async def discover(client, cfg: dict, out: Path, target_fraud: int = 100, legit_target: int = 20,
                   rpm: float = 20, collector_settings: dict | None = None, sleep=asyncio.sleep) -> dict:
    s = cfg["settings"]
    d = Discoverer(client, s, RateLimiter(rpm, sleep=sleep), sleep=sleep)
    rows: list[dict] = []
    collector_settings = collector_settings or {}

    def row(role, group, kw, n_results, new):
        labels = Counter(c.label for c in new)
        rows.append({"role": role, "group": group, "keyword": kw, "results": n_results, "new_public": len(new),
                     **{k: labels.get(k, 0) for k in ("likely_fraud", "unclear", "likely_legit")}})
        write_outputs(out, list(d.by_id.values()), rows, s, collector_settings)

    seeds = [c for c in [await d.seed(u) for u in cfg["seeds"]] if c]
    for c in seeds:
        await d.inspect(c)
    row("seed", "seeds", "(seed list)", len(cfg["seeds"]), seeds)

    stopped = False
    for group, kw in cfg["fraud"]:
        if d.count("likely_fraud") >= target_fraud:
            stopped = True
            log.info("reached %d likely_fraud candidates; stopping fraud keywords", target_fraud)
            break
        n, new = await d.search(kw, "fraud")
        for c in new:
            await d.inspect(c)
        log.info("[%s] %-32s results=%3d new=%3d  -> fraud %d / unclear %d / legit %d", group, kw, n, len(new),
                 *(sum(c.label == k for c in new) for k in ("likely_fraud", "unclear", "likely_legit")))
        row("fraud", group, kw, n, new)

    for group, kw in cfg["legit"]:
        if d.count("likely_legit", "legit") >= legit_target:
            break
        n, new = await d.search(kw, "legit")
        for c in new:
            await d.inspect(c)
        log.info("[legit] %-30s results=%3d new=%3d  -> legit %d / unclear %d", kw, n, len(new),
                 sum(c.label == "likely_legit" for c in new), sum(c.label == "unclear" for c in new))
        row("legit", group, kw, n, new)

    write_outputs(out, list(d.by_id.values()), rows, s, collector_settings)
    return {"labels": Counter(c.label for c in d.by_id.values()), "keywords": rows, "requests": d.requests,
            "stopped_at_target": stopped, "candidates": len(d.by_id)}


def print_report(result: dict, out: Path, stream=sys.stdout) -> None:
    p = lambda *a: print(*a, file=stream)  # noqa: E731
    p(f"\n{result['candidates']} candidates, {result['requests']} Telegram requests"
      + (" (stopped: likely_fraud target reached)" if result["stopped_at_target"] else " (keywords exhausted)"))
    for k in ("likely_fraud", "unclear", "likely_legit"):
        p(f"  {k:13s} {result['labels'].get(k, 0)}")
    p(f"\n{'role':6s} {'keyword':34s} {'results':>7s} {'new':>4s} {'fraud':>5s} {'uncl':>5s} {'legit':>5s}")
    for r in result["keywords"]:
        p(f"{r['role']:6s} {r['keyword'][:34]:34s} {r['results']:7d} {r['new_public']:4d} {r['likely_fraud']:5d} "
          f"{r['unclear']:5d} {r['likely_legit']:5d}")
    p(f"\n-> {out}\n-> {out.with_suffix('.csv')}\n-> {out.with_name(out.stem + '.keywords.csv')}")


def dry_run(cfg: dict, target_fraud: int, legit_target: int, rpm: float, stream=sys.stdout) -> None:
    s = cfg["settings"]
    p = lambda *a: print(*a, file=stream)  # noqa: E731
    p("dry run: no Telegram requests are made, nothing is written")
    p(f"  seeds: {len(cfg['seeds'])}  fraud keywords: {len(cfg['fraud'])}  legit keywords: {len(cfg['legit'])}")
    for g, n in Counter(g for g, _ in cfg["fraud"]).items():
        p(f"    {g}: {n}")
    p(f"  per keyword: 1 search (limit {s['search_limit']}), then per new candidate 1 history read of "
      f"{s['posts_per_channel']} posts (+1 if the subscriber count is missing)")
    p(f"  stop: {target_fraud} likely_fraud candidates or keywords exhausted; then up to {legit_target} legit negatives")
    p(f"  labels: likely_fraud if score >= {s['likely_fraud']}, likely_legit if < {s['likely_legit']}")
    p(f"  rate: {rpm} requests/min -> e.g. 500 candidates ~ {round((len(cfg['fraud']) + 500 * 1.5) / rpm)} min")


async def _connect(session: str, api_id: int, api_hash: str):
    client = make_client(session, api_id, api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        if sys.stdin.isatty():
            await client.start()                    # asks for the phone number and login code
        else:
            await client.disconnect()
            raise SystemExit("Telegram session is not logged in. Run this once in a terminal to log in:\n"
                             "  cd research && .venv/bin/python -m collect.discover_channels --login")
    return client


async def run(args) -> None:
    cfg = load_discovery_config(args.keywords, args.seeds)
    collector_settings = load_channels_config(args.channels_config)["settings"] \
        if Path(args.channels_config).exists() else {}
    out = Path(args.out)
    if args.dry_run:
        dry_run(cfg, args.target_fraud, args.legit_target, args.rpm)
        return
    load_env()
    api_id, api_hash = os.environ.get("TELEGRAM_API_ID"), os.environ.get("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        raise SystemExit("set TELEGRAM_API_ID and TELEGRAM_API_HASH in research/.env")
    session = os.environ.get("TELEGRAM_SESSION", "store/telegram_research.session")
    Path(session).parent.mkdir(parents=True, exist_ok=True)
    client = await _connect(session, int(api_id), api_hash)
    try:
        if args.login:
            me = await client.get_me()
            print(f"logged in (user id {me.id}); session saved to {session}")
            return
        result = await discover(client, cfg, out, args.target_fraud, args.legit_target, args.rpm, collector_settings)
    finally:
        await client.disconnect()
    print_report(result, out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Discover candidate public channels (read-only)")
    ap.add_argument("--out", default="config/channels.discovered.yaml")
    ap.add_argument("--keywords", default="config/discovery_keywords.yaml")
    ap.add_argument("--seeds", default="config/discovery_seeds.yaml")
    ap.add_argument("--channels-config", default="config/channels.yaml", help="collector settings copied into --out")
    ap.add_argument("--target-fraud", type=int, default=100, help="stop fraud keywords once this many likely_fraud")
    ap.add_argument("--legit-target", type=int, default=20)
    ap.add_argument("--rpm", type=float, default=20, help="Telegram requests per minute")
    ap.add_argument("--dry-run", action="store_true", help="print the plan without contacting Telegram")
    ap.add_argument("--login", action="store_true", help="log the research account in (interactive) and exit")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    if not 0 < args.rpm <= 20:
        raise SystemExit("--rpm must be between 0 and 20")
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("telethon").setLevel(logging.WARNING)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
