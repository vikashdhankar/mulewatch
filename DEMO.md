# 29 Nov demo: real-time Telegram alerts in the command center

Collected public posts are replayed through the Telegram watcher at 50x. The alerts appear live on the
command center's **Telegram watcher** page, where they can be filtered by district and category. All
commands run from the repository root.

## Before the demo day (27–28 Nov)

### 1. Review and approve channels

Fill in `research/store/MuleWatch_Channel_Review.xlsx`: put **Y** in "approved (Y/N)" for every channel you
checked by hand (https://t.me/s/<username>). A row whose suggestion is still `review` or `reject` is not
applied: change its suggestion to `approve_fraud` or `approve_legit` before marking it Y. Then:

```bash
cd research
../.venv/bin/python -m collect.apply_review --dry-run      # what would change, counts per label/category/district
../.venv/bin/python -m collect.apply_review                # writes config/channels.discovered.yaml
```

The last line of the report gives the fraud:legit ratio of the approved set. The target is about 2:1.
If there are too few legit channels, screen the legit seeds first. They go through the same scorer, and
discovery allows 300 Telegram requests a day:

```bash
../.venv/bin/python -m collect.discover_channels --legit-seeds config/legit_seeds.yaml
```

Screened seeds land in `config/channels.discovered.yaml` with `approved: false`. Check them by hand
like the rest, then mark them approved: add them to the review sheet with suggestion `approve_legit` and
Y, or set `approved: true` in the YAML.

### 2. Collect the approved channels (first pass: newest 500 posts each)

```bash
cd research
../.venv/bin/python -m collect.telegram_public --config config/channels.discovered.yaml --approved-only \
    --out store/raw/telegram.jsonl --max-posts 500
```

- The rate limit is unchanged: 20 requests/min for history pages and image downloads together, plus 10 s
  between channels.
- History takes 5 requests per channel (500 posts in pages of 100), so text alone takes about half a
  minute per channel.
- Each image post adds one download for OCR. A channel where half the posts are images takes about 13
  minutes, so 60 such channels take about 13 hours. **Start this by the morning of 28 Nov.**
- It can be stopped and run again: a channel continues from its last post (`store/raw/telegram_state.json`).
- Only one Telegram job runs at a time, so don't run discovery during collection.

Check what you have:

```bash
cd backend
../.venv/bin/python -m watcher replay ../research/store/raw/telegram.jsonl --speed 50x --window-hours 12 --estimate
```

This prints the number of posts in the replay window and how long the replay takes. Choose
`--window-hours` so the replay fits the slot, e.g. 10–15 minutes. Older posts are processed first as
**history**: they are scored and remembered, so "new identifier" and "posting burst" behave as they would
live, but they raise no alerts.

### 3. Rehearse (evening of 28 Nov)

Run the demo below once, end to end, then reset it (last section). A post never alerts twice, so every
run needs a fresh demo database.

Count the HIGH alerts in the rehearsal. Because of the history, an identifier seen earlier no longer counts
as new (+15), so a HIGH alert needs a strong post plus a Rajasthan place, a burst or a new identifier. If
the window gives too few HIGH alerts, try a different `--window-hours`. Replaying without the window
gives more alerts, but over a much longer run.

## On the day

Use a demo database of its own, so the real one stays untouched.

**Terminal 1: command center**

```bash
export MW_DATA_DIR="$PWD/backend/data/demo"
rm -rf "$MW_DATA_DIR"
./run.sh add-sp      # the line above deleted the SP account: create it again (asks for the password)
./run.sh
```

Open http://localhost:8000/watcher and sign in with the **analyst** demo account (shown on the sign-in
page). The watcher page always shows posts masked (`[PHONE]`, `[UPI]`). Case pages show the post as
collected: the analyst account sees phone and account numbers partly hidden, but **UPI IDs in full**. On a
projector, stay on the watcher page or open case pages with care.

**Terminal 2: the replay**, once the page is open

```bash
export MW_DATA_DIR="$PWD/backend/data/demo"
./run.sh watcher --replay research/store/raw/telegram.jsonl --speed 50x --window-hours 12 --no-llm
```

- `--no-llm` skips the LLM second opinion. Leave it out only if the model server in
  `research/models/configs/llm_zeroshot.yaml` is running (`ollama serve`); otherwise each gray-zone post
  waits for the timeout.
- Telegram messages to the duty officer are **off** in a replay. Add `--push` only if the duty chat
  (`TELEGRAM_CHAT_ID` in `.env`) is meant to receive the demo alerts: it is a real chat.

**What to show**

1. *Live alerts*: HIGH and MEDIUM cards arrive as the replay runs, with score, category, cue words and
   score breakdown.
2. The **district** filter (e.g. Jaipur), then the category filter (e.g. USDT P2P), then *Review queue*.
3. **Confirm / False alarm / Needs info** on a card: the decision is stored with the reviewer and time.
4. Click an identifier hash: the channels and posts that share it, and when it was first seen.
5. *Posting bursts*: pick a channel; red bars are flagged posts, and the dashed lines are the usual rate
   and the burst threshold.
6. Sign in as the **IO** account and click *Evidence PDF* on a HIGH card: the post, its SHA-256, the
   t.me link and UTC times, and the BSA Sec. 63 certificate with fields to complete.

## After the demo

```bash
# stop both terminals (Ctrl+C), then
rm -rf backend/data/demo
```

This also deletes the SP account in the demo database; the next run creates it again with `./run.sh add-sp`.

Decisions taken during the demo stay in the demo database. Export them to research only if they should
count as labelled data (*Export decisions to research* on the watcher page).

## SP / Super Admin account

Sh. Sumit Mehada, Superintendent of Police, Police Headquarters, Jaipur, signs in as `sp`. It is the
**Supervisor** role, the top one (every page, Officers, Audit log); the header shows it as *Super Admin (SP)*.

```bash
export MW_DATA_DIR="$PWD/backend/data/demo"   # the same data folder as the command center
./run.sh add-sp                               # asks for the password; prints the database it wrote to
./run.sh add-sp --username sp.mehada          # another username
```

- The demo reset (`rm -rf backend/data/demo`, or `rm -rf "$MW_DATA_DIR"` above) and `./run.sh --reset`
  delete this account. Run `./run.sh add-sp` again after every reset.
- Running it again on an existing account resets its password, re-enables it and signs out its old sessions.
- For a script, `SP_PASSWORD='...' ./run.sh add-sp` skips the prompt. Don't write the password into this file
  or any other file in the repo; give it to the SP in person.
