"""Fetch a single public URL (post, ad, profile page, Telegram post or direct image) and turn it into
text + images that the detection pipeline can score.

Order of preference for the post text:
  1. schema.org JSON-LD (DiscussionForumPosting, SocialMediaPosting, Product, ClassifiedAd, Article ...)
  2. Open Graph / Twitter card metadata (what link previews show)
  3. the page's main readable text (<article>, <main>, else <body>)
"""
import hashlib
import ipaddress
import json
import os
import re
import socket
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

from .config import MEDIA_DIR

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0 Safari/537.36 MuleWatch/1.0",
      "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8"}
MAX_PAGE = 3 * 1024 * 1024
MAX_IMAGE = 6 * 1024 * 1024
MAX_TEXT = 5000
POST_TYPES = {"discussionforumposting", "socialmediaposting", "posting", "blogposting", "article", "newsarticle",
              "product", "offer", "classifiedad", "comment", "question", "answer", "webpage", "itempage"}
PLATFORMS = {"facebook.com": "Facebook", "fb.com": "Facebook", "instagram.com": "Instagram", "x.com": "X",
             "twitter.com": "X", "t.me": "Telegram", "telegram.me": "Telegram", "olx.in": "OLX", "quikr.com": "Quikr",
             "youtube.com": "YouTube", "linkedin.com": "LinkedIn", "reddit.com": "Reddit", "whatsapp.com": "WhatsApp",
             "sharechat.com": "ShareChat", "kooapp.com": "Koo", "threads.net": "Threads"}


class FetchError(Exception):
    pass


# ----------------------------------------------------------------------------- safety

def _allowed_private_hosts() -> set[str]:
    hosts = set()
    for var in ("FORUM_URL",):
        h = urlparse(os.getenv(var, "")).hostname
        if h:
            hosts.add(h.lower())
    return hosts


def _check_host(url: str):
    """Refuse URLs that point into the local network (SSRF), except the configured demo forum."""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise FetchError("Only http:// and https:// links can be checked.")
    host = (p.hostname or "").lower()
    if not host:
        raise FetchError("That doesn't look like a web address.")
    if host in _allowed_private_hosts() or os.getenv("ALLOW_PRIVATE_URLS") == "1":
        return
    try:
        infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise FetchError(f"Couldn't find the website {host}. Check the address and the internet connection.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise FetchError(f"{host} points to a local or private network address, which isn't allowed.")


def _get(url: str, max_bytes: int, accept_image_only=False):
    """GET with manual redirects (each hop re-checked) and a size cap. Returns (final_url, content_type, bytes)."""
    for _ in range(5):
        _check_host(url)
        try:
            r = requests.get(url, headers=UA, timeout=12, stream=True, allow_redirects=False)
        except requests.RequestException as e:
            raise FetchError(f"Couldn't open the page: {type(e).__name__}")
        if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
            url = urljoin(url, r.headers.get("location", ""))
            r.close()
            continue
        if r.status_code >= 400:
            raise FetchError(f"The website answered {r.status_code}"
                             + (" (login required or blocked)" if r.status_code in (401, 403, 429) else "") + ".")
        ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
        if accept_image_only and not ctype.startswith("image/"):
            r.close()
            raise FetchError("not an image")
        data = b""
        for chunk in r.iter_content(65536):
            data += chunk
            if len(data) > max_bytes:
                r.close()
                if accept_image_only:
                    raise FetchError("image too large")
                break
        return url, ctype, data
    raise FetchError("Too many redirects.")


def _save_image(data: bytes, ctype: str, stem: str) -> str:
    ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif",
           "image/bmp": ".bmp"}.get(ctype)
    if not ext:
        return ""
    name = f"{stem}_{hashlib.sha1(data).hexdigest()[:10]}{ext}"
    (MEDIA_DIR / name).write_bytes(data)
    return name


def download_image(url: str, stem: str) -> str:
    try:
        _, ctype, data = _get(url, MAX_IMAGE, accept_image_only=True)
    except FetchError:
        return ""
    return _save_image(data, ctype, stem)


# ----------------------------------------------------------------------------- HTML parsing

class _Page(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "nav", "footer", "header", "form", "button", "select",
            "iframe", "head"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "blockquote", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta, self.ldjson, self.title, self.imgs = {}, [], "", []
        self.parts = {"body": [], "main": [], "article": []}
        self._skip, self._in = 0, {"main": 0, "article": 0}
        self._ld, self._ld_buf, self._title = False, [], False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content"):
                self.meta.setdefault(key, unescape(a["content"]))
        elif tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._ld, self._ld_buf = True, []
            return
        elif tag == "title":
            self._title = True
        elif tag == "img" and not self._skip:
            src = a.get("src") or a.get("data-src") or ""
            if src and not src.startswith("data:") and not re.search(r"logo|icon|avatar|sprite|emoji|\.svg", src, re.I):
                w = int(re.sub(r"\D", "", a.get("width", "")) or 0)
                if not w or w >= 200:
                    self.imgs.append((bool(self._in["article"] or self._in["main"]), src))
        if tag in self._in:
            self._in[tag] += 1
        if tag in self.SKIP:
            self._skip += 1
        if tag in self.BLOCK:
            self._add("\n")

    def handle_endtag(self, tag):
        if tag == "script" and self._ld:
            self._ld = False
            self.ldjson.append("".join(self._ld_buf))
        if tag == "title":
            self._title = False
        if tag in self._in and self._in[tag]:
            self._in[tag] -= 1
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag in self.BLOCK:
            self._add("\n")

    def handle_data(self, data):
        if self._ld:
            self._ld_buf.append(data)
        elif self._title:
            self.title += data
        elif not self._skip:
            self._add(data)

    def _add(self, s):
        self.parts["body"].append(s)
        if self._in["main"]:
            self.parts["main"].append(s)
        if self._in["article"]:
            self.parts["article"].append(s)

    def text(self, which):
        t = "".join(self.parts[which])
        lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in t.splitlines()]
        out, seen = [], set()
        for ln in lines:
            if len(ln) < 2 or ln in seen:
                continue
            seen.add(ln)
            out.append(ln)
        return "\n".join(out)


def _ld_items(raw: str):
    try:
        d = json.loads(raw.strip())
    except (ValueError, TypeError):
        return []
    stack, out = [d], []
    while stack:
        x = stack.pop()
        if isinstance(x, list):
            stack.extend(x)
        elif isinstance(x, dict):
            if "@graph" in x:
                stack.append(x["@graph"])
            out.append(x)
    return out


def _name(v):
    if isinstance(v, list):
        v = v[0] if v else ""
    if isinstance(v, dict):
        return str(v.get("name") or v.get("alternateName") or "")
    return str(v or "")


def _img_url(v):
    if isinstance(v, list):
        v = v[0] if v else ""
    if isinstance(v, dict):
        v = v.get("url") or v.get("contentUrl") or ""
    return str(v or "")


def platform_for(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.").removeprefix("m.")
    for dom, name in PLATFORMS.items():
        if host == dom or host.endswith("." + dom):
            return name
    return host or "Web page"


# ----------------------------------------------------------------------------- telegram single post

def _telegram_post(url: str):
    m = re.match(r"https?://(?:t|telegram)\.me/(?:s/)?([A-Za-z0-9_]{4,})/(\d+)", url)
    if not m:
        return None
    ch, mid = m.groups()
    _, _, data = _get(f"https://t.me/{ch}/{mid}?embed=1&mode=tme", MAX_PAGE)
    page = data.decode("utf-8", "replace")
    tm = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', page, re.S)
    text = unescape(re.sub(r"<[^>]+>", "", re.sub(r"<br\s*/?>", "\n", tm.group(1)))) if tm else ""
    img = re.search(r"tgme_widget_message_photo_wrap[^>]*background-image:url\('([^']+)'\)", page)
    owner = re.search(r'tgme_widget_message_owner_name"[^>]*>(?:<span[^>]*>)?([^<]+)', page)
    dt = re.search(r'<time datetime="([^"]+)"', page)
    return {"title": "", "text": text.strip(), "author": "@" + ch + (f" ({unescape(owner.group(1))})" if owner else ""),
            "images": [img.group(1)] if img else [], "posted_at": dt.group(1) if dt else "", "platform": "Telegram",
            "how": "Telegram public post preview", "html": page}


# ----------------------------------------------------------------------------- main entry

def fetch_url(url: str) -> dict:
    """Returns {url, final_url, platform, author, title, text, image_paths, posted_at, how, note}."""
    url = (url or "").strip()
    if not url:
        raise FetchError("Paste a link to check.")
    guessed = not re.match(r"^[a-z]+://", url, re.I)
    if guessed:
        url = "https://" + url
    note = ""

    tg = _telegram_post(url)
    if tg:
        final, info = url, tg
    else:
        try:
            final, ctype, data = _get(url, MAX_PAGE)
        except FetchError as e:
            if not (guessed and "Couldn't open" in str(e)):
                raise
            url = "http://" + url[len("https://"):]       # no scheme given and https failed: try http
            final, ctype, data = _get(url, MAX_PAGE)
        if ctype.startswith("image/"):
            name = _save_image(data, ctype, "url")
            if not name:
                raise FetchError(f"Unsupported image type {ctype}.")
            return {"url": url, "final_url": final, "platform": platform_for(final), "author": "", "title": "",
                    "text": "", "image_paths": [name], "posted_at": "", "how": "Direct image link (text read by OCR)",
                    "note": "", "html": ""}
        if "html" not in ctype and "xml" not in ctype and ctype:
            raise FetchError(f"That link is a {ctype or 'file'}, not a web page or image.")
        page = _Page()
        raw_html = data.decode("utf-8", "replace")
        try:
            page.feed(raw_html)
        except Exception:
            pass
        info = _from_page(page, final)
        info["html"] = raw_html

    lines = [ln.strip() for x in (info["title"], info["text"]) if x for ln in x.splitlines() if ln.strip()]
    text = "\n".join(dict.fromkeys(lines))[:MAX_TEXT]          # title is often repeated in the body
    images, seen = [], set()
    for src in info["images"]:
        full = urljoin(final, src)
        if full in seen:
            continue
        seen.add(full)
        name = download_image(full, "url")
        if name:
            images.append(name)
        if len(images) >= 3:
            break
    if len(text) < 40 and not images:
        note = ("The page returned almost no readable content. It may need a login (Facebook, Instagram and "
                "WhatsApp often do). Paste the post text or a screenshot instead, or use the Chrome extension "
                "while logged in.")
    return {"url": url, "final_url": final, "platform": info.get("platform") or platform_for(final),
            "author": info["author"], "title": info["title"], "text": text, "image_paths": images,
            "posted_at": info["posted_at"], "how": info["how"], "note": note, "html": info.get("html", "")}


def _from_page(page: _Page, final: str) -> dict:
    meta = page.meta
    best = None
    for raw in page.ldjson:
        for item in _ld_items(raw):
            types = item.get("@type", "")
            types = {t.lower() for t in (types if isinstance(types, list) else [types]) if isinstance(t, str)}
            if types & POST_TYPES:
                body = item.get("articleBody") or item.get("text") or item.get("description") or ""
                if body or item.get("headline") or item.get("name"):
                    score = 2 if types & {"discussionforumposting", "socialmediaposting", "classifiedad", "product"} else 1
                    if not best or score > best[0]:
                        best = (score, item)
    images = []
    if best:
        it = best[1]
        shared = it.get("sharedContent")
        link = shared.get("url", "") if isinstance(shared, dict) else ""
        text = "\n".join(x for x in (str(it.get("articleBody") or it.get("text") or it.get("description") or ""), link) if x)
        if _img_url(it.get("image")):
            images.append(_img_url(it.get("image")))
        info = {"title": str(it.get("headline") or it.get("name") or ""), "text": unescape(text),
                "author": _name(it.get("author") or it.get("seller") or it.get("creator")),
                "posted_at": str(it.get("datePublished") or it.get("dateCreated") or ""),
                "how": "Structured data published by the page (schema.org)"}
    else:
        og_title = meta.get("og:title") or meta.get("twitter:title") or page.title.strip()
        og_desc = meta.get("og:description") or meta.get("twitter:description") or meta.get("description") or ""
        main = page.text("article") or page.text("main")
        body = main or page.text("body")
        # keep the meta description first (it's what the poster wrote on most social sites)
        text = "\n".join(x for x in (og_desc, body[:MAX_TEXT]) if x)
        info = {"title": og_title.strip(), "text": text,
                "author": meta.get("author") or meta.get("article:author") or meta.get("twitter:creator") or "",
                "posted_at": meta.get("article:published_time", ""),
                "how": "Page content" + (" and link-preview metadata" if og_desc else "")}
    for key in ("og:image", "og:image:url", "twitter:image", "twitter:image:src"):
        if meta.get(key):
            images.append(meta[key])
    images += [src for in_main, src in page.imgs if in_main][:3] or [src for _, src in page.imgs][:2]
    info["images"] = images
    return info
