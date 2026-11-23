"""Charcha — a small public community forum used as the live monitoring target for MuleWatch.

Reddit-style: communities, posts with text / link / image, votes, comments, login & register.
Every post page publishes schema.org DiscussionForumPosting JSON-LD (like real forums do for
search engines) — that's what the MuleWatch crawler reads.

Run:  uvicorn forum_app:app --host 0.0.0.0 --port 8100
"""
import hashlib
import json
import os
import secrets
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE = Path(__file__).parent
DATA = Path(os.getenv("FORUM_DATA_DIR", BASE / "data"))
UPLOADS = DATA / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA / "charcha.db"
MOD_TOKEN = os.getenv("FORUM_MOD_TOKEN", "")  # no default: moderation API is off until a token is set
SITE_NAME = os.getenv("FORUM_NAME", "Charcha")

app = FastAPI(title="Charcha forum", docs_url=None, redoc_url=None)


@app.middleware("http")
async def no_index(request, call_next):
    # public demo: keep every page, API response and file out of search engines
    response = await call_next(request)
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOADS), name="uploads")
templates = Jinja2Templates(directory=BASE / "templates")

COMMUNITIES = [
    ("JaipurBazaar", "Buy, sell & rent anything in Jaipur", "🛒"),
    ("PaisaTalk", "Banking, savings, loans & personal finance", "💰"),
    ("NaukriAlerts", "Jobs, internships & gigs", "💼"),
    ("CampusCorner", "College life, exams, events & notes", "🎓"),
    ("GamingAdda", "Mobile & PC gaming, tournaments", "🎮"),
    ("CryptoDesi", "Crypto, trading & P2P", "🪙"),
]


# ----------------------------------------------------------------------------- db helpers

def db():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, pw TEXT,
            joined TEXT, karma INTEGER DEFAULT 1, avatar TEXT);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER, created TEXT);
        CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY, user_id INTEGER, community TEXT,
            title TEXT, body TEXT, link TEXT, image TEXT, created TEXT, score INTEGER DEFAULT 1,
            flagged INTEGER DEFAULT 0, flag_case TEXT, flag_reason TEXT, flagged_at TEXT);
        CREATE TABLE IF NOT EXISTS comments(id INTEGER PRIMARY KEY, post_id INTEGER, user_id INTEGER,
            body TEXT, created TEXT, flagged INTEGER DEFAULT 0, flag_case TEXT);
        CREATE TABLE IF NOT EXISTS votes(post_id INTEGER, user_id INTEGER, v INTEGER, PRIMARY KEY(post_id, user_id));
        """)
        cols = {r[1] for r in c.execute("PRAGMA table_info(comments)")}
        if "flagged" not in cols:          # databases created before comment moderation existed
            c.execute("ALTER TABLE comments ADD COLUMN flagged INTEGER DEFAULT 0")
            c.execute("ALTER TABLE comments ADD COLUMN flag_case TEXT")


def hash_pw(pw: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(8)
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120_000).hex()


def check_pw(pw: str, stored: str) -> bool:
    salt = stored.split("$", 1)[0]
    return secrets.compare_digest(hash_pw(pw, salt), stored)


AVATAR_COLORS = ["#f97316", "#0ea5e9", "#22c55e", "#a855f7", "#ef4444", "#eab308", "#14b8a6", "#ec4899"]


def create_user(c, username: str, pw: str, joined: Optional[str] = None) -> int:
    color = AVATAR_COLORS[int(hashlib.md5(username.encode()).hexdigest(), 16) % len(AVATAR_COLORS)]
    cur = c.execute("INSERT INTO users(username,pw,joined,avatar) VALUES(?,?,?,?)",
                    (username, hash_pw(pw), joined or datetime.utcnow().isoformat(), color))
    return cur.lastrowid


def current_user(request: Request):
    tok = request.cookies.get("charcha_session")
    if not tok:
        return None
    with db() as c:
        return c.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?",
                         (tok,)).fetchone()


def ago(iso: str) -> str:
    try:
        d = datetime.utcnow() - datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return ""
    s = int(d.total_seconds())
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


templates.env.filters["ago"] = ago
templates.env.globals["SITE_NAME"] = SITE_NAME
templates.env.globals["COMMUNITIES"] = COMMUNITIES


POST_SQL = """SELECT p.*, u.username, u.avatar,
    (SELECT COUNT(*) FROM comments c WHERE c.post_id=p.id) AS ncomments
    FROM posts p JOIN users u ON u.id=p.user_id"""


def hot_rank(p) -> float:
    age_h = (datetime.utcnow() - datetime.fromisoformat(p["created"])).total_seconds() / 3600
    return (p["score"] + 2 * p["ncomments"]) / (age_h + 2) ** 1.5


def render(request, name, **ctx):
    ctx.setdefault("user", current_user(request))
    return templates.TemplateResponse(request, name, ctx)


# ----------------------------------------------------------------------------- pages

@app.on_event("startup")
def _startup():
    init_db()


def _listing(request, where="", args=(), sort="hot", title=None, community=None):
    with db() as c:
        rows = c.execute(f"{POST_SQL} {where} ORDER BY p.id DESC LIMIT 200", args).fetchall()
        my_votes = {}
        u = current_user(request)
        if u:
            my_votes = {r["post_id"]: r["v"] for r in c.execute("SELECT post_id, v FROM votes WHERE user_id=?", (u["id"],))}
    if sort == "hot":
        rows = sorted(rows, key=hot_rank, reverse=True)
    elif sort == "top":
        rows = sorted(rows, key=lambda p: p["score"], reverse=True)
    return render(request, "listing.html", posts=rows, sort=sort, title=title, community=community, my_votes=my_votes)


@app.get("/", response_class=HTMLResponse)
def home(request: Request, sort: str = "hot"):
    return _listing(request, sort=sort)


@app.get("/new", response_class=HTMLResponse)
def new(request: Request):
    return _listing(request, sort="new")


@app.get("/c/{name}", response_class=HTMLResponse)
def community(request: Request, name: str, sort: str = "hot"):
    comm = next((c for c in COMMUNITIES if c[0].lower() == name.lower()), None)
    if not comm:
        raise HTTPException(404)
    return _listing(request, "WHERE p.community=?", (comm[0],), sort, community=comm)


@app.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = ""):
    like = f"%{q}%"
    return _listing(request, "WHERE p.title LIKE ? OR p.body LIKE ?", (like, like), "new", title=f"Results for “{q}”")


@app.get("/u/{username}", response_class=HTMLResponse)
def profile(request: Request, username: str):
    with db() as c:
        prof = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not prof:
            raise HTTPException(404)
        posts = c.execute(f"{POST_SQL} WHERE p.user_id=? ORDER BY p.id DESC", (prof["id"],)).fetchall()
    return render(request, "profile.html", prof=prof, posts=posts)


@app.get("/p/{pid}", response_class=HTMLResponse)
def post_page(request: Request, pid: int):
    with db() as c:
        p = c.execute(f"{POST_SQL} WHERE p.id=?", (pid,)).fetchone()
        if not p:
            raise HTTPException(404)
        comments = c.execute("""SELECT c.*, u.username, u.avatar FROM comments c JOIN users u ON u.id=c.user_id
                                WHERE post_id=? ORDER BY c.id""", (pid,)).fetchall()
    base = str(request.base_url).rstrip("/")
    ld = {
        "@context": "https://schema.org", "@type": "DiscussionForumPosting",
        "identifier": p["id"], "url": f"{base}/p/{p['id']}", "headline": p["title"], "text": p["body"] or "",
        "datePublished": p["created"] + "Z", "author": {"@type": "Person", "name": p["username"],
                                                       "url": f"{base}/u/{p['username']}"},
        "isPartOf": {"@type": "WebPage", "name": "c/" + p["community"], "url": f"{base}/c/{p['community']}"},
        "interactionStatistic": [{"@type": "InteractionCounter", "interactionType": "https://schema.org/LikeAction",
                                  "userInteractionCount": p["score"]},
                                 {"@type": "InteractionCounter", "interactionType": "https://schema.org/CommentAction",
                                  "userInteractionCount": p["ncomments"]}],
    }
    if comments:
        ld["comment"] = [{"@type": "Comment", "identifier": cm["id"], "url": f"{base}/p/{p['id']}#c{cm['id']}",
                          "text": cm["body"], "dateCreated": cm["created"] + "Z",
                          "author": {"@type": "Person", "name": cm["username"]}} for cm in comments]
    if p["link"]:
        ld["sharedContent"] = {"@type": "WebPage", "url": p["link"]}
    if p["image"]:
        ld["image"] = f"/uploads/{p['image']}"
    ld_json = json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")
    return render(request, "post.html", p=p, comments=comments, ld_json=ld_json)


# ----------------------------------------------------------------------------- auth

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/", error: str = ""):
    return render(request, "auth.html", mode="login", next=next, error=error)


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request, next: str = "/", error: str = ""):
    return render(request, "auth.html", mode="register", next=next, error=error)


def _start_session(user_id: int, next_url: str):
    tok = secrets.token_urlsafe(24)
    with db() as c:
        c.execute("INSERT INTO sessions VALUES(?,?,?)", (tok, user_id, datetime.utcnow().isoformat()))
    safe = next_url.startswith("/") and not next_url.startswith(("//", "/\\"))   # no open redirect
    r = RedirectResponse(next_url if safe else "/", status_code=303)
    r.set_cookie("charcha_session", tok, httponly=True, samesite="lax", max_age=7 * 86400)
    return r


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...), next: str = Form("/")):
    with db() as c:
        u = c.execute("SELECT * FROM users WHERE username=?", (username.strip(),)).fetchone()
    if not u or not check_pw(password, u["pw"]):
        return RedirectResponse(f"/login?error=Wrong+username+or+password&next={next}", status_code=303)
    return _start_session(u["id"], next)


@app.post("/register")
def register(username: str = Form(...), password: str = Form(...), next: str = Form("/")):
    username = username.strip()
    if not (3 <= len(username) <= 24) or not username.replace("_", "").isalnum():
        return RedirectResponse("/register?error=Username+must+be+3-24+letters,+digits+or+_", status_code=303)
    if len(password) < 6:
        return RedirectResponse("/register?error=Password+must+be+at+least+6+characters", status_code=303)
    try:
        with db() as c:
            uid = create_user(c, username, password)
    except sqlite3.IntegrityError:
        return RedirectResponse("/register?error=Username+already+taken", status_code=303)
    return _start_session(uid, next)


@app.get("/logout")
def logout(request: Request):
    tok = request.cookies.get("charcha_session")
    if tok:
        with db() as c:
            c.execute("DELETE FROM sessions WHERE token=?", (tok,))
    r = RedirectResponse("/", status_code=303)
    r.delete_cookie("charcha_session")
    return r


# ----------------------------------------------------------------------------- posting

@app.get("/submit", response_class=HTMLResponse)
def submit_page(request: Request, c: str = ""):
    if not current_user(request):
        return RedirectResponse("/login?next=/submit", status_code=303)
    return render(request, "submit.html", preselect=c)


ALLOWED_IMG = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


@app.post("/submit")
async def submit(request: Request, title: str = Form(...), community: str = Form(...), body: str = Form(""),
                 link: str = Form(""), image: Optional[UploadFile] = File(None)):
    u = current_user(request)
    if not u:
        return RedirectResponse("/login?next=/submit", status_code=303)
    if community not in [c[0] for c in COMMUNITIES]:
        raise HTTPException(400, "Unknown community")
    img_name = ""
    if image is not None and image.filename:
        ext = Path(image.filename).suffix.lower()
        if ext not in ALLOWED_IMG:
            raise HTTPException(400, "Only PNG/JPG/WEBP/GIF images")
        data = await image.read()
        if len(data) > 6 * 1024 * 1024:
            raise HTTPException(413, "Image too large (max 6 MB)")
        img_name = f"{uuid.uuid4().hex[:12]}{ext}"
        (UPLOADS / img_name).write_bytes(data)
    link = link.strip()
    if link and not link.startswith(("http://", "https://")):
        link = "https://" + link
    with db() as c:
        cur = c.execute("INSERT INTO posts(user_id,community,title,body,link,image,created) VALUES(?,?,?,?,?,?,?)",
                        (u["id"], community, title.strip()[:300], body.strip()[:10000], link[:500], img_name,
                         datetime.utcnow().isoformat()))
        c.execute("INSERT OR REPLACE INTO votes VALUES(?,?,1)", (cur.lastrowid, u["id"]))
    return RedirectResponse(f"/p/{cur.lastrowid}", status_code=303)


@app.post("/p/{pid}/comment")
def comment(request: Request, pid: int, body: str = Form(...)):
    u = current_user(request)
    if not u:
        return RedirectResponse(f"/login?next=/p/{pid}", status_code=303)
    if body.strip():
        with db() as c:
            c.execute("INSERT INTO comments(post_id,user_id,body,created) VALUES(?,?,?,?)",
                      (pid, u["id"], body.strip()[:3000], datetime.utcnow().isoformat()))
    return RedirectResponse(f"/p/{pid}#comments", status_code=303)


@app.post("/p/{pid}/vote")
def vote(request: Request, pid: int, v: int = Form(...)):
    u = current_user(request)
    if not u:
        return JSONResponse({"error": "login"}, status_code=401)
    v = max(-1, min(1, v))
    with db() as c:
        old = c.execute("SELECT v FROM votes WHERE post_id=? AND user_id=?", (pid, u["id"])).fetchone()
        old_v = old["v"] if old else 0
        new_v = 0 if old_v == v else v
        c.execute("INSERT OR REPLACE INTO votes VALUES(?,?,?)", (pid, u["id"], new_v))
        c.execute("UPDATE posts SET score=score+? WHERE id=?", (new_v - old_v, pid))
        score = c.execute("SELECT score FROM posts WHERE id=?", (pid,)).fetchone()["score"]
    return {"score": score, "mine": new_v}


# ----------------------------------------------------------------------------- moderation API (used by MuleWatch)

@app.post("/api/moderation/flag/{pid}")
async def flag(pid: int, request: Request, x_mod_token: str = Header("")):
    if not MOD_TOKEN or not secrets.compare_digest(x_mod_token, MOD_TOKEN):
        raise HTTPException(403, "bad moderation token")
    data = {}
    try:
        data = await request.json()
    except Exception:
        pass
    with db() as c:
        cur = c.execute("UPDATE posts SET flagged=1, flag_case=?, flag_reason=?, flagged_at=? WHERE id=?",
                        (str(data.get("case", ""))[:40], str(data.get("reason", ""))[:120],
                         datetime.utcnow().isoformat(), pid))
        if not cur.rowcount:
            raise HTTPException(404)
    return {"ok": True, "post": pid, "status": "under_review"}


@app.post("/api/moderation/flag-comment/{cid}")
async def flag_comment(cid: int, request: Request, x_mod_token: str = Header("")):
    if not MOD_TOKEN or not secrets.compare_digest(x_mod_token, MOD_TOKEN):
        raise HTTPException(403, "bad moderation token")
    data = {}
    try:
        data = await request.json()
    except Exception:
        pass
    with db() as c:
        cur = c.execute("UPDATE comments SET flagged=1, flag_case=? WHERE id=?", (str(data.get("case", ""))[:40], cid))
        if not cur.rowcount:
            raise HTTPException(404)
    return {"ok": True, "comment": cid, "status": "hidden_under_review"}


@app.post("/api/moderation/unflag/{pid}")
def unflag(pid: int, x_mod_token: str = Header("")):
    if not MOD_TOKEN or not secrets.compare_digest(x_mod_token, MOD_TOKEN):
        raise HTTPException(403)
    with db() as c:
        c.execute("UPDATE posts SET flagged=0 WHERE id=?", (pid,))
    return {"ok": True}


@app.get("/robots.txt", response_class=HTMLResponse)
def robots():
    # sandbox with synthetic scam ads — keep it out of search engines
    return HTMLResponse("User-agent: *\nDisallow: /\n", media_type="text/plain")
