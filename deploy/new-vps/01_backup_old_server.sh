#!/usr/bin/env bash
# Run on the OLD server (ssh mockup-server). Saves everything that is NOT in GitHub and lists what else runs there.
set -uo pipefail
TS=$(date +%Y%m%d-%H%M); OUT=/root/migration-backup-$TS; mkdir -p "$OUT"
echo "== Charcha forum data (posts, users, reports)"
systemctl stop charcha 2>/dev/null || true          # consistent SQLite copy
tar czf "$OUT/charcha-data.tgz" -C /opt/charcha/app data 2>/dev/null && echo "   saved charcha-data.tgz"
cp /etc/systemd/system/charcha.service "$OUT/" 2>/dev/null
systemctl start charcha 2>/dev/null || true         # keep the old forum up until DNS/IP switch
echo "== Inventory of everything else on this server (MockCircle, websites, databases, cron)"
{
  echo "## listening ports";            ss -ltnp
  echo "## enabled services";           systemctl list-unit-files --state=enabled --type=service --no-pager
  echo "## /opt and /home";             ls -la /opt /home
  echo "## CyberPanel websites";        ls /home/*/public_html -d 2>/dev/null; ls /usr/local/lsws/conf/vhosts 2>/dev/null
  echo "## MySQL databases";            mysql -e 'show databases' 2>/dev/null
  echo "## root crontab";               crontab -l 2>/dev/null
  echo "## docker";                     docker ps -a 2>/dev/null
  echo "## disk";                       df -h; du -sh /home/* /opt/* 2>/dev/null
} > "$OUT/inventory.txt" 2>&1
tar czf "$OUT.tgz" -C /root "$(basename "$OUT")"
echo "Backup: $OUT.tgz  (read $OUT/inventory.txt: anything listed there also has to move before the old VPS shuts down)"
