#!/usr/bin/env bash
# Run on the NEW server as root (ssh rootserver), Ubuntu 22.04/24.04.
# Installs Charcha (public demo forum), the MuleWatch command center and an ATMLens DEMO, each as a systemd service.
#
#   FORUM_DOMAIN=charcha.example.in MW_DOMAIN=mulewatch.example.in AL_DOMAIN=atmlens.example.in \
#   ATMLENS_DEPLOY_KEY=/root/atmlens_deploy_key  bash 02_setup_new_server.sh
#
# Domains are optional. With them (and DNS A-records pointing here) Caddy serves HTTPS automatically.
# Without them, Charcha is published on http://IP:8100 and the command centers stay on localhost (use an SSH tunnel).
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }
FORUM_DOMAIN="${FORUM_DOMAIN:-}"; MW_DOMAIN="${MW_DOMAIN:-}"; AL_DOMAIN="${AL_DOMAIN:-}"
MOD_TOKEN="${FORUM_MOD_TOKEN:-$(openssl rand -hex 16)}"

echo "==> Packages"
apt-get update -y
apt-get install -y git curl rsync python3 python3-venv python3-pip tesseract-ocr tesseract-ocr-hin ffmpeg \
  libgl1 libglib2.0-0 ca-certificates gnupg
if ! command -v node >/dev/null || [ "$(node -v | cut -c2- | cut -d. -f1)" -lt 18 ]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && apt-get install -y nodejs
fi
id apps >/dev/null 2>&1 || useradd -r -m -d /srv/apps -s /bin/bash apps

echo "==> Code from GitHub"
clone() {  # url dir
  if [ -d "$2/.git" ]; then sudo -u apps git -C "$2" pull --ff-only; else sudo -u apps git clone "$1" "$2"; fi; }
clone https://github.com/vikashdhankar/mulewatch.git /srv/apps/mulewatch
if [ -n "${ATMLENS_DEPLOY_KEY:-}" ]; then   # ATMLens is private: read-only deploy key added in GitHub → Settings → Deploy keys
  install -o apps -m 600 "$ATMLENS_DEPLOY_KEY" /srv/apps/.ssh_atmlens_key
  export GIT_SSH_COMMAND="ssh -i /srv/apps/.ssh_atmlens_key -o StrictHostKeyChecking=accept-new"
  sudo -u apps --preserve-env=GIT_SSH_COMMAND bash -c 'cd /srv/apps && { [ -d atmlens/.git ] && git -C atmlens pull --ff-only || git clone git@github.com:vikashdhankar/ATMLens.git atmlens; }'
else
  echo "!! ATMLENS_DEPLOY_KEY not set: skipping ATMLens"; fi

echo "==> Charcha forum (port 8100)"
FD=/srv/apps/charcha; mkdir -p $FD; rsync -a --delete --exclude data /srv/apps/mulewatch/forum/ $FD/app/; chown -R apps: $FD
[ -d $FD/venv ] || sudo -u apps python3 -m venv $FD/venv
sudo -u apps $FD/venv/bin/pip install -q -r $FD/app/requirements.txt
if [ -f /root/charcha-data.tgz ]; then tar xzf /root/charcha-data.tgz -C $FD/app && chown -R apps: $FD/app/data; echo "   restored old forum data"
elif [ ! -f $FD/app/data/charcha.db ]; then (cd $FD/app && sudo -u apps $FD/venv/bin/python seed_forum.py); fi
FORUM_BIND=127.0.0.1; [ -z "$FORUM_DOMAIN" ] && FORUM_BIND=0.0.0.0
cat > /etc/systemd/system/charcha.service <<U
[Unit]
Description=Charcha demo forum (MuleWatch target)
After=network.target
[Service]
User=apps
WorkingDirectory=$FD/app
Environment=FORUM_MOD_TOKEN=$MOD_TOKEN
ExecStart=$FD/venv/bin/uvicorn forum_app:app --host $FORUM_BIND --port 8100 --proxy-headers --workers 2
Restart=always
[Install]
WantedBy=multi-user.target
U

echo "==> MuleWatch command center (127.0.0.1:8000)"
MW=/srv/apps/mulewatch
[ -d $MW/.venv ] || sudo -u apps python3 -m venv $MW/.venv
sudo -u apps $MW/.venv/bin/pip install -q -r $MW/backend/requirements.txt -r $MW/forum/requirements.txt
(cd $MW/frontend && sudo -u apps npm install --no-audit --no-fund --silent && sudo -u apps npm run build --silent)
FORUM_URL="http://127.0.0.1:8100"
if [ ! -f $MW/.env ]; then
  sed -e "s#^FORUM_URL=.*#FORUM_URL=$FORUM_URL#" -e "s#^FORUM_MOD_TOKEN=.*#FORUM_MOD_TOKEN=$MOD_TOKEN#" \
      -e "s#^MW_DEMO_USERS=.*#MW_DEMO_USERS=0#" \
      -e "s#^PUBLIC_BASE_URL=.*#PUBLIC_BASE_URL=${MW_DOMAIN:+https://$MW_DOMAIN}#" $MW/.env.example > $MW/.env
  chown apps: $MW/.env; chmod 600 $MW/.env; fi
cat > /etc/systemd/system/mulewatch.service <<U
[Unit]
Description=MuleWatch command center
After=network.target charcha.service
[Service]
User=apps
WorkingDirectory=$MW/backend
EnvironmentFile=$MW/.env
ExecStart=$MW/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers
Restart=always
[Install]
WantedBy=multi-user.target
U

if [ -d /srv/apps/atmlens ]; then
  echo "==> ATMLens DEMO (127.0.0.1:8010, synthetic footage only)"
  AL=/srv/apps/atmlens
  [ -d $AL/.venv ] || sudo -u apps python3 -m venv $AL/.venv
  sudo -u apps $AL/.venv/bin/pip install -q -r $AL/backend/requirements.txt
  (cd $AL/frontend && sudo -u apps npm install --no-audit --no-fund --silent && sudo -u apps npm run build --silent)
  mkdir -p /var/lib/atmlens && chown apps: /var/lib/atmlens && chmod 700 /var/lib/atmlens
  [ -f $AL/.env ] || { printf 'AL_UNIT_NAME=DEMO - not for real cases\nAL_DATA_DIR=/var/lib/atmlens\nAL_DEMO_USERS=1\n' > $AL/.env; chown apps: $AL/.env; chmod 600 $AL/.env; }
  cat > /etc/systemd/system/atmlens.service <<U
[Unit]
Description=ATMLens demo
After=network.target
[Service]
User=apps
WorkingDirectory=$AL/backend
EnvironmentFile=$AL/.env
ExecStart=$AL/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010 --proxy-headers
Restart=always
[Install]
WantedBy=multi-user.target
U
fi

systemctl daemon-reload
for s in charcha mulewatch atmlens; do [ -f /etc/systemd/system/$s.service ] && systemctl enable --now $s && systemctl restart $s; done

echo "==> HTTPS reverse proxy"
if ss -ltn | grep -qE ':(80|443) ' && ! systemctl is-active --quiet caddy; then
  echo "!! Ports 80/443 are taken (CyberPanel/OpenLiteSpeed?). Add reverse-proxy rules in the panel instead:"
  echo "   $FORUM_DOMAIN -> 127.0.0.1:8100,  $MW_DOMAIN -> 127.0.0.1:8000,  $AL_DOMAIN -> 127.0.0.1:8010"
elif [ -n "$FORUM_DOMAIN$MW_DOMAIN$AL_DOMAIN" ]; then
  apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -y && apt-get install -y caddy
  { [ -n "$FORUM_DOMAIN" ] && printf '%s {\n  reverse_proxy 127.0.0.1:8100\n}\n' "$FORUM_DOMAIN"
    [ -n "$MW_DOMAIN" ] && printf '%s {\n  reverse_proxy 127.0.0.1:8000\n  request_body { max_size 50MB }\n}\n' "$MW_DOMAIN"
    [ -n "$AL_DOMAIN" ] && printf '%s {\n  reverse_proxy 127.0.0.1:8010\n  request_body { max_size 2GB }\n}\n' "$AL_DOMAIN"; } > /etc/caddy/Caddyfile
  systemctl restart caddy
fi

echo "==> Firewall"
if systemctl is-active --quiet firewalld; then
  # CyberPanel servers use firewalld: never stack ufw on top (it can lock out the panel, mail, DNS or Docker)
  echo "   firewalld is active: leaving it as it is (the command centers bind to 127.0.0.1)"
  if [ -z "$FORUM_DOMAIN" ]; then firewall-cmd --permanent --add-port=8100/tcp && firewall-cmd --reload; fi
else
  apt-get install -y ufw
  ufw allow OpenSSH; ufw allow 80/tcp; ufw allow 443/tcp; [ -z "$FORUM_DOMAIN" ] && ufw allow 8100/tcp; ufw --force enable
fi

sleep 3
for p in 8100 8000 8010; do printf "port %s: " $p; curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:$p/ || echo down; done
echo
echo "FORUM_MOD_TOKEN=$MOD_TOKEN   (already written into MuleWatch's .env)"
echo "Next: create real MuleWatch users:  cd $MW/backend && sudo -u apps ../.venv/bin/python -m app.users add <user> SUPERVISOR \"Name\""
echo "      ATMLens demo users have the public password from its README: sign in and change them at once."
