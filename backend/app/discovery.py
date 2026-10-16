"""Internet discovery: find mule-account ads anywhere on the public web, district by district.

Every cycle it runs a few web searches (sale/rent wording x target district x platform), keeps each new result,
scores the title and snippet, opens the promising ones and scores them like any other post, so they become cases
with the usual alerts, evidence and drafts. Telegram channels named in what it finds are suggested for continuous
monitoring.

Search providers (set one key in .env):
  BRAVE_API_KEY                     Brave Search API (independent index)
  SERPER_API_KEY                    Serper.dev (Google results)
  GOOGLE_CSE_KEY + GOOGLE_CSE_CX    Google Programmable Search (closed to new customers)
  SEARXNG_URL                       a self-hosted SearXNG instance (free, no key)
Without any of them it runs in demo mode against the local Charcha forum's search.

Only what search engines have indexed publicly is reachable: open Telegram channels, public Instagram profiles and
posts, public Facebook pages and groups, OLX, YouTube, X, forums and websites. Nothing behind a login is accessed.
"""
import html as _html
import os
import re
import threading
import time
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

from . import audit, jurisdiction
from .config import LEVEL_RANK, PUBLIC_BASE_URL
from .db import (DiscoveredChannel, DiscoveryHit, DiscoveryQuery, DiscoveryRun, Post, SessionLocal, Source)

# ----------------------------------------------------------------------------- settings

PHASE1 = ["Jaipur", "Jodhpur", "Udaipur", "Bikaner", "Bharatpur", "Jhunjhunu", "Sikar", "Kota", "Dholpur"]


def _env_list(name, default):
    v = os.getenv(name, "")
    return [x.strip() for x in v.split(",") if x.strip()] or default


def districts() -> list[str]:
    return [d for d in _env_list("DISCOVERY_DISTRICTS", PHASE1) if d in jurisdiction.DISTRICTS]


def _int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


ENABLED = os.getenv("DISCOVERY_ENABLED", "1") != "0"
INTERVAL_MIN = lambda: max(5, _int("DISCOVERY_INTERVAL_MINUTES", 30))          # noqa: E731
DAILY_BUDGET = lambda: max(0, _int("DISCOVERY_DAILY_QUERIES", 100))            # noqa: E731
BATCH = lambda: max(1, _int("DISCOVERY_BATCH", 8))                             # noqa: E731
MIN_TRIAGE = lambda: float(os.getenv("DISCOVERY_MIN_TRIAGE", "30"))            # noqa: E731
OPEN_PER_RUN = lambda: max(1, _int("DISCOVERY_OPEN_PER_RUN", 25))              # noqa: E731
FRESHNESS = lambda: os.getenv("DISCOVERY_FRESHNESS", "month").lower()          # week | month | year | any  # noqa: E731
PAUSE = float(os.getenv("DISCOVERY_PAUSE_SECONDS", "1.0"))

# Sale / rent wording that sellers actually use. Hindi wording is paired with the Hindi district name.
TERMS_EN = [
    "bank account kit", "current account kit available", "savings account for sale", "rent your bank account",
    "corporate account kit", "ATM card with PIN for sale", "gaming withdrawal account",
    "khata kiraye par", "account kiraye pe dena", "net banking kit",
]
TERMS_HI = ["बैंक खाता किराये पर", "खाता किराए पर दें पैसे कमाएं"]
# "" = whole web. Each site: search reaches what that platform has made public to search engines.
SITES = ["", "t.me", "instagram.com", "facebook.com", "youtube.com", "x.com", "olx.in", "sharechat.com",
         "quora.com", "reddit.com"]
PLATFORM_OF_SITE = {"": "Whole web", "t.me": "Telegram", "instagram.com": "Instagram", "facebook.com": "Facebook",
                    "youtube.com": "YouTube", "x.com": "X", "olx.in": "OLX", "sharechat.com": "ShareChat",
                    "quora.com": "Quora", "reddit.com": "Reddit"}
TG_SKIP = {"s", "joinchat", "share", "addstickers", "proxy", "iv", "c", "addlist", "boost", "socks", "setlanguage",
           "contact", "login", "telegram", "durov", "username"}
TG_RX = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?@?([A-Za-z][A-Za-z0-9_]{4,31})\b", re.I)
SKIP_HOSTS = ("cybercrime.gov.in", "rbi.org.in", "npci.org.in", "sachet.rbi.org.in", "gov.in", "nic.in")

_state = {"running": False, "busy": False, "next_run": None, "last_error": "", "thread": None}
_lock = threading.Lock()
_wake = threading.Event()


# ----------------------------------------------------------------------------- providers

class SearchError(Exception):
    pass


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _brave(q: str) -> list[dict]:
    fresh = {"week": "pw", "month": "pm", "year": "py"}.get(FRESHNESS())
    params = {"q": q, "count": 20, "country": "IN", "safesearch": "off"}
    if fresh:
        params["freshness"] = fresh
    r = requests.get("https://api.search.brave.com/res/v1/web/search", params=params, timeout=15,
                     headers={"X-Subscription-Token": os.getenv("BRAVE_API_KEY", ""), "Accept": "application/json"})
    if r.status_code != 200:
        raise SearchError(f"Brave Search returned {r.status_code}: {r.text[:160]}")
    return [{"url": x.get("url", ""), "title": _clean(x.get("title")), "snippet": _clean(x.get("description")),
             "published": x.get("page_age") or x.get("age") or ""} for x in (r.json().get("web") or {}).get("results", [])]


def _serper(q: str) -> list[dict]:
    body = {"q": q, "gl": "in", "num": 20}
    tbs = {"week": "qdr:w", "month": "qdr:m", "year": "qdr:y"}.get(FRESHNESS())
    if tbs:
        body["tbs"] = tbs
    r = requests.post("https://google.serper.dev/search", json=body, timeout=15,
                      headers={"X-API-KEY": os.getenv("SERPER_API_KEY", ""), "Content-Type": "application/json"})
    if r.status_code != 200:
        raise SearchError(f"Serper returned {r.status_code}: {r.text[:160]}")
    return [{"url": x.get("link", ""), "title": _clean(x.get("title")), "snippet": _clean(x.get("snippet")),
             "published": x.get("date", "")} for x in r.json().get("organic", [])]


def _google(q: str) -> list[dict]:
    params = {"key": os.getenv("GOOGLE_CSE_KEY", ""), "cx": os.getenv("GOOGLE_CSE_CX", ""), "q": q, "num": 10, "gl": "in"}
    d = {"week": "w1", "month": "m1", "year": "y1"}.get(FRESHNESS())
    if d:
        params["dateRestrict"] = d
    r = requests.get("https://www.googleapis.com/customsearch/v1", params=params, timeout=15)
    if r.status_code != 200:
        raise SearchError(f"Google Programmable Search returned {r.status_code}: {r.text[:160]}")
    return [{"url": x.get("link", ""), "title": _clean(x.get("title")), "snippet": _clean(x.get("snippet")),
             "published": ""} for x in r.json().get("items", [])]


def _searxng(q: str) -> list[dict]:
    params = {"q": q, "format": "json", "language": "all"}
    tr = {"week": "week", "month": "month", "year": "year"}.get(FRESHNESS())
    if tr:
        params["time_range"] = tr
    r = requests.get(os.getenv("SEARXNG_URL", "").rstrip("/") + "/search", params=params, timeout=20,
                     headers={"User-Agent": "MuleWatch-Discovery/1.0"})
    if r.status_code != 200:
        raise SearchError(f"SearXNG returned {r.status_code}")
    return [{"url": x.get("url", ""), "title": _clean(x.get("title")), "snippet": _clean(x.get("content")),
             "published": x.get("publishedDate") or ""} for x in r.json().get("results", [])]


def _forum_demo(q: str) -> list[dict]:
    """Demo mode: the Charcha forum's own search stands in for a web search engine (offline demos)."""
    from .crawler import FORUM_URL
    term = re.sub(r"\bsite:\S+", "", q).replace('"', "")
    for d in jurisdiction.DISTRICTS.values():          # the forum search matches one phrase, so drop the place
        term = term.replace(d["name"], "").replace(d["hi"], "")
    term = term.replace("Rajasthan", "").replace("राजस्थान", "").strip()
    words = term.split()
    phrase = " ".join(words[:2]) if len(words) > 1 else term
    r = requests.get(FORUM_URL.rstrip("/") + "/search", params={"q": phrase}, timeout=10)
    if r.status_code != 200:
        raise SearchError(f"Forum search returned {r.status_code}")
    out = []
    for m in re.finditer(r'<h2 class="title"><a href="(/p/\d+)">(.*?)</a>', r.text, re.S):
        out.append({"url": FORUM_URL.rstrip("/") + m.group(1), "title": _clean(m.group(2)), "snippet": "", "published": ""})
    return out[:20]


PROVIDERS = {
    "brave": ("Brave Search", _brave, lambda: bool(os.getenv("BRAVE_API_KEY"))),
    "serper": ("Serper (Google results)", _serper, lambda: bool(os.getenv("SERPER_API_KEY"))),
    "google": ("Google Programmable Search", _google, lambda: bool(os.getenv("GOOGLE_CSE_KEY") and os.getenv("GOOGLE_CSE_CX"))),
    "searxng": ("SearXNG (self-hosted)", _searxng, lambda: bool(os.getenv("SEARXNG_URL"))),
    "forum": ("Demo: Charcha forum search", _forum_demo, lambda: os.getenv("DISCOVERY_DEMO", "1") != "0"),
}


def provider() -> str:
    want = os.getenv("DISCOVERY_PROVIDER", "auto").lower()
    if want in PROVIDERS and PROVIDERS[want][2]():
        return want
    for k in ("brave", "serper", "google", "searxng", "forum"):
        if PROVIDERS[k][2]():
            return k
    return ""


def search(q: str) -> tuple[str, list[dict]]:
    p = provider()
    if not p:
        raise SearchError("No search provider is set up")
    return p, PROVIDERS[p][1](q)


# ----------------------------------------------------------------------------- queries

def _q(term: str, place: str, site: str) -> str:
    return " ".join(x for x in (f'"{term}"' if " " in term else term, place, f"site:{site}" if site else "") if x)


def generated() -> list[dict]:
    out = []
    for dist in districts() + [""]:
        info = jurisdiction.DISTRICTS.get(dist)
        for site in SITES:
            for term in TERMS_EN:
                out.append({"text": _q(term, info["name"] if info else "Rajasthan", site), "term": term,
                            "district": dist, "site": site})
            for term in TERMS_HI:
                out.append({"text": _q(term, info["hi"] if info else "राजस्थान", site), "term": term,
                            "district": dist, "site": site})
    return out


def ensure_queries(s) -> int:
    """Create the generated queries; switch off generated ones for districts no longer targeted."""
    want = {g["text"]: g for g in generated()}
    have = {q.text: q for q in s.query(DiscoveryQuery).all()}
    added = 0
    for text, g in want.items():
        if text not in have:
            s.add(DiscoveryQuery(kind="auto", **g))
            added += 1
        elif have[text].kind == "auto" and not have[text].enabled and have[text].created_by == "district-off":
            have[text].enabled, have[text].created_by = True, ""
    for text, q in have.items():
        if q.kind == "auto" and text not in want and q.enabled:
            q.enabled, q.created_by = False, "district-off"
    s.commit()
    return added


def _priority(q: DiscoveryQuery, now: datetime) -> float:
    if not q.last_run:
        return 1e9 + (1e6 if q.kind == "custom" else 0)
    hours = (now - q.last_run).total_seconds() / 3600
    yield_ = 1 + 3 * (q.flagged or 0) + 0.5 * (q.new_hits or 0) / max(1, q.runs or 1)
    return hours * yield_ * (2 if q.kind == "custom" else 1)


def pick(s, n: int) -> list[DiscoveryQuery]:
    """The n most overdue queries, taken in turn from each district so every district is covered evenly."""
    now = datetime.utcnow()
    by_d = defaultdict(list)
    for q in s.query(DiscoveryQuery).filter_by(enabled=True).all():
        by_d[q.district].append(q)
    for lst in by_d.values():
        lst.sort(key=lambda q: _priority(q, now), reverse=True)
    order = sorted(by_d, key=lambda d: _priority(by_d[d][0], now), reverse=True)
    out, i = [], 0
    while len(out) < n and any(by_d[d] for d in order):
        d = order[i % len(order)]
        if by_d[d]:
            out.append(by_d[d].pop(0))
        i += 1
    return out


# ----------------------------------------------------------------------------- budget

def _ist_midnight_utc(now: datetime | None = None) -> datetime:
    ist = (now or datetime.utcnow()) + timedelta(hours=5, minutes=30)
    return ist.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=5, minutes=30)


def used_today(s) -> int:
    from sqlalchemy import func
    return int(s.query(func.coalesce(func.sum(DiscoveryRun.queries), 0))
               .filter(DiscoveryRun.started_at >= _ist_midnight_utc(), DiscoveryRun.provider != "forum").scalar() or 0)


# ----------------------------------------------------------------------------- results

_TRACKING = re.compile(r"^(utm_|fbclid|gclid|igshid|igsh|si$|ref$|ref_src|mibextid|__)", re.I)


def normalise(url: str) -> str:
    u = urlparse((url or "").strip())
    if u.scheme not in ("http", "https") or not u.netloc:
        return ""
    q = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if not _TRACKING.match(k)]
    host = u.netloc.lower()
    if host.startswith("m.") and any(host.endswith(x) for x in ("facebook.com", "youtube.com")):
        host = "www." + host[2:]
    return urlunparse((u.scheme.lower(), host, u.path.rstrip("/") or "/", "", urlencode(q), ""))[:500]


def channels_in(*texts: str) -> set[str]:
    out = set()
    for t in texts:
        for h in TG_RX.findall(t or ""):
            if h.lower() not in TG_SKIP and not h.lower().endswith("bot"):
                out.add(h.lower())
    return out


def _note_channels(s, handles: set[str], district: str, url: str):
    if not handles:
        return
    monitored = {(x.url or "").rstrip("/").split("/")[-1].lstrip("@").lower()
                 for x in s.query(Source).filter_by(kind="telegram").all()}
    for h in handles:
        c = s.query(DiscoveredChannel).filter_by(handle=h).first()
        if c:
            c.mentions += 1
            c.last_seen = datetime.utcnow()
            if district and district not in (c.districts or []):
                c.districts = (c.districts or []) + [district]
        else:
            s.add(DiscoveredChannel(handle=h, districts=[district] if district else [], example_url=url,
                                    status="monitored" if h in monitored else "suggested"))
    s.flush()


def _place(text: str) -> str:
    """District named in the result itself. A result is not tagged with the searched district unless it names it:
    search engines also return pages about other places."""
    return jurisdiction.suggest(Post(text=text, entities={})).get("district", "")


def _triage(text: str) -> float:
    from .scoring import analyze
    return analyze(text)["base_score"] if text.strip() else 0.0


def record_results(s, run: DiscoveryRun, q: DiscoveryQuery, prov: str, results: list[dict]) -> list[int]:
    """Store new results; returns ids of new hits worth opening."""
    own = urlparse(PUBLIC_BASE_URL).netloc
    fresh_ids = []
    for r in results:
        url = normalise(r.get("url", ""))
        host = urlparse(url).netloc
        if not url or host == own or any(host == h or host.endswith("." + h) for h in SKIP_HOSTS):
            continue
        hit = s.query(DiscoveryHit).filter_by(url=url).first()
        if hit:
            hit.seen_count += 1
            continue
        from .fetcher import platform_for
        text = f"{r.get('title', '')}\n{r.get('snippet', '')}"
        tri = _triage(text)
        hit = DiscoveryHit(url=url, title=(r.get("title") or "")[:300], snippet=(r.get("snippet") or "")[:2000],
                           platform=platform_for(url), district=_place(text), query_id=q.id, run_id=run.id,
                           provider=prov, published=str(r.get("published") or "")[:40], triage=tri,
                           status="new" if tri >= MIN_TRIAGE() or prov == "forum" else "skipped")
        s.add(hit)
        s.flush()
        q.new_hits = (q.new_hits or 0) + 1
        run.new_hits += 1
        if hit.status == "new":
            fresh_ids.append(hit.id)
            _note_channels(s, channels_in(url, text), q.district, url)
    return fresh_ids


def open_hit(hit_id: int) -> int | None:
    """Open one promising result and score it as a post. Returns the post id."""
    from .crawler import _parse_dt
    from .fetcher import FetchError, fetch_url
    from .pipeline import ingest
    with SessionLocal() as s:
        hit = s.get(DiscoveryHit, hit_id)
        existing = s.query(Post).filter(Post.url == hit.url).order_by(Post.id.desc()).first()
        if existing:
            hit.status, hit.post_id = "existing", existing.id
            s.commit()
            return None
        url, title, snippet = hit.url, hit.title, hit.snippet
    page, err = None, ""
    try:
        page = fetch_url(url)
        if len((page.get("text") or "").strip()) < 40 and not page.get("image_paths"):
            err, page = page.get("note") or "Page shows almost nothing without a login", None
    except FetchError as e:
        err = str(e)
    except Exception as e:                     # noqa: BLE001 - one odd page must not stop the run
        err = f"{type(e).__name__}: {str(e)[:150]}"
    with SessionLocal() as s:
        hit = s.get(DiscoveryHit, hit_id)
        q = s.get(DiscoveryQuery, hit.query_id) if hit.query_id else None
        why = f"Found by web search ({PLATFORM_OF_SITE.get(q.site, q.site) if q else 'web'}): {q.text if q else ''}".strip()
        if page:
            existing = s.query(Post).filter(Post.url == page["final_url"]).first()
            if existing:
                hit.status, hit.post_id = "existing", existing.id
                s.commit()
                return None
            imgs = page["image_paths"]
            p = ingest(s, text=page["text"], platform=page["platform"], author=page["author"], url=page["final_url"],
                       image_path=imgs[0] if imgs else "", extra_images=imgs[1:], posted_at=_parse_dt(page["posted_at"]),
                       source="discovery", recompute=False, html=page.get("html", ""))
            hit.how = "page"
            _note_channels(s, channels_in(page["text"]), hit.district, url)
        else:
            text = f"{title}\n{snippet}".strip()
            if not text:
                hit.status, hit.error = "error", err[:300]
                s.commit()
                return None
            from .fetcher import platform_for
            p = ingest(s, text=text, platform=platform_for(url), url=url, source="discovery", recompute=False)
            p.reasons = (p.reasons or []) + ["Built from the search result only (the page could not be read: "
                                             f"{err[:120]}). Open the original and verify before acting."]
            hit.how = "snippet"
        p.reasons = (p.reasons or []) + [why]
        hit.status, hit.post_id = "case", p.id
        s.commit()
        return p.id


def _settle(s, hit_ids: list[int]) -> int:
    """After rescoring: count High/Critical, credit the queries, fill in districts from the case."""
    flagged = 0
    for hid in hit_ids:
        hit = s.get(DiscoveryHit, hid)
        if not hit or not hit.post_id:
            continue
        p = s.get(Post, hit.post_id)
        if not p:
            continue
        if not hit.district:
            hit.district = (p.jurisdiction or {}).get("district") or jurisdiction.suggest(p).get("district", "")
        if hit.status == "case" and LEVEL_RANK.get(p.risk_level, 0) >= LEVEL_RANK["High"]:
            flagged += 1
            if hit.query_id and (q := s.get(DiscoveryQuery, hit.query_id)):
                q.flagged = (q.flagged or 0) + 1
    return flagged


# ----------------------------------------------------------------------------- one cycle

def run_cycle(trigger: str = "schedule", user=None, max_queries: int | None = None) -> dict:
    if not _lock.acquire(blocking=False):
        return {"ok": False, "message": "A search run is already in progress"}
    _state["busy"] = True
    try:
        prov = provider()
        with SessionLocal() as s:
            ensure_queries(s)
            budget_left = DAILY_BUDGET() - used_today(s) if prov != "forum" else BATCH()
            n = min(max_queries or BATCH(), budget_left)
            if not prov:
                return {"ok": False, "message": "No search provider is set up"}
            if n <= 0:
                return {"ok": False, "message": "Today's search budget is used up"}
            run = DiscoveryRun(provider=prov, trigger=trigger)
            s.add(run)
            s.commit()
            todo, errors = [], []
            for q in pick(s, n):
                try:
                    _, results = search(q.text)
                    q.last_error = ""
                except Exception as e:          # noqa: BLE001
                    results = []
                    q.last_error = str(e)[:300]
                    errors.append(q.last_error)
                q.runs = (q.runs or 0) + 1
                q.last_run = datetime.utcnow()
                q.results = (q.results or 0) + len(results)
                run.queries += 1
                run.results += len(results)
                todo += record_results(s, run, q, prov, results)
                s.commit()
                if errors and len(errors) >= 3 and not run.results:
                    break                        # the provider is failing (bad key, quota): stop spending
                time.sleep(PAUSE)
            run_id = run.id
        # open the most promising first
        with SessionLocal() as s:
            order = [h.id for h in s.query(DiscoveryHit).filter(DiscoveryHit.id.in_(todo))
                     .order_by(DiscoveryHit.triage.desc()).all()] if todo else []
            for hid in order[OPEN_PER_RUN():]:
                s.get(DiscoveryHit, hid).status = "skipped"
            s.commit()
        opened = []
        for hid in order[:OPEN_PER_RUN()]:
            try:
                open_hit(hid)
            except Exception:                    # noqa: BLE001
                traceback.print_exc()
            opened.append(hid)
        with SessionLocal() as s:
            if any(s.get(DiscoveryHit, h).status == "case" for h in opened):
                from .pipeline import recompute_all
                recompute_all(s, alert=True)
            run = s.get(DiscoveryRun, run_id)
            run.flagged = _settle(s, opened)
            run.finished_at = datetime.utcnow()
            run.error = "; ".join(dict.fromkeys(errors))[:300]
            s.commit()
            out = {"ok": True, "run": run_id, "queries": run.queries, "results": run.results,
                   "new_hits": run.new_hits, "flagged": run.flagged, "error": run.error}
        _state["last_error"] = out["error"]
        audit.log(user, "discovery.run", detail={k: v for k, v in out.items() if k != "ok"} | {"trigger": trigger})
        return out
    finally:
        _state["busy"] = False
        _lock.release()


# ----------------------------------------------------------------------------- scheduler

def _loop():
    time.sleep(20)                               # let the app finish starting
    while _state["running"]:
        try:
            if provider():
                run_cycle()
        except Exception as e:                   # noqa: BLE001
            traceback.print_exc()
            _state["last_error"] = str(e)[:200]
        _state["next_run"] = datetime.utcnow() + timedelta(minutes=INTERVAL_MIN())
        _wake.wait(INTERVAL_MIN() * 60)
        _wake.clear()


def start():
    if ENABLED and not _state["running"]:
        _state["running"] = True
        _state["next_run"] = datetime.utcnow() + timedelta(seconds=20)
        _state["thread"] = threading.Thread(target=_loop, daemon=True, name="discovery")
        _state["thread"].start()


def run_now(user) -> dict:
    if _state["busy"]:
        return {"ok": False, "message": "A search run is already in progress"}
    if not provider():
        return {"ok": False, "message": "No search provider is set up"}
    with SessionLocal() as s:
        if provider() != "forum" and used_today(s) >= DAILY_BUDGET():
            return {"ok": False, "message": "Today's search budget is used up"}
    threading.Thread(target=run_cycle, kwargs={"trigger": user.username, "user": user}, daemon=True).start()
    return {"ok": True, "message": "Search run started"}


# ----------------------------------------------------------------------------- read models for the API

def status(s) -> dict:
    prov = provider()
    total_q = s.query(DiscoveryQuery).filter_by(enabled=True).count()
    per_day = min(DAILY_BUDGET(), BATCH() * (24 * 60 // INTERVAL_MIN()))
    runs = s.query(DiscoveryRun).order_by(DiscoveryRun.id.desc()).limit(10).all()
    return {
        "enabled": ENABLED, "running": _state["running"], "busy": _state["busy"],
        "provider": prov, "provider_name": PROVIDERS[prov][0] if prov else "",
        "demo": prov == "forum",
        "providers": [{"key": k, "name": v[0], "configured": v[2]()} for k, v in PROVIDERS.items() if k != "forum"],
        "budget": DAILY_BUDGET(), "used_today": used_today(s), "batch": BATCH(), "interval_min": INTERVAL_MIN(),
        "freshness": FRESHNESS(), "min_triage": MIN_TRIAGE(),
        "queries": total_q, "rotation_days": round(total_q / per_day, 1) if per_day else None,
        "next_run": _state["next_run"].isoformat() if _state["next_run"] else None,
        "districts": districts(), "last_error": _state["last_error"],
        "runs": [{"id": r.id, "started_at": r.started_at.isoformat(), "provider": r.provider, "trigger": r.trigger,
                  "queries": r.queries, "results": r.results, "new_hits": r.new_hits, "flagged": r.flagged,
                  "error": r.error, "done": bool(r.finished_at)} for r in runs],
    }


def coverage(s) -> dict:
    hits = s.query(DiscoveryHit).all()
    posts = {p.id: p for p in s.query(Post).filter(Post.id.in_([h.post_id for h in hits if h.post_id])).all()} if hits else {}
    by_d = {d: {"district": d, "hits": 0, "cases": 0, "flagged": 0, "last": None} for d in districts()}
    plat = Counter()
    for h in hits:
        d = by_d.setdefault(h.district or "", {"district": h.district or "", "hits": 0, "cases": 0, "flagged": 0, "last": None})
        d["hits"] += 1
        plat[h.platform] += 1
        p = posts.get(h.post_id)
        if p and h.status in ("case", "existing"):
            d["cases"] += 1
            if LEVEL_RANK.get(p.risk_level, 0) >= LEVEL_RANK["High"]:
                d["flagged"] += 1
                if not d["last"] or h.found_at.isoformat() > d["last"]:
                    d["last"] = h.found_at.isoformat()
    qd = Counter(q.district for q in s.query(DiscoveryQuery).filter(DiscoveryQuery.last_run.isnot(None)).all())
    for d in by_d.values():
        d["searched"] = qd.get(d["district"], 0)
    return {"districts": list(by_d.values()), "platforms": plat.most_common(),
            "totals": {"hits": len(hits), "cases": sum(1 for h in hits if h.status in ("case", "existing")),
                       "flagged": sum(d["flagged"] for d in by_d.values())}}
