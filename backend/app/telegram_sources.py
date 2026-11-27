"""Add the hand-approved Telegram channels as live sources (public web previews, t.me/s/<channel>).

Only channels marked `approved: true` in research/config/channels.discovered.yaml are added: that flag is
set by `python -m collect.apply_review` from the Y's in the channel review sheet, after a person has looked
at each channel. Nothing is added from the discovery tool's suggestions alone.

    cd backend
    ../.venv/bin/python -m app.telegram_sources --dry-run     # list what would be added
    ../.venv/bin/python -m app.telegram_sources               # add them (the running app picks them up)

Run it with the same data folder (MW_DATA_DIR) as the command center. Channels already added are skipped;
a channel that is no longer approved is switched off, not deleted, so its cases stay. Polling pace:
TELEGRAM_PER_CYCLE and TELEGRAM_INTERVAL in app/crawler.py.
"""
import argparse
import re
from pathlib import Path

import yaml

from .config import BASE_DIR
from .db import SessionLocal, Source, init_db

DEFAULT_YAML = BASE_DIR.parent / "research" / "config" / "channels.discovered.yaml"
USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")


def approved_channels(path: Path) -> list[dict]:
    d = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = d.get("channels", []) if isinstance(d, dict) else d
    out = []
    for r in rows or []:
        u = str(r.get("username", "")).strip().lstrip("@")
        if r.get("approved") is True and USERNAME.match(u):
            out.append({"username": u, "label": r.get("label", ""), "category": r.get("category", ""),
                        "district": r.get("top_district", "") or ""})
    return out


def sync(path: Path, dry_run: bool = False) -> dict:
    chans = approved_channels(path)
    wanted = {c["username"].lower(): c for c in chans}
    added, kept, disabled = [], [], []
    init_db()
    with SessionLocal() as s:
        have = {x.url.rstrip("/").split("/")[-1].lower(): x for x in s.query(Source).filter_by(kind="telegram")}
        for key, c in wanted.items():
            if key in have:
                kept.append(c["username"])
                if not have[key].enabled and not dry_run:
                    have[key].enabled = True
                continue
            added.append(c["username"])
            if not dry_run:
                tag = " · ".join(x for x in (c["label"].replace("likely_", ""), c["category"], c["district"]) if x)
                s.add(Source(kind="telegram", url=f"https://t.me/s/{c['username']}",
                             name=f"@{c['username']}" + (f" ({tag})" if tag else "")))
        for key, x in have.items():
            if key not in wanted and x.enabled:
                disabled.append(key)
                if not dry_run:
                    x.enabled = False
        if not dry_run:
            s.commit()
    return {"approved": len(chans), "added": added, "already": kept, "switched_off": disabled}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--yaml", type=Path, default=DEFAULT_YAML)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    r = sync(a.yaml, a.dry_run)
    verb = "would add" if a.dry_run else "added"
    print(f"{r['approved']} approved channels in {a.yaml.name}: {verb} {len(r['added'])}, "
          f"{len(r['already'])} already sources, {len(r['switched_off'])} no longer approved"
          f"{' (would be switched off)' if a.dry_run else ' (switched off)'}")
    for u in r["added"]:
        print(f"  + @{u}")
    for u in r["switched_off"]:
        print(f"  - @{u}")
    if not r["approved"]:
        print("No channel is approved yet: put Y in research/store/MuleWatch_Channel_Review.xlsx, then run\n"
              "  cd research && ../.venv/bin/python -m collect.apply_review")


if __name__ == "__main__":
    main()
