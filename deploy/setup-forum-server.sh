#!/usr/bin/env bash
# One-command setup of the Charcha demo forum on a CyberPanel (or any Ubuntu/AlmaLinux) server.
#
#   1. Copy the forum folder to the server (from your laptop):
#        scp -r ~/Projects/mulewatch/forum ~/Projects/mulewatch/deploy root@103.174.103.46:/opt/charcha-src/
#   2. On the server:
#        sudo bash /opt/charcha-src/deploy/setup-forum-server.sh
#
# The forum runs as a systemd service on port 8100 (CyberPanel/OpenLiteSpeed keeps ports 80/443).
# Re-running the script updates the code and keeps the existing database unless RESEED=1.
set -euo pipefail

PORT="${PORT:-8100}"
APP_DIR=/opt/charcha
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# keep the token of an existing install, otherwise generate one
MOD_TOKEN="${FORUM_MOD_TOKEN:-$(grep -oP 'FORUM_MOD_TOKEN=\K\S+' /etc/systemd/system/charcha.service 2>/dev/null || openssl rand -hex 16)}"

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo/root"; exit 1; }
[ -f "$SRC_DIR/forum/forum_app.py" ] || { echo "forum/ folder not found next to deploy/ ($SRC_DIR)"; exit 1; }

echo "==> Checking Python"
PY=""
for c in python3.12 python3.11 python3.10 python3.9 python3.8 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)'; then PY="$(command -v $c)"; break; fi
done
if [ -z "$PY" ]; then
  echo "Installing Python 3..."
  if command -v apt-get >/dev/null; then apt-get update -y && apt-get install -y python3 python3-venv python3-pip
  else dnf install -y python3.11 || yum install -y python39; fi
  PY="$(command -v python3.11 || command -v python3.9 || command -v python3)"
fi
echo "    using $PY ($($PY --version))"
if command -v apt-get >/dev/null && ! "$PY" -c "import venv, ensurepip" 2>/dev/null; then
  apt-get install -y "python3-venv" || apt-get install -y "$(basename $PY)-venv"
fi

echo "==> Installing app to $APP_DIR"
mkdir -p "$APP_DIR"
rsync -a --delete --exclude data "$SRC_DIR/forum/" "$APP_DIR/app/" 2>/dev/null || {
  rm -rf "$APP_DIR/app.new"; cp -r "$SRC_DIR/forum" "$APP_DIR/app.new"; rm -rf "$APP_DIR/app.new/data"
  [ -d "$APP_DIR/app/data" ] && mv "$APP_DIR/app/data" "$APP_DIR/app.new/data"
  rm -rf "$APP_DIR/app"; mv "$APP_DIR/app.new" "$APP_DIR/app"; }
[ -d "$APP_DIR/venv" ] || "$PY" -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/app/requirements.txt"

if [ ! -f "$APP_DIR/app/data/charcha.db" ] || [ "${RESEED:-0}" = "1" ]; then
  echo "==> Seeding 50 demo posts"
  (cd "$APP_DIR/app" && "$APP_DIR/venv/bin/python" seed_forum.py)
fi

echo "==> Creating systemd service 'charcha'"
cat > /etc/systemd/system/charcha.service <<EOF
[Unit]
Description=Charcha demo forum (MuleWatch target)
After=network.target

[Service]
WorkingDirectory=$APP_DIR/app
Environment=FORUM_MOD_TOKEN=$MOD_TOKEN
ExecStart=$APP_DIR/venv/bin/uvicorn forum_app:app --host 0.0.0.0 --port $PORT --proxy-headers --workers 2
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now charcha
systemctl restart charcha

echo "==> Opening port $PORT in the firewall"
if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
  firewall-cmd --permanent --add-port=${PORT}/tcp && firewall-cmd --reload
fi
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then ufw allow ${PORT}/tcp; fi
if command -v csf >/dev/null 2>&1; then
  grep -q "^TCP_IN.*\b${PORT}\b" /etc/csf/csf.conf || { sed -i "s/^TCP_IN = \"/TCP_IN = \"${PORT},/" /etc/csf/csf.conf; csf -r >/dev/null; }
fi

sleep 2
if curl -fsS "http://127.0.0.1:${PORT}/" -o /dev/null; then
  IP="$(curl -fsS https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
  echo
  echo "✅ Charcha is running:  http://${IP}:${PORT}"
  echo "   Logins: demo / demo123  ·  judge1, judge2, judge3 / demo123"
  echo "   Moderation token: $MOD_TOKEN  (put the same value in FORUM_MOD_TOKEN of MuleWatch's .env)"
  echo "   Logs: journalctl -u charcha -f      Reseed: RESEED=1 sudo bash $0"
  echo "   If it doesn't open from outside, also allow TCP ${PORT} in CyberPanel → Security → Firewall"
  echo "   and in your hosting provider's network firewall / security group."
else
  echo "❌ Service didn't start. Check: journalctl -u charcha -n 50"
  exit 1
fi
