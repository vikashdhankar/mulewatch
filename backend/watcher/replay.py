"""Replay collected posts through the live pipeline, so real-time alerts can be shown without waiting for new
posts. The gaps between posts are their real gaps divided by --speed, capped at replay.max_gap_s. Posts already
processed (live or in an earlier replay) are skipped, so a replay never alerts twice.

window_hours: only the last N hours of the file (up to its newest post) are replayed in real time. Older
posts are processed first, without pauses, as history: they are scored and remembered (identifiers, channel
posting rates) but raise no case or alert. Post times are never changed, so evidence keeps the real ones."""
import logging
import re
import time
from datetime import timedelta

from common.io import iter_jsonl

from .process import utc_naive
from .telegram import heartbeat

log = logging.getLogger("watcher.replay")


def parse_speed(s: str | float) -> float:
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*x?\s*", str(s).lower())
    if not m or float(m.group(1)) <= 0:
        raise ValueError(f"speed must look like 50x, got {s!r}")
    return float(m.group(1))


def load(path) -> list[dict]:
    rows = []
    for r in iter_jsonl(path):
        if "message_id" not in r:                     # tg:<channel>:<id>
            try:
                r["message_id"] = int(str(r.get("post_id", "")).rsplit(":", 1)[1])
            except (IndexError, ValueError):
                continue
        if r.get("channel") and r.get("date"):
            rows.append(r)
    rows.sort(key=lambda r: utc_naive(r["date"]))
    return rows


def replay(path, processor, speed: float = 50.0, max_gap: float = 5.0, push: bool = False, limit: int | None = None,
           sleep=time.sleep, recompute_every: int = 10, window_hours: float | None = None) -> dict:
    rows = load(path)
    history = []
    if window_hours and rows:
        start = utc_naive(rows[-1]["date"]) - timedelta(hours=window_hours)
        history = [r for r in rows if utc_naive(r["date"]) < start]
        rows = rows[len(history):]
        log.info("history: %d posts before %s (no alerts)", len(history), start.isoformat(timespec="minutes"))
        for i, r in enumerate(history, 1):
            processor.handle(r, history=True)
            if i % 500 == 0:
                log.info("history: %d/%d", i, len(history))
                heartbeat("replay")
    rows = rows[:limit] if limit else rows
    log.info("replaying %d posts from %s at %sx", len(rows), path, speed)
    prev, since, cases = None, time.monotonic(), 0
    for r in rows:
        t = utc_naive(r["date"])
        if prev is not None:
            gap = min(max(0.0, (t - prev).total_seconds() / speed), max_gap)
            if gap:
                sleep(gap)
        prev = t
        out = processor.handle(r, mode="replay", push=push)
        if out and out.post_id:
            cases += 1
            if cases % recompute_every == 0:
                processor.recompute(push=push)
        if time.monotonic() - since > 10:
            heartbeat("replay")
            since = time.monotonic()
    processor.recompute(push=push)
    heartbeat("replay_done")
    return dict(processor.counts, posts=len(rows), history_posts=len(history))
