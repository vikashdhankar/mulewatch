"""Keys, passwords, session tokens and field encryption.

Two secrets live in the data folder unless they are given in .env:
  * MW_SECRET     signs login sessions
  * MW_DATA_KEY   encrypts imported complaint data (Fernet) and keys the identifier hashes used for matching
Back up backend/data/keys/ together with the database: without MW_DATA_KEY the complaint data can't be read."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

import bcrypt
from cryptography.fernet import Fernet, InvalidToken

from .config import DATA_DIR

KEY_DIR = DATA_DIR / "keys"
SESSION_HOURS = float(os.getenv("SESSION_HOURS", "12"))


def _key_file(name: str, make) -> str:
    env = os.getenv(name, "").strip()
    if env:
        return env
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(KEY_DIR, 0o700)
    except OSError:
        pass
    path = KEY_DIR / name.lower()
    if not path.exists():
        path.write_text(make())
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return path.read_text().strip()


_secret_cache: dict[str, str] = {}


def _secret() -> bytes:
    if "s" not in _secret_cache:
        _secret_cache["s"] = _key_file("MW_SECRET", lambda: secrets.token_urlsafe(48))
    return _secret_cache["s"].encode()


def _data_key() -> str:
    if "d" not in _secret_cache:
        _secret_cache["d"] = _key_file("MW_DATA_KEY", lambda: Fernet.generate_key().decode())
    return _secret_cache["d"]


# ----------------------------------------------------------------------------- passwords

def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8")[:72], bcrypt.gensalt(rounds=12)).decode()


def check_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8")[:72], (hashed or "").encode())
    except ValueError:
        return False


def password_problem(pw: str) -> str:
    if len(pw) < 8:
        return "Use at least 8 characters."
    if pw.isdigit() or pw.isalpha():
        return "Mix letters with numbers or symbols."
    return ""


# ----------------------------------------------------------------------------- sessions

def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(user_id: int, version: int) -> str:
    body = _b64(json.dumps({"u": user_id, "v": version, "exp": int(time.time() + SESSION_HOURS * 3600)}).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(token: str) -> dict | None:
    try:
        body, sig = (token or "").split(".", 1)
        good = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        data = json.loads(_unb64(body))
        return data if data.get("exp", 0) > time.time() else None
    except (ValueError, json.JSONDecodeError):
        return None


# ----------------------------------------------------------------------------- complaint data

def encrypt(obj) -> str:
    return Fernet(_data_key().encode()).encrypt(json.dumps(obj, ensure_ascii=False).encode()).decode()


def decrypt(token: str):
    try:
        return json.loads(Fernet(_data_key().encode()).decrypt((token or "").encode()))
    except (InvalidToken, ValueError):
        return None


def ident_digest(kind: str, value: str) -> str:
    """Keyed hash of a normalised identifier. Complaints and cases are matched on these, so the
    identifiers in the complaint data never need to be decrypted to find a match."""
    key = hashlib.sha256(b"mulewatch-ident|" + _data_key().encode()).digest()
    return hmac.new(key, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()
