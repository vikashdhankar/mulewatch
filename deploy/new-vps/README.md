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
8. **Update links:** the MuleWatch README, `deploy/setup-forum-server.sh`, a test and the built dashboard mention `103.155.85.18`; change them
   to the new forum address. Keep the old server running until step 6 passes.
