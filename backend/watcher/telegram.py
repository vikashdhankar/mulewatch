"""Live polling of approved public channels, read-only.

Reuses the research collector: ReadOnlyTelegramClient (join/send/forward/react/mark-read requests are blocked
in the client), the approval gate of research/config/channels.discovered.yaml (approved: true, labelled
likely_fraud or likely_legit), the rate limiter, the record format and the Tesseract OCR of images in memory.

One global limiter spaces every request (entity lookups, history pages, image downloads counted per 512 KB
chunk). Each channel is polled again after interval_active_s if it posted within active_window_h, otherwise
after interval_quiet_s. A FloodWait longer than flood_sleep_threshold_s pauses every channel until it ends."""
import asyncio
import logging
import math
import os
from datetime import datetime, timedelta

from app.db import SessionLocal, WatchChannel, set_setting

from . import store
from .config import path

log = logging.getLogger("watcher.telegram")
CHUNK = 512 * 1024


def next_interval(last_post_at: datetime | None, now: datetime, tcfg: dict) -> int:
    """Seconds until the next poll: often for a channel that is posting, rarely for a quiet one."""
    active = last_post_at is not None and now - last_post_at <= timedelta(hours=tcfg["active_window_h"])
    return int(tcfg["interval_active_s"] if active else tcfg["interval_quiet_s"])


def approved_channels(cfg: dict) -> list[dict]:
    from collect.telegram_public import load_config
    f = path(cfg["channels_file"])
    if not f.exists():
        return []
    return load_config(f)["channels"]


def heartbeat(mode: str):
    set_setting("watcher_heartbeat", datetime.utcnow().isoformat(timespec="seconds"))
    set_setting("watcher_mode", mode)


class Poller:
    def __init__(self, cfg: dict, processor, client, limiter=None, clock=datetime.utcnow, sleep=asyncio.sleep,
                 ocr=None):
        from collect.telegram_public import RateLimiter, ocr_bytes
        self.cfg, self.t, self.p, self.client = cfg, cfg["telegram"], processor, client
        self.limiter = limiter or RateLimiter(self.t["requests_per_minute"])
        self.clock, self.sleep = clock, sleep
        self.ocr = ocr or (lambda data: ocr_bytes(data, cfg["ocr"]["lang"]))
        self.entities: dict = {}
        self.flood_until: datetime | None = None

    async def _entity(self, name: str):
        from collect.telegram_public import is_public_channel
        if name not in self.entities:
            await self.limiter.wait()
            ent = await self.client.get_entity(name)
            if not is_public_channel(ent):
                raise ValueError("not a public broadcast channel")
            self.entities[name] = ent
        return self.entities[name]

    async def _ocr(self, msg) -> str:
        from collect.telegram_public import image_size, media_type
        if not self.cfg["ocr"]["enabled"] or media_type(msg) not in ("photo", "image_document"):
            return ""
        size = image_size(msg)
        if size > self.cfg["ocr"]["max_image_bytes"]:
            return ""
        for _ in range(max(1, math.ceil(size / CHUNK))):
            await self.limiter.wait()
        data = await self.client.download_media(msg, file=bytes)
        if not data:
            return ""
        text = await asyncio.to_thread(self.ocr, data)
        del data                                       # images are never stored
        return text

    async def poll_channel(self, ch: dict) -> int:
        """Read and process this channel's messages newer than its cursor. Returns how many were processed."""
        from collect.telegram_public import to_record
        from telethon.errors import FloodWaitError
        name, key = ch["username"], ch["username"].lower()
        with SessionLocal() as s:
            wc = store.channel(s, key, ch.get("label") or "")
            last_id, first = wc.last_id or 0, not wc.last_id
            s.commit()
        n, err = 0, ""
        try:
            entity = await self._entity(name)
            await self.limiter.wait()
            if first:          # newest posts only: an approved channel's history isn't alerted on
                msgs = list(await self.client.get_messages(entity, limit=max(1, self.t["first_poll_backfill"])))
                newest = max((m.id for m in msgs), default=0)
                msgs = msgs[:self.t["first_poll_backfill"]]
            else:
                msgs = list(await self.client.get_messages(entity, min_id=last_id, limit=self.t["batch_limit"],
                                                           reverse=True))
                newest = last_id
            for msg in sorted(msgs, key=lambda m: m.id):
                if getattr(msg, "action", None):       # service messages (pinned, title changed ...)
                    continue
                rec = to_record(msg, key, await self._ocr(msg))
                if ch.get("label"):
                    rec["channel_label"] = ch["label"]
                await asyncio.to_thread(self.p.handle, rec, "live", not first)
                n += 1
            if newest:
                with SessionLocal() as s:              # also covers a first poll with nothing to process
                    wc = store.channel(s, key)
                    wc.last_id = max(wc.last_id or 0, newest)
                    s.commit()
        except FloodWaitError as e:
            self.flood_until = self.clock() + timedelta(seconds=e.seconds)
            err = f"FloodWait {e.seconds}s: all channels paused"
            log.warning("FloodWait %ss on %s; pausing all channels", e.seconds, key)
            raise
        except Exception as e:                          # one broken channel must not stop the others
            err = f"{type(e).__name__}: {str(e)[:150]}"
            log.warning("poll %s failed: %s", key, type(e).__name__)
        finally:
            now = self.clock()
            with SessionLocal() as s:
                wc = store.channel(s, key)
                wc.last_poll_at, wc.last_error = now, err
                if not err:
                    wc.last_ok_at = now
                wc.interval_s = next_interval(wc.last_post_at, now, self.t)
                wc.next_poll_at = now + timedelta(seconds=wc.interval_s)
                s.commit()
            if n:
                await asyncio.to_thread(self.p.recompute)
        return n

    async def cycle(self) -> int:
        """Poll every approved channel that is due. Returns the number of posts processed."""
        if store.paused(self.cfg):
            return 0
        now = self.clock()
        if self.flood_until and now < self.flood_until:
            return 0
        chans = approved_channels(self.cfg)
        with SessionLocal() as s:
            due_at = {c.username: c.next_poll_at for c in s.query(WatchChannel).all()}
        due = [c for c in chans if (due_at.get(c["username"].lower()) or now) <= now]
        due.sort(key=lambda c: due_at.get(c["username"].lower()) or datetime.min)
        total = 0
        from telethon.errors import FloodWaitError
        for c in due:
            try:
                total += await self.poll_channel(c)
            except FloodWaitError:
                break
        return total

    async def run(self, once: bool = False):
        idle_logged = False
        while True:
            heartbeat("live")
            if not approved_channels(self.cfg) and not idle_logged:
                log.warning("no approved channels in %s; waiting", self.cfg["channels_file"])
                idle_logged = True
            await self.cycle()
            if once:
                return
            await self.sleep(15)


async def connect(cfg: dict, interactive: bool = False):
    from collect.telegram_public import make_client
    api_id, api_hash = os.environ.get("TELEGRAM_API_ID"), os.environ.get("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        raise SystemExit("set TELEGRAM_API_ID and TELEGRAM_API_HASH in research/.env")
    session = path(os.environ.get("TELEGRAM_WATCHER_SESSION") or cfg["telegram"]["session"])
    session.parent.mkdir(parents=True, exist_ok=True)
    client = make_client(str(session), int(api_id), api_hash, cfg["telegram"]["flood_sleep_threshold_s"])
    if interactive:
        await client.start()
    else:
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            raise SystemExit("the watcher's Telegram session is not logged in: run `python -m watcher login` once "
                             "in a terminal (from backend/)")
    return client
