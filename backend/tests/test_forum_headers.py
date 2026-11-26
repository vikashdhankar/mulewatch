"""FORUM_HEADERS (e.g. a Cloudflare Access service token) go to the configured forum and nowhere else.
Also: the forum answers HEAD (curl -I) with 200.   cd backend && python -m pytest -q tests/test_forum_headers.py"""
import importlib
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("MW_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crawler  # noqa: E402
from app.config import _parse_headers, forum_headers  # noqa: E402

FORUM = "https://charcha.example.in"
CF = '{"CF-Access-Client-Id": "id.access", "CF-Access-Client-Secret": "s3cret"}'


def test_parse_headers_formats():
    assert _parse_headers(CF) == {"CF-Access-Client-Id": "id.access", "CF-Access-Client-Secret": "s3cret"}
    assert _parse_headers("CF-Access-Client-Id: id.access; CF-Access-Client-Secret: s3cret") == \
        {"CF-Access-Client-Id": "id.access", "CF-Access-Client-Secret": "s3cret"}
    assert _parse_headers("") == {} and _parse_headers("{broken") == {} and _parse_headers("no-colon") == {}


def test_headers_only_for_the_forum_origin(monkeypatch):
    monkeypatch.setenv("FORUM_URL", FORUM)
    monkeypatch.setenv("FORUM_HEADERS", CF)
    for same in (FORUM, FORUM + "/new", FORUM + ":443/p/3", "https://CHARCHA.example.in/uploads/a.png"):
        assert forum_headers(same)["CF-Access-Client-Secret"] == "s3cret", same
    for other in ("http://charcha.example.in/new",          # plain http: never send the secret
                  "https://charcha.example.in:8443/",       # other port
                  "https://evil.charcha.example.in/",       # subdomain
                  "https://charcha.example.in.evil.com/",
                  "https://t.me/s/channel", "", "not a url"):
        assert forum_headers(other) == {}, other
    monkeypatch.delenv("FORUM_HEADERS")
    assert forum_headers(FORUM) == {}


def _capture(monkeypatch, status=200, url=None):
    calls = []

    def fake(method):
        def call(u, **kw):
            calls.append((method, u, kw))
            return SimpleNamespace(status_code=status, ok=status < 400, text="", url=url or u,
                                   is_redirect=status in (301, 302, 303, 307, 308), raise_for_status=lambda: None)
        return call
    monkeypatch.setattr(crawler.requests, "get", fake("GET"))
    monkeypatch.setattr(crawler.requests, "post", fake("POST"))
    return calls


def test_crawler_sends_headers_to_forum_only_and_no_redirects(monkeypatch):
    monkeypatch.setenv("FORUM_URL", FORUM)
    monkeypatch.setenv("FORUM_HEADERS", CF)
    calls = _capture(monkeypatch)
    crawler._get(FORUM + "/new")
    crawler._get("https://t.me/s/somechannel")
    (_, _, kw_forum), (_, _, kw_tg) = calls
    assert kw_forum["headers"]["CF-Access-Client-Id"] == "id.access"
    assert kw_forum["allow_redirects"] is False                # a redirect can't carry the secret elsewhere
    assert "CF-Access-Client-Secret" not in kw_tg["headers"] and "allow_redirects" not in kw_tg


def test_takedown_uses_headers_and_a_302_is_not_success(monkeypatch):
    monkeypatch.setenv("FORUM_URL", FORUM)
    monkeypatch.setenv("FORUM_HEADERS", CF)
    monkeypatch.setattr(crawler, "MOD_TOKEN", "tok")
    post = SimpleNamespace(id=7, source="forum", remote_id=f"{FORUM}#12", category="mule")
    calls = _capture(monkeypatch)
    ok, _ = crawler.request_takedown(post)
    _, url, kw = calls[-1]
    assert ok and url == f"{FORUM}/api/moderation/flag/12"
    assert kw["headers"]["X-Mod-Token"] == "tok" and kw["headers"]["CF-Access-Client-Secret"] == "s3cret"
    _capture(monkeypatch, status=302)                          # e.g. Cloudflare Access refused the token
    assert crawler.request_takedown(post)[0] is False


def test_forum_behind_sign_in_page_is_an_error_not_ok(monkeypatch):
    monkeypatch.setenv("FORUM_URL", FORUM)
    monkeypatch.delenv("FORUM_HEADERS", raising=False)
    _capture(monkeypatch, url="https://team.cloudflareaccess.com/cdn-cgi/access/login/x")
    try:
        crawler.crawl_forum(None, SimpleNamespace(url=FORUM))
        raise AssertionError("should have raised")
    except RuntimeError as e:
        assert "FORUM_HEADERS" in str(e)


def test_forum_answers_head(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("FORUM_DATA_DIR", str(tmp_path))
    forum_dir = str(Path(__file__).resolve().parents[2] / "forum")
    monkeypatch.syspath_prepend(forum_dir)
    sys.modules.pop("forum_app", None)
    forum_app = importlib.import_module("forum_app")
    with TestClient(forum_app.app) as c:
        r = c.head("/robots.txt")
        assert r.status_code == 200 and r.content == b""
        assert r.headers["x-robots-tag"].startswith("noindex")
        assert c.get("/robots.txt").text == "User-agent: *\nDisallow: /\n"
    sys.modules.pop("forum_app", None)
