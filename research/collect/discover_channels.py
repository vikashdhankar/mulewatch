"""Find candidate public channels for collection, score them, and write a list for a human to approve.

    python -m collect.discover_channels --out config/channels.discovered.yaml -v
    python -m collect.discover_channels --dry-run          # show the plan; no Telegram requests

Pace: 6 requests/min and at most 300 requests per calendar day by default. Progress is saved after every
channel (config/channels.discovered.state.json, git-ignored), so running the same command again the next
day continues where it stopped; nothing is searched or read twice. If Telegram asks to wait (FloodWait)
more than --max-flood-wait seconds, the run saves and stops for the day; a shorter wait is waited out and
the pace halved. At most --max-new-per-keyword new channels are scored per search. Only one Telegram job
(discovery or collector) can run at a time (store/telegram.lock).

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

Also per candidate:
  geo_score        share of sampled posts (with text) naming a Rajasthan district or place (English,
                   Hindi and common spellings) or a Rajasthan PIN code (30xxxx-34xxxx, amounts excluded);
                   rajasthan_focus = geo_score >= scoring.rajasthan_focus (0.2); top_district
  category         payout_mule, account_sale, usdt_p2p, crypto_investment_scam, task_job_scam,
                   legit_finance or unrelated, from cue words; 'unclear' when no category clearly leads
  awareness_share  share of posts with awareness wording (cyber-police / bank warning channels)

Seeds come from config/discovery_seeds.yaml and, if present, store/discovery_seeds.yaml (git-ignored;
entries may carry a 'group', which is kept as seed_group).

Stop rule: fraud keywords run until there are --target-fraud likely_fraud candidates and
--target-rajasthan of them are rajasthan_focus; once the first is met only the Rajasthan keywords
keep running. Legit keywords run until --legit-target candidates are categorised legit_finance.

Channel titles are written with identifiers masked. Post text and contact values are never printed,
logged or written.

Output: the YAML file (same format as channels.yaml, every entry approved: false, sorted by score),
a CSV next to it for review, and a per-keyword CSV. The collector only reads entries a person has
set to approved: true whose label is likely_fraud or likely_legit.
"""
import argparse
import asyncio
import csv
import json
import logging
import os
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from collect.rajasthan import places_in
from collect.telegram_public import (RateLimiter, load_config as load_channels_config, make_client,
                                     normalize_username, telegram_lock)
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
    # USDT / P2P rails used to cash out mule money
    "crypto": ["p2p", "f2f", "binance", "tether", "trc20", "usdt seller", "usdt buyer", "inr to usdt", "usdt to inr",
               "usdt cash", "crypto exchange", "यूएसडीटी"],
    # investment / trading scams
    "investment_scam": ["double money", "100% profit", "daily return", "daily profit", "guaranteed profit",
                        "guaranteed return", "investment plan", "forex signal", "forex signals", "vip signal",
                        "trading profit", "profit daily", "crypto investment", "पैसा डबल", "दोगुना", "गारंटीड"],
    # awareness / official wording: a cyber-police or bank channel warning about mule accounts
    "awareness": ["beware", "cyber crime", "cybercrime", "1930", "awareness", "never share", "report fraud",
                  "cyber dost", "sanchar saathi", "cybercrime.gov.in", "sachet", "सावधान", "जागरूक",
                  "साइबर अपराध", "धोखाधड़ी से बचें", "ठगी से बचें"],
    # market / regulator news: legit finance channels
    "finance_news": ["nifty", "sensex", "mutual fund", "ipo", "repo rate", "interest rate", "monetary policy",
                     "circular", "press release", "निफ्टी", "सेंसेक्स", "म्यूचुअल फंड"],
}
WEIGHTS = {"strong": 3.0, "sale": 2.0, "bank": 1.0, "lure": 1.0, "crypto": 2.0, "investment_scam": 3.0,
           "awareness": -3.0, "finance_news": -1.0}


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


# --------------------------------------------------------------------------- categories

CATEGORY_TERMS: dict[str, list[str]] = {
    "payout_mule": ["payout", "payin", "pay-in", "pay in", "gaming", "betting", "casino", "per transaction",
                    "commission per", "running account", "settlement", "fund transfer", "escrow", "upi load",
                    "payment gateway", "gateway account", "merchant account", "pg account", "पेआउट"],
    "account_sale": ["kit", "kits", "full kit", "passbook", "net banking", "netbanking", "corporate account",
                     "current account", "savings account", "saving account", "firm account", "old account",
                     "fresh account", "account sale", "account sell", "on rent", "for rent", "kiraye", "kiraya",
                     "khata", "atm card", "debit card", "sim card", "cheque book", "किराये", "किराए", "करंट अकाउंट",
                     "खाता", "पासबुक", "किट"],
    "usdt_p2p": ["usdt", "p2p", "f2f", "binance", "tether", "trc20", "erc20", "inr to usdt", "usdt to inr",
                 "usdt rate", "buy usdt", "sell usdt", "crypto exchange", "usdt cash", "यूएसडीटी"],
    "crypto_investment_scam": ["double money", "100% profit", "daily return", "daily profit", "guaranteed profit",
                               "guaranteed return", "investment plan", "forex signal", "forex signals",
                               "vip signal", "trading profit", "profit daily", "crypto investment", "roi",
                               "पैसा डबल", "दोगुना", "मुनाफा", "गारंटीड"],
    "task_job_scam": ["part time", "part-time", "task", "tasks", "work from home", "daily payment", "daily income",
                      "ghar baithe", "kamai", "like videos", "youtube like", "review task", "prepaid task", "job",
                      "jobs", "salary", "पार्ट टाइम", "घर बैठे", "कमाई", "जॉब", "नौकरी"],
    "legit_finance": ["nifty", "sensex", "mutual fund", "ipo", "repo rate", "interest rate", "monetary policy",
                      "rbi", "sebi", "circular", "press release", "stock market", "share market", "fd rates",
                      "fixed deposit", "personal finance", "budget", "inflation", "gdp", "dividend", "quarterly results",
                      "निफ्टी", "सेंसेक्स", "शेयर बाजार", "म्यूचुअल फंड", "ब्याज दर"],
}
FRAUD_CATEGORIES = ["payout_mule", "account_sale", "usdt_p2p", "crypto_investment_scam", "task_job_scam"]
_CAT_RX = [(cat, t, _rx(t)) for cat, terms in CATEGORY_TERMS.items() for t in terms]
_AWARE_RX = [_rx(t) for t in CUES["awareness"]]


def category_hits(text: str) -> Counter:
    """Distinct category terms in one text (a longer term hides a shorter one inside it)."""
    if not text:
        return Counter()
    hits = {(cat, t) for cat, t, rx in _CAT_RX if rx.search(text)}
    terms = {t for _, t in hits}
    return Counter(cat for cat, t in hits if not any(t != o and t in o for o in terms))


def decide_category(hits: Counter, label: str, verified: bool, posts: int) -> str:
    """Rule-based category from cue counts summed over the sampled posts and the title."""
    if posts == 0:
        return "unclear"
    fraud = sorted(((hits[c], c) for c in FRAUD_CATEGORIES), reverse=True)
    (top_n, top), (second_n, _) = fraud[0], fraud[1]
    fraud_total = sum(n for n, _ in fraud)
    legit_n = hits["legit_finance"]
    if label == "likely_legit":
        if verified or (legit_n >= 3 and legit_n > fraud_total):
            return "legit_finance"
        if fraud_total <= 2 and legit_n < 3:
            return "unrelated"
        return "unclear"
    if top_n >= 3 and top_n >= 1.5 * second_n:          # clearly ahead of the runner-up
        return top
    if label == "unclear" and legit_n >= 3 and legit_n > fraud_total:
        return "legit_finance"
    return "unclear"


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
    category: str = "unclear"
    geo_score: float = 0.0
    rajasthan_focus: bool = False
    districts: dict = field(default_factory=dict)
    top_district: str = ""
    awareness_share: float = 0.0
    seed_group: str = ""
    error: str = ""
    inspected: bool = False


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

    places = [places_in(t) for t in with_text]
    district_counts = Counter(d for ps in places for d in ps)
    district_counts.update(places_in(c.title))
    c.geo_score = round(sum(bool(ps) for ps in places) / len(with_text), 3) if with_text else 0.0
    c.rajasthan_focus = c.geo_score >= s.get("rajasthan_focus", 0.2)
    c.districts = dict(district_counts.most_common(3))
    named = [d for d, _ in district_counts.most_common() if d not in ("rajasthan", "rajasthan_pin")]
    c.top_district = named[0] if named else (district_counts.most_common(1)[0][0] if district_counts else "")

    hits = Counter()
    for t in with_text + [c.title]:
        hits.update(category_hits(t))
    c.category = decide_category(hits, c.label, c.verified, len(with_text))
    c.awareness_share = round(sum(any(rx.search(t) for rx in _AWARE_RX) for t in with_text) / len(with_text), 3) \
        if with_text else 0.0


# --------------------------------------------------------------------------- telegram calls

class StopForToday(Exception):
    """Stop cleanly, save state, and continue on the next run (budget used up or Telegram asked to wait)."""


class DailyBudget:
    """Requests per calendar day, remembered in the state file across runs."""

    def __init__(self, limit: int, state: dict, today: str):
        self.limit, self.state = limit, state
        if state.get("budget_date") != today:
            state["budget_date"], state["requests_today"] = today, 0

    @property
    def used(self) -> int:
        return self.state["requests_today"]

    @property
    def remaining(self) -> int:
        return self.limit - self.used

    def spend(self) -> None:
        if self.remaining <= 0:
            raise StopForToday(f"daily budget of {self.limit} requests used")
        self.state["requests_today"] += 1


class Discoverer:
    def __init__(self, client, settings: dict, limiter: RateLimiter, budget: DailyBudget, sleep=asyncio.sleep,
                 max_flood_wait: int = 60, max_retries: int = 3, max_new_per_keyword: int = 15):
        self.client, self.s, self.limiter, self.sleep = client, settings, limiter, sleep
        self.budget, self.max_flood_wait, self.max_retries = budget, max_flood_wait, max_retries
        self.max_new = max_new_per_keyword
        self.by_id: dict[int, Candidate] = {}
        self.requests = 0                            # this run

    async def _call(self, fn, *args, **kwargs):
        """One Telegram request: counted against the daily budget, spaced by the rate limiter. A FloodWait
        longer than max_flood_wait ends the run for today; a shorter one is waited out and the request
        rate is halved for the rest of the run."""
        from telethon.errors import FloodWaitError
        for attempt in range(self.max_retries + 1):
            self.budget.spend()
            await self.limiter.wait()
            self.requests += 1
            try:
                return await fn(*args, **kwargs)
            except FloodWaitError as e:
                if e.seconds > self.max_flood_wait or attempt == self.max_retries:
                    raise StopForToday(f"Telegram asked to wait {e.seconds}s")
                self.limiter.interval *= 2
                log.warning("FloodWait %ss: waiting, then slowing to %.1f requests/min", e.seconds,
                            60 / self.limiter.interval)
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

    async def search(self, q: str, role: str) -> tuple[int, list[Candidate], int]:
        """(results, new candidates to inspect, new candidates dropped by the per-keyword cap)."""
        from telethon.tl.functions.contacts import SearchRequest
        found = await self._call(self.client, SearchRequest(q=q, limit=int(self.s["search_limit"])))
        chats = list(getattr(found, "chats", []) or [])
        new = [c for c in (self._add(ch, f"keyword '{q}'", role) for ch in chats) if c]
        capped = new[self.max_new:]
        for c in capped:                             # not scored now; a later keyword may find them again
            del self.by_id[c.id]
        return len(chats), new[:self.max_new], len(capped)

    async def _seed_input(self, username: str):
        """Input peer from Telethon's on-disk entity cache if it has the username (no request), otherwise
        one ResolveUsername request (these have the tightest daily limit, so the cache matters)."""
        session = getattr(self.client, "session", None)
        if session is not None:
            try:
                return session.get_input_entity(username)
            except (ValueError, KeyError, TypeError):
                pass
        return await self._call(self.client.get_input_entity, username)

    async def seeds(self, seeds: list[tuple[str, str]]) -> tuple[list[Candidate], list[str]]:
        """Resolve seeds (cache first) and fetch them in one batched request. Returns (new candidates,
        usernames that could not be used)."""
        inputs, failed = [], []
        for u, g in seeds:
            try:
                inputs.append((u, g, await self._seed_input(u)))
            except StopForToday:
                raise
            except Exception as e:                   # unknown / deleted username
                log.warning("seed %s: %s", u, type(e).__name__)
                failed.append(u)
        entities = []
        if inputs:
            try:
                entities = await self._call(self.client.get_entity, [x[2] for x in inputs])
            except StopForToday:
                raise
            except Exception:                        # one bad seed spoils the batch: fetch one by one
                entities = []
                for u, _, inp in inputs:
                    try:
                        entities.append(await self._call(self.client.get_entity, inp))
                    except StopForToday:
                        raise
                    except Exception as e:
                        log.warning("seed %s: %s", u, type(e).__name__)
                        entities.append(None)
        out = []
        for (u, g, _), entity in zip(inputs, entities):
            if entity is None:
                failed.append(u)
                continue
            c = self._add(entity, "seed list" + (f" (group: {g})" if g else ""), "seed")
            if c is not None:
                c.seed_group = g
                out.append(c)
            elif entity.id not in self.by_id:
                log.warning("seed %s: not a public channel or supergroup", u)
                failed.append(u)
        return out, failed

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
            # one more request for the subscriber count, only where it matters for review
            if c.subscribers is None and c.label == "likely_fraud":
                full = await self._call(self.client, GetFullChannelRequest(channel=entity))
                c.subscribers = getattr(full.full_chat, "participants_count", None)
        except StopForToday:
            raise
        except Exception as e:                      # private since search, banned, history hidden ...
            c.error = type(e).__name__
            c.label = "unclear"
            log.warning("%s: %s", c.username, c.error)
        c.inspected = True
        log.debug("%-32s %-9s %-12s %-22s score=%5.2f contacts=%.0f%% geo=%.2f posts=%d", c.username, c.kind,
                  c.label, c.category, c.score, 100 * c.contact_share, c.geo_score, c.posts_sampled)

    def count(self, label: str | None = None, role: str | None = None, category: str | None = None,
              rajasthan: bool = False) -> int:
        return sum(c.inspected and (label is None or c.label == label) and (role is None or c.role == role)
                   and (category is None or c.category == category) and (not rajasthan or c.rajasthan_focus)
                   for c in self.by_id.values())


# --------------------------------------------------------------------------- state

STATE_VERSION = 1


def load_state(path: Path) -> dict:
    if path.exists():
        st = json.loads(path.read_text(encoding="utf-8"))
        if st.get("version") == STATE_VERSION:
            return st
        log.warning("%s has an old format; starting fresh", path)
    return {"version": STATE_VERSION, "keywords_done": [], "rows": [], "candidates": [], "seeds_done": [],
            "seeds_failed": []}


def save_state(path: Path, state: dict, d: "Discoverer") -> None:
    state["candidates"] = [asdict(c) for c in d.by_id.values() if c.inspected]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


# --------------------------------------------------------------------------- config / output

def load_seeds(*paths) -> list[tuple[str, str]]:
    """[(username, group)] from seed files; entries are usernames or {username, group}. First file wins
    on duplicates, except that a later file can add a group to a seed that had none."""
    out: dict[str, list] = {}
    for path in paths:
        if not path or not Path(path).exists():
            continue
        for item in (yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}).get("seeds", []) or []:
            item = {"username": item} if isinstance(item, str) else dict(item)
            name = normalize_username(str(item.get("username", "")))
            group = str(item.get("group") or "")
            key = name.lower()
            if key not in out:
                out[key] = [name, group]
            elif group and not out[key][1]:
                out[key][1] = group
    return [tuple(v) for v in out.values()]


def expand_rajasthan(spec: dict) -> list[tuple[str, str]]:
    """'<place> <suffix>' searches: priority places first, then the Hindi ones, then the rest. With the stop
    rule this means the smaller places are only searched if the Rajasthan target is not met yet."""
    places = spec.get("places", [])
    first = [x for x in spec.get("priority_places", []) if x in places]
    rest = [x for x in places if x not in first]
    kws = [f"{p} {s}" for p in first for s in spec.get("suffixes", [])]
    kws += [f"{p} {s}" for p in spec.get("hindi_places", []) for s in spec.get("hindi_suffixes", [])]
    kws += [f"{p} {s}" for p in rest for s in spec.get("suffixes", [])]
    return [("rajasthan", k) for k in kws]


def load_discovery_config(keywords_path, seeds_path, extra_seeds_path=None) -> dict:
    kw = yaml.safe_load(Path(keywords_path).read_text(encoding="utf-8")) or {}
    seeds = load_seeds(seeds_path, extra_seeds_path)
    scoring = {"posts_per_channel": 20, "contact_weight": 4.0, "title_weight": 0.5, "post_cap": 10.0,
               "likely_fraud": 5.0, "likely_legit": 2.0, "rajasthan_focus": 0.2, **(kw.get("scoring") or {})}
    if scoring["likely_legit"] > scoring["likely_fraud"]:
        raise ValueError("scoring.likely_legit must not be above scoring.likely_fraud")

    def flat(section):
        out = []
        for group, terms in (kw.get(section) or {}).items():
            out += [(group, t.strip()) for t in terms or [] if t and t.strip()]
        return out
    fraud = flat("fraud") + expand_rajasthan(kw.get("rajasthan") or {})
    seen, uniq = set(), []
    for g, k in fraud:                              # "usdt payout" is in two groups: search it once
        if k.lower() not in seen:
            seen.add(k.lower())
            uniq.append((g, k))
    return {"fraud": uniq, "legit": flat("legit"), "seeds": seeds,
            "settings": {**scoring, "search_limit": int(kw.get("search_limit", 100))}}


def _entry(c: Candidate, today: str) -> dict:
    first = c.found_by[0]
    return {"username": c.username, "title": c.title, "approved": False, "label": c.label, "score": c.score,
            "category": c.category, "rajasthan_focus": c.rajasthan_focus, "geo_score": c.geo_score,
            "top_district": c.top_district or None, "districts": c.districts,
            "awareness_share": c.awareness_share,
            "subscribers": c.subscribers, "last_post": c.last_post or None, "lang_mix": c.lang_mix,
            "kind": c.kind, "verified": c.verified, "tg_scam_flag": c.tg_scam_flag,
            "contact_share": c.contact_share, "posts_sampled": c.posts_sampled,
            "found_by": c.found_by, "reason": f"auto-discovered {today} by {first}",
            **({"seed_group": c.seed_group} if c.seed_group else {}), **({"error": c.error} if c.error else {})}


def write_outputs(out: Path, cands: list[Candidate], keyword_rows: list[dict], settings: dict,
                  collector_settings: dict) -> None:
    today = date.today().isoformat()
    cands = sorted(cands, key=lambda c: (-c.score, c.username.lower()))
    doc = {"generated": today,
           "note": "Candidates for human review. Set approved: true only after checking a channel by hand. "
                   "The collector reads only approved likely_fraud / likely_legit broadcast channels.",
           "scoring": {k: settings[k] for k in ("posts_per_channel", "contact_weight", "title_weight",
                                                "likely_fraud", "likely_legit", "rajasthan_focus")},
           "channels": [_entry(c, today) for c in cands],
           "settings": collector_settings}
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    tmp.replace(out)

    cols = ["username", "title", "subscribers", "last_post", "score", "category", "rajasthan_focus", "geo_score",
            "lang_mix", "found_by", "label", "kind", "approved"]
    with open(out.with_suffix(".csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for c in cands:
            mix = c.lang_mix or {}
            w.writerow({"username": c.username, "title": c.title, "subscribers": c.subscribers,
                        "last_post": c.last_post, "score": c.score, "category": c.category,
                        "rajasthan_focus": c.rajasthan_focus, "geo_score": c.geo_score,
                        "lang_mix": f"dev={mix.get('devanagari', 0)};rom={mix.get('roman_hindi', 0)};"
                                    f"en={mix.get('english', 0)}",
                        "found_by": "; ".join(c.found_by), "label": c.label, "kind": c.kind, "approved": False})
    with open(out.with_name(out.stem + ".keywords.csv"), "w", newline="", encoding="utf-8") as f:
        cols = ["role", "group", "keyword", "results", "new_public", "likely_fraud", "unclear", "likely_legit",
                "rajasthan_focus", "legit_finance", "capped"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(keyword_rows)


# --------------------------------------------------------------------------- run

def _kw_key(role: str, kw: str) -> str:
    return f"{role}|{kw.lower()}"


async def discover(client, cfg: dict, out: Path, target_fraud: int = 100, legit_target: int = 20,
                   rpm: float = 6, collector_settings: dict | None = None, sleep=asyncio.sleep,
                   target_rajasthan: int = 25, state_path: Path | None = None, daily_budget: int = 300,
                   max_new_per_keyword: int = 15, max_flood_wait: int = 60, today: str | None = None) -> dict:
    s = cfg["settings"]
    state_path = Path(state_path or out.with_name(out.stem + ".state.json"))
    state = load_state(state_path)
    budget = DailyBudget(daily_budget, state, today or date.today().isoformat())
    d = Discoverer(client, s, RateLimiter(rpm, sleep=sleep), budget, sleep=sleep, max_flood_wait=max_flood_wait,
                   max_new_per_keyword=max_new_per_keyword)
    for cd in state["candidates"]:                   # resume: channels scored on earlier runs are not re-read
        c = Candidate(**cd)
        d.by_id[c.id] = c
    rows: list[dict] = state["rows"]
    collector_settings = collector_settings or {}
    # a keyword costs 1 search + up to max_new history reads + a few subscriber counts: start it only if
    # the day's budget can cover it, so it is never left half done
    reserve = 1 + max_new_per_keyword + 3

    def row(role, group, kw, n_results, new, capped=0):
        labels = Counter(c.label for c in new)
        rows.append({"role": role, "group": group, "keyword": kw, "results": n_results, "new_public": len(new),
                     **{k: labels.get(k, 0) for k in ("likely_fraud", "unclear", "likely_legit")},
                     "rajasthan_focus": sum(c.rajasthan_focus for c in new),
                     "legit_finance": sum(c.category == "legit_finance" for c in new), "capped": capped})

    def checkpoint():
        save_state(state_path, state, d)
        write_outputs(out, [c for c in d.by_id.values() if c.inspected], rows, s, collector_settings)

    stopped, skipped, reason = False, 0, ""
    fraud_done = lambda: d.count("likely_fraud") >= target_fraud  # noqa: E731
    raj_done = lambda: d.count("likely_fraud", rajasthan=True) >= target_rajasthan  # noqa: E731
    try:
        done_seeds = {u.lower() for u in state["seeds_done"] + state["seeds_failed"]}
        pending = [(u, g) for u, g in cfg["seeds"] if u.lower() not in done_seeds]
        if pending:
            new, failed = await d.seeds(pending)
            for c in new:
                await d.inspect(c)
                checkpoint()
            state["seeds_done"] += [u for u, _ in pending if u not in failed]
            state["seeds_failed"] += failed
            row("seed", "seeds", "(seed list)", len(pending), new)
            checkpoint()

        for role, keywords in (("fraud", cfg["fraud"]), ("legit", cfg["legit"])):
            for group, kw in keywords:
                if role == "fraud":
                    if fraud_done() and raj_done():
                        stopped = True
                        break
                    if fraud_done() and group != "rajasthan":    # only Rajasthan searches still help
                        skipped += 1
                        continue
                elif d.count(category="legit_finance") >= legit_target:
                    break
                if _kw_key(role, kw) in state["keywords_done"]:
                    continue
                if budget.remaining < reserve:
                    raise StopForToday(f"daily budget nearly used ({budget.used}/{daily_budget})")
                n, new, capped = await d.search(kw, role)
                for c in new:
                    await d.inspect(c)
                    checkpoint()
                state["keywords_done"].append(_kw_key(role, kw))
                row(role, group, kw, n, new, capped)
                checkpoint()
                log.info("[%s] %-32s results=%3d new=%3d%s -> fraud %d / unclear %d / legit %d | total fraud %d "
                         "(raj %d), legit_finance %d | budget %d/%d", group, kw, n, len(new),
                         f" (+{capped} capped)" if capped else "",
                         *(sum(c.label == k for c in new) for k in ("likely_fraud", "unclear", "likely_legit")),
                         d.count("likely_fraud"), d.count("likely_fraud", rajasthan=True),
                         d.count(category="legit_finance"), budget.used, daily_budget)
            if stopped and role == "fraud":
                log.info("targets reached: %d likely_fraud (%d Rajasthan-focused)", d.count("likely_fraud"),
                         d.count("likely_fraud", rajasthan=True))
    except StopForToday as e:
        reason = str(e)
        log.warning("stopping for today: %s. Run the same command again later to continue.", reason)
    finally:
        for cid in [c.id for c in d.by_id.values() if not c.inspected]:   # half-done keyword: redo next run
            del d.by_id[cid]
        checkpoint()

    cands = [c for c in d.by_id.values() if c.inspected]
    fraud = [c for c in cands if c.label == "likely_fraud"]
    all_done = not reason
    return {"labels": Counter(c.label for c in cands), "categories": Counter(c.category for c in cands),
            "districts": Counter(c.top_district for c in cands if c.rajasthan_focus),
            "districts_fraud": Counter(c.top_district for c in fraud if c.rajasthan_focus),
            "rajasthan_fraud": sum(c.rajasthan_focus for c in fraud),
            "legit_finance": sum(c.category == "legit_finance" for c in cands),
            "keywords": rows, "requests": d.requests, "requests_today": budget.used, "daily_budget": daily_budget,
            "stopped_at_target": stopped, "skipped_keywords": skipped, "paused": reason, "finished": all_done,
            "keywords_done": len(state["keywords_done"]), "keywords_total": len(cfg["fraud"]) + len(cfg["legit"]),
            "candidates": len(cands), "targets": {"fraud": target_fraud, "rajasthan": target_rajasthan,
                                                   "legit_finance": legit_target}}


def print_report(result: dict, out: Path, stream=sys.stdout) -> None:
    p = lambda *a: print(*a, file=stream)  # noqa: E731
    if result.get("paused"):
        status = f"paused: {result['paused']}; run the same command again (tomorrow for the budget) to continue"
    elif result["stopped_at_target"]:
        status = "finished: targets reached"
    else:
        status = "finished: keywords exhausted"
    p(f"\n{status}")
    p(f"{result['candidates']} candidates scored so far; keywords searched {result.get('keywords_done', 0)}/"
      f"{result.get('keywords_total', 0)}; requests this run {result['requests']}, today "
      f"{result.get('requests_today', 0)}/{result.get('daily_budget', 0)}")
    t = result.get("targets", {})
    p("\nper label:")
    for k in ("likely_fraud", "unclear", "likely_legit"):
        p(f"  {k:24s} {result['labels'].get(k, 0)}")
    p(f"\ntargets: likely_fraud {result['labels'].get('likely_fraud', 0)}/{t.get('fraud')}, "
      f"of them rajasthan_focus {result.get('rajasthan_fraud', 0)}/{t.get('rajasthan')}, "
      f"legit_finance {result.get('legit_finance', 0)}/{t.get('legit_finance')}")
    p("\nper category:")
    for k, n in sorted(result.get("categories", {}).items(), key=lambda kv: -kv[1]):
        p(f"  {k:24s} {n}")
    p("\nper district (rajasthan_focus channels, by most-named place; likely_fraud in brackets):")
    for k, n in sorted(result.get("districts", {}).items(), key=lambda kv: -kv[1]):
        p(f"  {k or '-':24s} {n} ({result.get('districts_fraud', {}).get(k, 0)})")
    if result.get("skipped_keywords"):
        p(f"\n{result['skipped_keywords']} non-Rajasthan keywords skipped after the likely_fraud target was met")
    p(f"\n{'role':6s} {'keyword':34s} {'results':>7s} {'new':>4s} {'fraud':>5s} {'uncl':>5s} {'legit':>5s} "
      f"{'raj':>4s} {'lfin':>4s}")
    for r in result["keywords"]:
        p(f"{r['role']:6s} {r['keyword'][:34]:34s} {r['results']:7d} {r['new_public']:4d} {r['likely_fraud']:5d} "
          f"{r['unclear']:5d} {r['likely_legit']:5d} {r.get('rajasthan_focus', 0):4d} {r.get('legit_finance', 0):4d}")
    p(f"\n-> {out}\n-> {out.with_suffix('.csv')}\n-> {out.with_name(out.stem + '.keywords.csv')}")


def dry_run(cfg: dict, target_fraud: int, legit_target: int, rpm: float, stream=sys.stdout,
            target_rajasthan: int = 25, daily_budget: int = 300, max_new: int = 15,
            state: dict | None = None) -> None:
    s = cfg["settings"]
    p = lambda *a: print(*a, file=stream)  # noqa: E731
    p("dry run: no Telegram requests are made, nothing is written")
    p(f"  seeds: {len(cfg['seeds'])}  fraud keywords: {len(cfg['fraud'])}  legit keywords: {len(cfg['legit'])}")
    for g, n in Counter(g for g, _ in cfg["fraud"]).items():
        p(f"    {g}: {n}")
    p(f"  per keyword: 1 search, then 1 history read of {s['posts_per_channel']} posts for each of at most "
      f"{max_new} new channels (+1 for the subscriber count of likely_fraud ones that lack it)")
    p(f"  seeds: looked up from the session cache where possible, then fetched in one batched request")
    p(f"  seed groups: {dict(Counter(g or '-' for _, g in cfg['seeds']))}")
    p(f"  stop: {target_fraud} likely_fraud incl. {target_rajasthan} rajasthan_focus, or keywords exhausted; "
      f"then legit keywords until {legit_target} legit_finance")
    p(f"  labels: likely_fraud if score >= {s['likely_fraud']}, likely_legit if < {s['likely_legit']}")
    n_kw = len(cfg["fraud"]) + len(cfg["legit"])
    p(f"  pace: {rpm} requests/min, at most {daily_budget} requests a day (~{round(daily_budget / rpm)} min); "
      f"a FloodWait over the limit pauses until the next run")
    if state:
        p(f"  resume: {len(state.get('keywords_done', []))}/{n_kw} keywords done, "
          f"{len(state.get('candidates', []))} channels scored, "
          f"{state.get('requests_today', 0) if state.get('budget_date') == date.today().isoformat() else 0} "
          f"requests used today")


async def _connect(session: str, api_id: int, api_hash: str):
    # flood_sleep_threshold=0: every FloodWait reaches Discoverer._call, which decides to wait or pause
    client = make_client(session, api_id, api_hash, flood_sleep_threshold=0)
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
    cfg = load_discovery_config(args.keywords, args.seeds, args.extra_seeds)
    collector_settings = load_channels_config(args.channels_config)["settings"] \
        if Path(args.channels_config).exists() else {}
    out = Path(args.out)
    state_path = Path(args.state or out.with_name(out.stem + ".state.json"))
    if args.fresh and state_path.exists() and not args.dry_run:
        state_path.unlink()
    if args.dry_run:
        dry_run(cfg, args.target_fraud, args.legit_target, args.rpm, target_rajasthan=args.target_rajasthan,
                daily_budget=args.daily_budget, max_new=args.max_new_per_keyword,
                state=None if args.fresh else load_state(state_path))
        return
    load_env()
    api_id, api_hash = os.environ.get("TELEGRAM_API_ID"), os.environ.get("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        raise SystemExit("set TELEGRAM_API_ID and TELEGRAM_API_HASH in research/.env")
    session = os.environ.get("TELEGRAM_SESSION", "store/telegram_research.session")
    Path(session).parent.mkdir(parents=True, exist_ok=True)
    with telegram_lock():
        client = await _connect(session, int(api_id), api_hash)
        try:
            if args.login:
                me = await client.get_me()
                print(f"logged in (user id {me.id}); session saved to {session}")
                return
            result = await discover(client, cfg, out, args.target_fraud, args.legit_target, args.rpm,
                                    collector_settings, target_rajasthan=args.target_rajasthan, state_path=state_path,
                                    daily_budget=args.daily_budget, max_new_per_keyword=args.max_new_per_keyword,
                                    max_flood_wait=args.max_flood_wait)
        finally:
            await client.disconnect()
    print_report(result, out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Discover candidate public channels (read-only)")
    ap.add_argument("--out", default="config/channels.discovered.yaml")
    ap.add_argument("--keywords", default="config/discovery_keywords.yaml")
    ap.add_argument("--seeds", default="config/discovery_seeds.yaml")
    ap.add_argument("--extra-seeds", default="store/discovery_seeds.yaml", help="git-ignored seeds with groups")
    ap.add_argument("--channels-config", default="config/channels.yaml", help="collector settings copied into --out")
    ap.add_argument("--target-fraud", type=int, default=100, help="stop fraud keywords once this many likely_fraud")
    ap.add_argument("--target-rajasthan", type=int, default=25, help="of the likely_fraud, rajasthan_focus")
    ap.add_argument("--legit-target", type=int, default=20, help="legit_finance negatives")
    ap.add_argument("--rpm", type=float, default=6, help="Telegram requests per minute (at most 20)")
    ap.add_argument("--daily-budget", type=int, default=300, help="requests per calendar day, across runs")
    ap.add_argument("--max-new-per-keyword", type=int, default=15, help="new channels scored per search")
    ap.add_argument("--max-flood-wait", type=int, default=60,
                    help="pause until the next run if Telegram asks to wait longer than this (seconds)")
    ap.add_argument("--state", default="", help="resume file (default: next to --out, git-ignored)")
    ap.add_argument("--fresh", action="store_true", help="ignore saved progress and start over")
    ap.add_argument("--dry-run", action="store_true", help="print the plan without contacting Telegram")
    ap.add_argument("--login", action="store_true", help="log the research account in (interactive) and exit")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    if not 0 < args.rpm <= 20:
        raise SystemExit("--rpm must be between 0 and 20")
    if not 0 < args.daily_budget <= 1000:
        raise SystemExit("--daily-budget must be between 1 and 1000")
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("telethon").setLevel(logging.WARNING)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
