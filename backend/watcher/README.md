# Real-time Telegram watcher

Reads the **approved** public Telegram channels every 2–15 minutes. Each new post goes through
redaction, classification and risk scoring, and is routed into the command center that already exists.
The watcher is a separate process that writes into the same database, so its alerts show live on the
dashboard (the `/api/events` stream). Research collection (`research/collect`) stays offline and is
not changed.

```
approved channel ──► poll (read-only Telethon, 20 req/min, FloodWait-aware, cursor per channel in SQLite)
                     └─► OCR of images (hin+eng, size cap)
post ──► redact (keyed hashes of phone/UPI/account/card/handle)
     ──► classify (best saved research model, else TF-IDF + LR; LLM second opinion when 0.35 ≤ p ≤ 0.75)
     ──► risk 0–100 ──► ≥70 HIGH: case + alert + Telegram message to the duty chat
                        40–69 MEDIUM: case in the review queue
                        <40 LOW: stored only (masked), not shown as a case
```

Risk = 60·p·severity(category) + 15 (an identifier never seen before) + 10 (a Rajasthan place named)
+ 10 (channel posting rate in the last hour > 3× its 7-day mean) + 5 (an identifier seen in ≥ 3 channels).
All weights, severities and thresholds are in `watcher.yaml`.

## Run it

```bash
./run.sh                         # the command center, as before
./run.sh watcher login           # once: Telegram phone number and code (its own session file)
./run.sh watcher                 # the watcher; or the systemd unit in deploy/systemd/
```

Before the first run:

1. `research/.env` holds `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` and `RESEARCH_HASH_SALT` (or set
   `WATCHER_HASH_SALT`). Identifier hashes are keyed with this salt, so keep it fixed: if it changes,
   every identifier looks new.
2. Approve channels in `research/config/channels.discovered.yaml` (`approved: true`). Only those are read.
3. The duty officer's chat is the one the bot already alerts (`TELEGRAM_CHAT_ID`, or `/alerts <code>`).

Pause without stopping: **Pause** on the *Telegram watcher* page (supervisors), or `paused: true` in
`watcher.yaml`.

## Demo without waiting for live posts

```bash
./run.sh watcher --replay research/store/raw/telegram.jsonl --speed 50x
# no collected data yet? make synthetic posts:
(cd research && ../.venv/bin/python -m tools.synthetic --out /tmp/syn --n 400 --channels 6 --sellers 25)
./run.sh watcher --replay /tmp/syn/raw.jsonl --speed 200x
```

The replay keeps the posts' own gaps, divided by the speed and capped at 5 s. It sends nothing to
Telegram unless you add `--push`. Replayed rows are marked `replay`.

## Other commands (`./run.sh watcher <command>`, or `python -m watcher <command>` from `backend/`)

| Command | What it does |
|---|---|
| `run --once` | one polling cycle, then exit |
| `health` | last poll per channel, polling lag, review-queue size (also `GET /api/watcher/health`) |
| `retrain` | rebuild the fallback TF-IDF + LR model, including reviewers' decisions exported earlier |
| `export-feedback` | write reviewed posts to `research/store/annotations/watcher/` as labelled data (also a button on the page) |

## What it reuses

From the backend (`backend/app`): the `Post` / `Alert` models and `pipeline.ingest`, so a watcher case
is an ordinary case. It also reuses the existing alert path and its Telegram sending (`alerts.send_to_chat`
and the linked duty chat), `evidence` (files with SHA-256 and integrity checks), the BSA Sec. 63
certificate from `legal`, `jurisdiction` (place → district), `audit`, role-based masking, and the
existing reviewer feedback (`apply_feedback`).

From research (`research/`): `pii.redact.Redactor`, the read-only Telegram client, rate limiter,
approval gate and OCR (`collect.telegram_public`), the category terms (`collect.discover_channels`),
the saved models and `models.tfidf_lr`, and `common.llm_client`.

## Privacy

- Logs carry channel, message id, route, score and category. They never contain post text or contact
  values (a log filter also masks anything that slips through).
- The Telegram alert carries masked text, category, score, channel, link, district and the number of
  linked identifiers. It never carries the phone number or UPI ID.
- The watcher's own tables hold masked text and identifier hashes only. MEDIUM and HIGH cases keep the
  post as received in the case and its evidence files, as for any other source, because the
  investigating officer needs it. Role-based masking applies on screen.

## Tests

```bash
cd backend && ../.venv/bin/python -m pytest -q tests/test_watcher_*.py
```

These use mocked Telethon updates and check the expected alerts, that the same post never alerts twice,
identifier novelty, routing thresholds, the API, evidence packs and feedback export.
