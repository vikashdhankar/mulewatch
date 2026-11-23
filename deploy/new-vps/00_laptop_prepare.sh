#!/usr/bin/env bash
# Run on your LAPTOP. Makes sure GitHub has the latest code before the servers clone it.
set -euo pipefail
cd ~/Projects/mulewatch
echo "== MuleWatch (laptop copy tracks github.com/vikashdhankar/mulewatch)"
git status --short | head -20
# Your Hindi/bulk/discovery QA fix (commit 809e64c) exists only on this laptop. Push it and merge into main.
git push -u origin fix/qa-hindi-bulk-discovery
git checkout main && git pull --ff-only origin main
git merge --no-ff fix/qa-hindi-bulk-discovery -m "Merge QA fixes (Hindi text, bulk notes, discovery rotation)"
git push origin main
echo "== ATMLens (GitHub is 2 commits ahead of this laptop; nothing local to push)"
cd ~/Projects/atmlens && git status --short | head -20 && git pull --ff-only origin main
echo "Done. Both repos on GitHub are now the source for the new server."
