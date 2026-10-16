"""Real-time collectors for publicly available content.

* ForumCrawler   — crawls a public forum's /new page and each post page, reading the
                   schema.org DiscussionForumPosting JSON-LD (the same structured data real
                   sites publish for search engines) and downloading attached images.
* TelegramPublic — reads public channel previews at https://t.me/s/<channel> (no login/API).

A background thread polls every enabled source every CRAWL_INTERVAL seconds."""
import hashlib
import html
import json
import os
import re
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import requests

from .config import MEDIA_DIR
from .db import Post, SessionLocal, Source
from .pipeline import ingest

CRAWL_INTERVAL = float(os.getenv("CRAWL_INTERVAL", "3"))
FORUM_URL = os.getenv("FORUM_URL", "http://localhost:8100")
MOD_TOKEN = os.getenv("FORUM_MOD_TOKEN", "skit-cybercell-2026")
UA = {"User-Agent": "MuleWatch-Crawler/1.0 (+research; hackathon demo)"}
MAX_IMAGE = 6 * 1024 * 1024

_status = {"running": False, "last_cycle": None, "new_last_cycle": 0, "errors": 0}


def status():
    return dict(_status)


def _get(url, **kw):
    return requests.get(url, headers=UA, timeout=8, **kw)


def _download_image(url: str, name: str) -> str:
    try:
        r = _get(url, stream=True)
        if not r.ok or not r.headers.get("content-type", "").startswith("image/"):
            return ""
        ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}.get(
            r.headers["content-type"].split(";")[0], ".img")
        data = b""
        for chunk in r.iter_content(65536):
            data += chunk
            if len(data) > MAX_IMAGE:
                return ""
        path = MEDIA_DIR / f"{name}{ext}"
        path.write_bytes(data)
        return path.name
    except requests.RequestException:
        return ""


def _parse_dt(s: str) -> datetime | None:
    """ISO time -> naive UTC (the DB stores UTC)."""
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None
    return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d


# ----------------------------------------------------------------------------- forum

def _forum_cards(listing_html: str) -> dict:
    """{post id: (fingerprint, comment count)} from a forum listing page. The fingerprint (author +
    title) tells posts apart when a reseeded forum reuses ids; the count tells us when to look for
    new comments."""
    cards = {}
    for block in re.findall(r'<article[^>]*data-post-id="\d+".*?</article>', listing_html, re.S):
        pid = re.search(r'data-post-id="(\d+)"', block).group(1)
        author = (re.search(r'href="/u/([^"]+)"', block) or [None, ""])[1]
        title = html.unescape((re.search(r'class="title"><a[^>]*>(.*?)</a>', block, re.S) or [None, ""])[1])
        n = re.search(r"(\d+) comments?\b", block)
        cards[pid] = (hashlib.sha1(f"{author}|{title}".encode()).hexdigest()[:12], int(n.group(1)) if n else 0)
    return cards


def crawl_forum(session, src: Source) -> int:
    """New posts and new comments. Each comment is scored as its own case, because sellers often
    hide their ads under ordinary posts."""
    base = src.url.rstrip("/")
    listing = _get(base + "/new")
    listing.raise_for_status()
    cards = _forum_cards(listing.text)
    known = {p.remote_id for p in session.query(Post.remote_id).filter(Post.source == "forum").all()}
    new = 0
    for pid, (fp, ncomments) in sorted(cards.items(), key=lambda kv: int(kv[0])):
        rid = f"{base}#{pid}#{fp}"
        legacy = f"{base}#{pid}"          # format used by earlier versions (id only)
        if rid not in known and legacy in known:
            old = session.query(Post).filter_by(source="forum", remote_id=legacy).first()
            if old:
                old.remote_id = rid
            known.add(rid)
        need_post = rid not in known
        seen_comments = sum(1 for k in known if k.startswith(rid + "#c"))
        if not need_post and ncomments <= seen_comments:
            continue
        page = _get(f"{base}/p/{pid}")
        if not page.ok:
            continue
        m = re.search(r'<script type="application/ld\+json">(.*?)</script>', page.text, re.S)
        if not m:
            continue
        d = json.loads(m.group(1))
        title = d.get("headline", "")
        community = d.get("isPartOf", {}).get("name", "") if isinstance(d.get("isPartOf"), dict) else ""
        platform = "Charcha forum" + (f" · {community}" if community else "")
        if need_post:
            body = d.get("text", "")
            link = d.get("sharedContent", {}).get("url", "") if isinstance(d.get("sharedContent"), dict) else ""
            text = "\n".join(x for x in (title, body, link) if x)
            image = ""
            if d.get("image"):
                image = _download_image(urljoin(base + "/", d["image"]), f"forum_{pid}_{fp}")
            p = ingest(session, text=text, platform=platform, author=(d.get("author") or {}).get("name", ""),
                       url=f"{base}/p/{pid}", image_path=image,
                       posted_at=_parse_dt(d.get("datePublished", "")), source="forum", recompute=False,
                       html=page.text)
            p.remote_id = rid
            known.add(rid)
            new += 1
        if ncomments and "comment" not in d:
            _status["comments_unsupported"] = True     # forum on the server is older than comment scanning
        for cm in d.get("comment") or []:
            crid = f"{rid}#c{cm.get('identifier')}"
            if crid in known or not (cm.get("text") or "").strip():
                continue
            c = ingest(session, text=cm["text"], platform=platform + " · comment",
                       author=(cm.get("author") or {}).get("name", ""),
                       url=cm.get("url") or f"{base}/p/{pid}#c{cm.get('identifier')}",
                       posted_at=_parse_dt(cm.get("dateCreated", "")), source="forum", recompute=False,
                       html=page.text)
            c.remote_id = crid
            c.reasons = (c.reasons or []) + [f"Posted as a comment on “{title[:80]}”"]
            known.add(crid)
            new += 1
    return new


# ----------------------------------------------------------------------------- telegram

def crawl_telegram(session, src: Source) -> int:
    channel = src.url.rstrip("/").split("/")[-1].lstrip("@")
    r = _get(f"https://t.me/s/{channel}")
    r.raise_for_status()
    known = {p.remote_id for p in session.query(Post.remote_id).filter(Post.source == "telegram").all()}
    new = 0
    for block in re.findall(r'(<div class="tgme_widget_message [^"]*"[^>]*data-post="[^"]+".*?)(?=<div class="tgme_widget_message_wrap|\Z)',
                            r.text, re.S):
        post_id = re.search(r'data-post="([^"]+)"', block).group(1)
        if post_id in known:
            continue
        tm = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, re.S)
        text = html.unescape(re.sub(r"<br\s*/?>", "\n", re.sub(r"<(?!br)[^>]+>", "", tm.group(1)))) if tm else ""
        img = re.search(r"tgme_widget_message_photo_wrap[^>]*background-image:url\('([^']+)'\)", block)
        image = _download_image(img.group(1), "tg_" + post_id.replace("/", "_")) if img else ""
        dt = re.search(r'<time datetime="([^"]+)"', block)
        if not text and not image:
            continue
        p = ingest(session, text=text, platform="Telegram", author="@" + channel, url=f"https://t.me/{post_id}",
               image_path=image, posted_at=_parse_dt(dt.group(1)) if dt else None, source="telegram", recompute=False,
               html=block)
        p.remote_id = post_id
        new += 1
    return new


# ----------------------------------------------------------------------------- single page

PAGE_INTERVAL = float(os.getenv("PAGE_INTERVAL", "60"))


def crawl_page(session, src: Source) -> int:
    """A single URL (an ad, a profile, a listing). Re-fetched every PAGE_INTERVAL seconds; a new case is
    created whenever its content changes."""
    from .fetcher import fetch_url
    f = fetch_url(src.url)
    if not f["text"] and not f["image_paths"]:
        raise RuntimeError(f["note"] or "no readable content")
    fp = hashlib.sha1((f["text"] + "|" + "|".join(f["image_paths"])).encode()).hexdigest()[:16]
    if fp == src.cursor:
        return 0
    imgs = f["image_paths"]
    p = ingest(session, text=f["text"], platform=f["platform"], author=f["author"], url=f["final_url"],
               image_path=imgs[0] if imgs else "", extra_images=imgs[1:], posted_at=_parse_dt(f["posted_at"]),
               source="page", recompute=False, html=f.get("html", ""))
    p.remote_id = f"{src.url}#{fp}"
    src.cursor = fp
    return 1


CRAWLERS = {"forum": crawl_forum, "telegram": crawl_telegram, "page": crawl_page}


def crawl_once() -> int:
    from .pipeline import recompute_all
    total, backfill = 0, False
    with SessionLocal() as s:
        for src in s.query(Source).filter_by(enabled=True).all():
            if src.kind == "page" and src.last_crawl and \
                    datetime.utcnow() - src.last_crawl < timedelta(seconds=PAGE_INTERVAL):
                continue            # single pages are polled gently, not every few seconds
            if src.items_seen == 0 and src.kind != "page":
                backfill = True     # first crawl of a source: don't spam Telegram with old posts
            try:
                n = CRAWLERS[src.kind](s, src)
                src.items_seen += n
                src.last_status = f"ok · {n} new" if n else "ok"
                total += n
                if src.kind == "forum" and _status.get("comments_unsupported"):
                    src.last_status += " · comments not readable: update the forum on the server"
            except Exception as e:
                src.last_status = f"error: {type(e).__name__}: {str(e)[:120]}"
                _status["errors"] += 1
            src.last_crawl = datetime.utcnow()
            s.commit()
        if total:
            recompute_all(s, alert=True, push=not backfill)
    _status["last_cycle"] = datetime.utcnow().isoformat()
    _status["new_last_cycle"] = total
    return total


def _loop():
    _status["running"] = True
    while _status["running"]:
        try:
            crawl_once()
        except Exception:
            traceback.print_exc()
        time.sleep(CRAWL_INTERVAL)


def start():
    if not _status["running"]:
        threading.Thread(target=_loop, daemon=True, name="crawler").start()


def ensure_default_sources():
    """The default forum source always follows FORUM_URL from .env."""
    with SessionLocal() as s:
        src = s.query(Source).filter_by(kind="forum", name="Charcha public forum").first()
        if not src:
            s.add(Source(kind="forum", name="Charcha public forum", url=FORUM_URL))
        elif src.url != FORUM_URL:
            src.url, src.last_status = FORUM_URL, "address changed"
        s.commit()


def request_takedown(post: Post) -> tuple[bool, str]:
    if post.source != "forum" or "#" not in (post.remote_id or ""):
        return False, "Takedown API is only wired for the Charcha forum in this demo."
    parts = post.remote_id.split("#")
    base, pid = parts[0], parts[1]
    try:
        # the forum may have been reseeded since capture: make sure this id is still the same post
        if len(parts) > 2 and (_forum_cards(_get(base + "/new").text).get(pid) or ("",))[0] != parts[2]:
            return False, "This post is no longer on the forum (the forum was reset), so there is nothing to take down."
        if len(parts) > 3 and parts[3].startswith("c"):          # a single comment
            r = requests.post(f"{base}/api/moderation/flag-comment/{parts[3][1:]}",
                              headers={"X-Mod-Token": MOD_TOKEN, **UA},
                              json={"case": f"MW-{post.id:05d}", "reason": post.category}, timeout=6)
            return r.ok, ("Comment hidden on the forum." if r.ok else r.text[:200])
        r = requests.post(f"{base}/api/moderation/flag/{pid}", headers={"X-Mod-Token": MOD_TOKEN, **UA},
                          json={"case": f"MW-{post.id:05d}", "reason": post.category}, timeout=6)
        return r.ok, r.text[:200]
    except requests.RequestException as e:
        return False, str(e)
