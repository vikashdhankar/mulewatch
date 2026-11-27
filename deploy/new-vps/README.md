# Moving MuleWatch, Charcha and ATMLens to the new VPS

Old VPS: `ssh mockup-server` (103.155.85.18, CyberPanel), shutting down next month.
New VPS: `ssh rootserver`.

GitHub carries the **code**. It must not carry the **data** (forum database, `.env` files, keys, evidence);
those are copied server-to-server with `scp`.

## What I found on the laptop (23 Nov 2026)

| Project | Laptop copy | GitHub | Action |
|---|---|---|---|
| MuleWatch | tracks `vikashdhankar/mulewatch`; branch `fix/qa-hindi-bulk-discovery` has commit `809e64c` that is **not on GitHub** | `vikashdhankar/mulewatch` main = `5b4e7fd` (police workflow, Hindi UI, discovery) | push + merge the fix (step 0) |
| MuleWatch (team) | not on laptop | `Sunil-saini1818/MuleWatch` main = `0848e83` (Gemini analyst, pitch deck). Separate history since 14 Oct | not deployed; see note below |
| ATMLens | `af03d45`, no local changes | `vikashdhankar/ATMLens` main = `9f257cc` (2 commits newer) | nothing to push |

Note: the two MuleWatch repositories split on 14 Oct and have different features. The server uses
`vikashdhankar/mulewatch` because it has the police command center. Merging the team's Gemini-analyst work is a
separate job. The team repo also has a Telegram API ID/hash written into `backend/app/config.py`: revoke it at
my.telegram.org and move it to `.env`.

## Steps

0. **Laptop:** `bash 00_laptop_prepare.sh`
1. **Old server:** `scp 01_backup_old_server.sh mockup-server:/root/ && ssh mockup-server bash /root/01_backup_old_server.sh`
   Read the `inventory.txt` it prints. MockCircle.in and anything else listed there also has to move before shutdown.
2. **Copy the forum data old -> laptop -> new:**
   `scp mockup-server:/root/migration-backup-*/charcha-data.tgz . && scp charcha-data.tgz rootserver:/root/`
3. **ATMLens deploy key** (ATMLens is private): on the new server `ssh-keygen -t ed25519 -N '' -f /root/atmlens_deploy_key`,
   add `/root/atmlens_deploy_key.pub` in GitHub -> ATMLens -> Settings -> Deploy keys (read-only).
4. **DNS:** create A-records for e.g. `charcha.`, `mulewatch.`, `atmlens.` on your domain, pointing to the new IP.
5. **New server:**
   ```
   scp 02_setup_new_server.sh rootserver:/root/
   ssh rootserver "FORUM_DOMAIN=charcha.<domain> MW_DOMAIN=mulewatch.<domain> AL_DOMAIN=atmlens.<domain> \
                   ATMLENS_DEPLOY_KEY=/root/atmlens_deploy_key bash /root/02_setup_new_server.sh"
   ```
6. **Check:** open the three sites; sign in; the MuleWatch "Monitored sources" page should show the forum live;
   post on Charcha and see the alert arrive.
7. **Security before showing anyone:**
   * MuleWatch starts with **no demo users**; add yours with `python -m app.users add`.
   * ATMLens demo accounts use the password printed in its README: change them on first sign-in.
   * Put only synthetic/demo footage in the ATMLens demo. Real CCTV evidence stays on the police unit's own PC.
8. **Update links:** done 27 Nov 2026: no file still points at `103.155.85.18` except this page's description of the old server.
   Keep the old server running until you've confirmed the new one (see the rollback below).

## Charcha forum: operations

Since 27 Nov 2026 the forum lives on **rootserver** (103.174.103.46) at **https://charcha.openhippo.in**.
MuleWatch and ATMLens for the demo run on the **laptop** and reach the forum over the internet.

| | |
|---|---|
| Service | `charcha` (systemd, user `apps`), uvicorn on `127.0.0.1:8100`, code in `/srv/apps/charcha/app`, data in `/srv/apps/charcha/app/data` |
| HTTPS | OpenLiteSpeed vhost `charcha.openhippo.in` (CyberPanel) proxies to 127.0.0.1:8100; Let's Encrypt cert; Cloudflare proxy on (orange cloud) |
| Access | Cloudflare Access app `charcha`: people use policy "Charcha demo viewers" (allowed emails); the laptop crawler uses Service Auth policy "MuleWatch laptop crawler (service token)" with token `mulewatch-laptop-crawler` (expires Nov 2027) |
| Laptop `.env` | `FORUM_URL=https://charcha.openhippo.in`, `FORUM_HEADERS` = that token's CF-Access-Client-Id/Secret, `FORUM_MOD_TOKEN` = the same value as in `charcha.service` |
| Search engines | every response has `X-Robots-Tag: noindex, nofollow, noarchive`; the forum's `robots.txt` says `Disallow: /` (Cloudflare's zone-wide managed robots.txt adds its own block above it) |

```bash
ssh rootserver
systemctl status charcha                 # state
journalctl -u charcha -f                 # live logs
systemctl restart charcha                # restart (touches nothing else)
curl -sI http://127.0.0.1:8100/          # 200 + x-robots-tag, from the server itself
```

**Backups.** `/usr/local/bin/charcha-backup.sh` runs every night at 02:15 UTC (`/etc/cron.d/charcha-backup`, log in
`/var/log/charcha-backup.log`) and writes `/root/backups/charcha-nightly-<date>.db` + `-uploads.tgz`, keeping 7 days.
Run it by hand before any risky change: `ssh rootserver /usr/local/bin/charcha-backup.sh`.
Copy one to the laptop: `scp 'rootserver:/root/backups/charcha-nightly-*.db' ~/charcha-backups/`.

**Restore a backup.**
```bash
ssh rootserver 'systemctl stop charcha && cp /root/backups/charcha-nightly-<date>.db /srv/apps/charcha/app/data/charcha.db \
  && chown apps: /srv/apps/charcha/app/data/charcha.db && systemctl start charcha'
```

**Reset to the 50 seeded posts** (deletes judges' posts; take a backup first):
```bash
ssh rootserver '/usr/local/bin/charcha-backup.sh && systemctl stop charcha && cd /srv/apps/charcha/app \
  && rm -f data/charcha.db && sudo -u apps ../venv/bin/python seed_forum.py && systemctl start charcha'
```
Then on the laptop run `./run.sh --reset` so MuleWatch forgets the old case ids.

**Update the forum code** after a commit: `scp forum/forum_app.py rootserver:/root/ && ssh rootserver 'install -o apps -g apps -m 644 /root/forum_app.py /srv/apps/charcha/app/ && systemctl restart charcha'`
(templates/static likewise, or `rsync -a --exclude data forum/ rootserver:/srv/apps/charcha/app/` then `chown -R apps: /srv/apps/charcha/app`).

**Moderation token.** Kept in `/etc/systemd/system/charcha.service` and in `/srv/apps/mulewatch/.env` (the server's own MuleWatch);
it must equal `FORUM_MOD_TOKEN` in the laptop `.env`. After changing it: `systemctl daemon-reload && systemctl restart charcha mulewatch`.

**Service token.** Rotate it in Zero Trust → Access controls → Service credentials → `mulewatch-laptop-crawler` → Rotate secret,
then put the new secret in the laptop's `FORUM_HEADERS`. If Monitored sources shows "redirected to a sign-in page", the
token is missing, expired or not in the Access policy.

**Roll back to the old server** (103.155.85.18, while it still runs):
```bash
cd ~/Projects/mulewatch && cp .env .env.broken-$(date +%F) && cp .env.bak-2026-11-27 .env   # then restart ./run.sh
```
`.env.bak-2026-11-27` has the old `FORUM_URL=http://103.155.85.18:8100` and the moderation token MuleWatch used with it
(the old server's own token was not re-checked: ssh to it hung on 26 Nov). **Offline fallback:** `./run.sh --local-forum` runs the forum on the laptop and ignores `FORUM_HEADERS`.
