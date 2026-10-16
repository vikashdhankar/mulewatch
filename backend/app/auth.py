"""Login, roles and user management.

Roles (each includes everything the one before it can do):
  ANALYST     triage: view cases, record verdicts, watchlist, check posts
  IO          Investigating Officer: case status, assignment to self, legal drafts, complaint data,
              evidence exports, complaint imports
  SUPERVISOR  SHO / SP: assign to anyone, users, audit log, daily brief, override any status
"""
import os
import secrets
import time
from datetime import datetime
from types import SimpleNamespace

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response

from . import audit
from .db import SessionLocal, User
from .security import check_password, hash_password, make_token, password_problem, read_token

ROLES = ["ANALYST", "IO", "SUPERVISOR"]
RANK = {r: i for i, r in enumerate(ROLES)}
COOKIE = "mw_session"
INGEST_KEY = os.getenv("MW_INGEST_KEY", "").strip()
DEMO_PASSWORD = "mule@2026"
DEMO_USERS = [
    ("analyst", "Cyber Analyst (demo)", "Data Analyst", "ANALYST"),
    ("io", "SI Demo Officer", "Sub-Inspector", "IO"),
    ("sho", "SHO Demo", "Station House Officer", "SUPERVISOR"),
]

# open without a login: the sign-in call itself and the single-page app's static files
PUBLIC_API = {"/api/auth/login", "/api/auth/logout", "/api/health"}
INGEST_PATHS = {"/api/analyze", "/api/analyze/url"}

router = APIRouter(prefix="/api/auth")
users_router = APIRouter(prefix="/api/users")


def ip_of(request: Request) -> str:
    return request.client.host if request.client else ""


def can(user, role: str) -> bool:
    return user is not None and RANK.get(user.role, -1) >= RANK[role]


def current_user(request: Request):
    u = getattr(request.state, "user", None)
    if u is None:
        raise HTTPException(401, "Sign in required")
    return u


def require(role: str):
    def dep(request: Request):
        u = current_user(request)
        if not can(u, role):
            raise HTTPException(403, f"This needs the {role.title() if role != 'IO' else 'Investigating Officer'} role")
        return u
    return dep


def public_user(u) -> dict:
    return {"id": u.id, "username": u.username, "name": u.name, "designation": u.designation,
            "police_station": u.police_station, "role": u.role, "active": u.active,
            "must_change_password": bool(getattr(u, "must_change_password", False)),
            "telegram_linked": bool(getattr(u, "telegram_chat_id", "")),
            "last_login": u.last_login.isoformat() if getattr(u, "last_login", None) else None}


def ensure_demo_users():
    """First start with an empty users table: create one demo account per role (unless MW_DEMO_USERS=0)."""
    if os.getenv("MW_DEMO_USERS", "1") == "0":
        return
    with SessionLocal() as s:
        if s.query(User).count():
            return
        for username, name, desig, role in DEMO_USERS:
            s.add(User(username=username, name=name, designation=desig, role=role,
                       police_station="Cyber Police Station, Jaipur", password_hash=hash_password(DEMO_PASSWORD)))
        s.commit()
    print(f"==> Created demo accounts analyst / io / sho (password {DEMO_PASSWORD}). Change them before real use.")


def demo_accounts_active() -> bool:
    with SessionLocal() as s:
        return any(check_password(DEMO_PASSWORD, u.password_hash)
                   for u in s.query(User).filter(User.username.in_([d[0] for d in DEMO_USERS]), User.active).all())


async def auth_middleware(request: Request, call_next):
    path = request.url.path
    request.state.user = None
    needs = path.startswith("/api/") or path.startswith("/media/")
    tok = read_token(request.cookies.get(COOKIE, ""))
    if tok:
        with SessionLocal() as s:
            u = s.get(User, tok["u"])
            if u and u.active and u.session_version == tok["v"]:
                request.state.user = u
    if request.state.user is None and path in INGEST_PATHS and INGEST_KEY and \
            secrets.compare_digest(request.headers.get("X-MW-Key", ""), INGEST_KEY):
        # the Chrome extension: may submit posts to check, nothing else
        request.state.user = SimpleNamespace(id=None, username="extension", name="Chrome extension",
                                             role="ANALYST", designation="", police_station="")
    if needs and path not in PUBLIC_API and request.state.user is None:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Sign in required"}, status_code=401)
    return await call_next(request)


# ----------------------------------------------------------------------------- sign in / out

_fails: dict[tuple, list] = {}      # (ip, username) -> [count, locked_until]


@router.post("/login")
def login(request: Request, response: Response, username: str = Body(...), password: str = Body(...)):
    key = (ip_of(request), username.strip().lower())
    cnt, until = _fails.get(key, [0, 0])
    if until > time.time():
        raise HTTPException(429, f"Too many attempts. Try again in {int(until - time.time()) + 1} s.")
    with SessionLocal() as s:
        u = s.query(User).filter(User.username == username.strip().lower()).first()
        if not u or not u.active or not check_password(password, u.password_hash):
            cnt += 1
            _fails[key] = [cnt, time.time() + 120 if cnt >= 5 else 0]
            audit.log({"id": u.id if u else None, "username": username[:60], "role": u.role if u else ""},
                      "login.failed", ip=ip_of(request))
            raise HTTPException(401, "Wrong username or password")
        _fails.pop(key, None)
        u.last_login = datetime.utcnow()
        s.commit()
        token = make_token(u.id, u.session_version)
        out = public_user(u)
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=secure, path="/",
                        max_age=int(float(os.getenv("SESSION_HOURS", "12")) * 3600))
    audit.log(u, "login", ip=ip_of(request))
    return out


@router.post("/logout")
def logout(request: Request, response: Response):
    u = getattr(request.state, "user", None)
    if u is not None and u.id:
        audit.log(u, "logout", ip=ip_of(request))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(u=Depends(current_user)):
    out = public_user(u)
    if u.role == "SUPERVISOR":
        out["demo_accounts_active"] = demo_accounts_active()
    return out


@router.post("/password")
def change_password(request: Request, old: str = Body(...), new: str = Body(...), u=Depends(current_user)):
    if not u.id:
        raise HTTPException(400)
    problem = password_problem(new)
    if problem:
        raise HTTPException(400, problem)
    with SessionLocal() as s:
        row = s.get(User, u.id)
        if not check_password(old, row.password_hash):
            raise HTTPException(400, "Current password is wrong")
        row.password_hash = hash_password(new)
        row.must_change_password = False
        s.commit()
    audit.log(u, "user.password_changed", ip=ip_of(request))
    return {"ok": True}


@router.post("/telegram-code")
def telegram_code(request: Request, u=Depends(current_user)):
    """One-time code the officer sends to the bot as /officer <code> to get alerts and the daily brief."""
    code = f"{secrets.randbelow(900000) + 100000}"
    with SessionLocal() as s:
        row = s.get(User, u.id)
        row.telegram_code = code
        s.commit()
    from . import reportbot
    return {"code": code, "bot": reportbot.status().get("username", "")}


@router.delete("/telegram")
def telegram_unlink(request: Request, u=Depends(current_user)):
    with SessionLocal() as s:
        row = s.get(User, u.id)
        row.telegram_chat_id, row.telegram_code = "", ""
        s.commit()
    audit.log(u, "user.telegram_unlinked", ip=ip_of(request))
    return {"ok": True}


# ----------------------------------------------------------------------------- user management (supervisors)

@users_router.get("")
def list_users(u=Depends(require("ANALYST"))):
    """Everyone can see the officer list (needed to show who a case is assigned to)."""
    with SessionLocal() as s:
        rows = s.query(User).order_by(User.role.desc(), User.name).all()
        if can(u, "SUPERVISOR"):
            return [public_user(x) for x in rows]
        return [{"id": x.id, "name": x.name, "username": x.username, "role": x.role, "designation": x.designation,
                 "active": x.active} for x in rows]


@users_router.post("")
def create_user(request: Request, username: str = Body(...), name: str = Body(...), role: str = Body(...),
                password: str = Body(...), designation: str = Body(""), police_station: str = Body(""),
                u=Depends(require("SUPERVISOR"))):
    username = username.strip().lower()
    if role not in ROLES:
        raise HTTPException(400, f"role must be one of {ROLES}")
    if not username.replace("_", "").replace(".", "").isalnum():
        raise HTTPException(400, "Username: letters, numbers, dot or underscore only")
    if password_problem(password):
        raise HTTPException(400, password_problem(password))
    with SessionLocal() as s:
        if s.query(User).filter_by(username=username).first():
            raise HTTPException(409, "That username is taken")
        row = User(username=username, name=name.strip(), role=role, designation=designation.strip(),
                   police_station=police_station.strip(), password_hash=hash_password(password),
                   must_change_password=True)
        s.add(row)
        s.commit()
        out = public_user(row)
    audit.log(u, "user.created", detail={"username": username, "role": role}, ip=ip_of(request))
    return out


@users_router.patch("/{uid}")
def update_user(uid: int, request: Request, data: dict = Body(...), u=Depends(require("SUPERVISOR"))):
    allowed = {"name", "designation", "police_station", "role", "active"}
    changes = {k: v for k, v in data.items() if k in allowed}
    if "role" in changes and changes["role"] not in ROLES:
        raise HTTPException(400, "Unknown role")
    with SessionLocal() as s:
        row = s.get(User, uid)
        if not row:
            raise HTTPException(404)
        if row.id == u.id and (changes.get("active") is False or changes.get("role", "SUPERVISOR") != "SUPERVISOR"):
            raise HTTPException(400, "You can't remove your own supervisor access")
        for k, v in changes.items():
            setattr(row, k, v)
        if "active" in changes or "role" in changes:
            row.session_version = (row.session_version or 1) + 1      # sign them out everywhere
        s.commit()
        out = public_user(row)
    audit.log(u, "user.updated", detail={"user": out["username"], **changes}, ip=ip_of(request))
    return out


@users_router.post("/{uid}/reset-password")
def reset_password(uid: int, request: Request, password: str = Body(..., embed=True),
                   u=Depends(require("SUPERVISOR"))):
    if password_problem(password):
        raise HTTPException(400, password_problem(password))
    with SessionLocal() as s:
        row = s.get(User, uid)
        if not row:
            raise HTTPException(404)
        row.password_hash = hash_password(password)
        row.must_change_password = True
        row.session_version = (row.session_version or 1) + 1
        s.commit()
        name = row.username
    audit.log(u, "user.password_reset", detail={"user": name}, ip=ip_of(request))
    return {"ok": True}
