#!/usr/bin/env bash
# Start the MuleWatch command center (default http://localhost:8000)
#
#   ./run.sh                     monitor the forum set in .env (FORUM_URL)
#   ./run.sh --local-forum       also run the Charcha forum locally (offline backup demo)
#   ./run.sh --reset             wipe collected cases and start fresh
#   ./run.sh --port 8010         use another port for the command center
#   ./run.sh --forum-port 8110   use another port for the local forum
#   ./run.sh --lan               let other devices on the network open the command center
#                                (everyone signs in; the default is still this laptop only)
#
# If the default port is taken by another program, the next free port is used automatically.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"

LOCAL_FORUM=0; RESET=0; LAN=0; PORT="${MW_PORT:-}"; FPORT="${FORUM_PORT:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --local-forum) LOCAL_FORUM=1 ;;
    --reset) RESET=1 ;;
    --lan) LAN=1 ;;
    --port) PORT="$2"; shift ;;
    --port=*) PORT="${1#*=}" ;;
    --forum-port) FPORT="$2"; shift ;;
    --forum-port=*) FPORT="${1#*=}" ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1 (see ./run.sh --help)"; exit 1 ;;
  esac
  shift
done

[ -f .env ] || cp .env.example .env

if [ "$(uname)" = "Darwin" ]; then
  INSTALL_HINT="brew install python@3.12 tesseract tesseract-lang"
  # Homebrew paths (Apple silicon and Intel) come first so the old system python3 isn't picked
  export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
else
  INSTALL_HINT="sudo apt install -y python3 python3-venv tesseract-ocr tesseract-ocr-hin"
fi

PY="$(command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3.10 || command -v python3 || true)"
if [ -z "$PY" ] || ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "!! Python 3.10 or newer is needed (found: ${PY:-none} $("${PY:-false}" --version 2>&1 || true))."
  echo "   Install it with: $INSTALL_HINT"
  exit 1
fi

# Some Macs report an empty macOS version to Python (platform.mac_ver() == ""), which crashes pip's
# "truststore" certificate code. pip's legacy certificate handling avoids it.
if [ "$(uname)" = "Darwin" ] && ! "$PY" -c 'import platform, sys; sys.exit(0 if platform.mac_ver()[0] else 1)'; then
  echo "==> macOS version not visible to Python; using pip's legacy certificate mode"
  export PIP_USE_DEPRECATED=legacy-certs
fi

if [ ! -d .venv ]; then
  echo "==> Creating virtualenv"
  if ! "$PY" -m venv .venv; then
    # some Homebrew/Debian Pythons ship a broken ensurepip: build the venv without pip, then bootstrap pip
    echo "==> Retrying without ensurepip"
    rm -rf .venv
    "$PY" -m venv --without-pip .venv && curl -fsSL https://bootstrap.pypa.io/get-pip.py | .venv/bin/python - -q \
      || { rm -rf .venv; echo "!! Could not create the Python environment. Try: $INSTALL_HINT (or brew reinstall python@3.12), then run ./run.sh again"; exit 1; }
  fi
fi
# shellcheck disable=SC1091
source .venv/bin/activate
if [ ! -f .venv/.deps-ok ] || [ backend/requirements.txt -nt .venv/.deps-ok ]; then
  echo "==> Installing Python packages"
  pip install -q --upgrade pip
  pip install -q -r backend/requirements.txt -r forum/requirements.txt
  touch .venv/.deps-ok
fi

command -v tesseract >/dev/null || echo "!! Tesseract OCR not found — image text won't be read. Install: $INSTALL_HINT"

if [ ! -f frontend/dist/index.html ]; then
  if command -v npm >/dev/null; then
    echo "==> Building dashboard"
    (cd frontend && npm install --no-audit --no-fund && npm run build)
  else
    echo "!! npm not found and frontend/dist missing — install Node.js 18+"; exit 1
  fi
fi

port_free() { python -c "import socket,sys; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(('0.0.0.0', int(sys.argv[1])))" "$1" 2>/dev/null; }
who_uses() {
  local w; w="$(ss -ltnp 2>/dev/null | grep -E ":$1\b" | grep -o 'users:(("[^"]*' | cut -d'"' -f2 | head -1)"
  echo "${w:-another program}"
}
pick_port() {  # $1 = requested (explicit) port or empty, $2 = default, $3 = label
  local want="$1" def="$2" label="$3" p
  if [ -n "$want" ]; then
    port_free "$want" || { echo "!! Port $want is already in use ($(who_uses "$want")). Choose another with --port." >&2; exit 1; }
    echo "$want"; return
  fi
  p="$def"
  while ! port_free "$p"; do
    [ "$p" = "$def" ] && echo "==> Port $def is busy ($(who_uses "$def")); using the next free port for the $label" >&2
    p=$((p + 1))
  done
  echo "$p"
}

PORT="$(pick_port "$PORT" 8000 "command center")"

if [ "$RESET" = 1 ]; then
  echo "==> Resetting collected data"
  rm -rf backend/data
fi

PIDS=()
cleanup() { for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM

if [ "$LOCAL_FORUM" = 1 ]; then
  FPORT="$(pick_port "$FPORT" 8100 "forum")"
  echo "==> Starting local Charcha forum on http://localhost:$FPORT"
  [ -f forum/data/charcha.db ] || (cd forum && python seed_forum.py)
  (cd forum && FORUM_MOD_TOKEN="$(grep -E '^FORUM_MOD_TOKEN=' "$ROOT/.env" | cut -d= -f2-)" \
     uvicorn forum_app:app --host 0.0.0.0 --port "$FPORT" --log-level warning) &
  PIDS+=($!)
  export FORUM_URL="http://localhost:$FPORT"
  sleep 1
fi

export PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-http://localhost:$PORT}"
echo
echo "==> MuleWatch command center:  http://localhost:$PORT"
[ "$LOCAL_FORUM" = 1 ] && echo "==> Local Charcha forum:        http://localhost:$FPORT"
echo "    (Ctrl+C to stop)"
echo
cd backend
HOST=127.0.0.1; [ "$LAN" = 1 ] && HOST=0.0.0.0
uvicorn app.main:app --host "$HOST" --port "$PORT" --log-level warning &
PIDS+=($!)
wait
