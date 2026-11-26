"""Central configuration. Everything is overridable through environment variables (.env)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
ROOT_DIR = BASE_DIR.parent                                 # repo root
DATA_DIR = Path(os.getenv("MW_DATA_DIR", BASE_DIR / "data"))
MEDIA_DIR = DATA_DIR / "media"
DATA_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)


def _load_dotenv():
    """Tiny .env loader so we don't need python-dotenv."""
    for p in (ROOT_DIR / ".env", BASE_DIR / ".env"):
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def _origin(url: str):
    from urllib.parse import urlparse
    p = urlparse(url or "")
    if p.scheme not in ("http", "https") or not p.hostname:
        return None
    return p.scheme, p.hostname.lower(), p.port or (443 if p.scheme == "https" else 80)


def _parse_headers(raw: str) -> dict:
    """FORUM_HEADERS: a JSON object, or 'Name: value; Name: value'."""
    import json
    raw = (raw or "").strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        try:
            return {str(k): str(v) for k, v in json.loads(raw).items()}
        except (ValueError, AttributeError):
            return {}
    out = {}
    for part in raw.split(";"):
        name, sep, value = part.partition(":")
        if sep and name.strip() and value.strip():
            out[name.strip()] = value.strip()
    return out


def forum_headers(url: str) -> dict:
    """Extra headers for requests to the configured forum (e.g. a Cloudflare Access service token:
    CF-Access-Client-Id / CF-Access-Client-Secret). Sent only when url has exactly the same scheme, host and
    port as FORUM_URL, so the secret never goes to any other site or over plain http to an https forum."""
    forum = _origin(os.getenv("FORUM_URL", ""))
    if not forum or _origin(url) != forum:
        return {}
    return _parse_headers(os.getenv("FORUM_HEADERS", ""))

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'mulewatch.db'}")

# Alerts
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
ALERT_MIN_LEVEL = os.getenv("ALERT_MIN_LEVEL", "Critical")   # Critical | High

# Citizen reporting bot (Telegram). Falls back to the alert bot's token when not set.
REPORT_BOT_TOKEN = os.getenv("REPORT_BOT_TOKEN", "") or TELEGRAM_BOT_TOKEN
REPORTS_PER_HOUR = int(os.getenv("REPORTS_PER_HOUR", "30"))

# Optional LLM second opinion (Claude). Leave empty to run fully offline.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-haiku-5-5")

# Risk level thresholds (score 0-100)
LEVELS = [(80, "Critical"), (55, "High"), (30, "Medium"), (0, "Low")]


def level_for(score: float) -> str:
    for threshold, name in LEVELS:
        if score >= threshold:
            return name
    return "Low"


LEVEL_RANK = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}
