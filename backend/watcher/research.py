"""Access to the research pipeline's modules (research/ is a plain directory, not an installed package).

research/ is appended to sys.path, after the backend, so a research module never shadows a backend one."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "research"
BACKEND = ROOT / "backend"

for p in (BACKEND, RESEARCH):
    if str(p) not in sys.path:
        sys.path.append(str(p))

from common.io import load_env  # noqa: E402

load_env()          # research/.env: TELEGRAM_API_ID / _HASH, RESEARCH_HASH_SALT, LLM_BASE_URL
