"""Read posts from public Telegram channels listed in config/channels.yaml.

    python -m collect.telegram_public --config config/channels.yaml --out store/raw/telegram.jsonl
    python -m collect.telegram_public --config config/channels.discovered.yaml --approved-only \
        --out store/raw/telegram.jsonl --max-posts 500     # approved entries only, newest 500 per channel

What it does and does not do:
  * reads message history of public broadcast channels that have an @username, without joining them;
    a channel's first run takes its newest max_posts posts, later runs only what is newer;
  * refuses invite links, private channels, groups and supergroups;
  * never sends, forwards, reacts, joins, adds contacts or opens bot chats: those requests are
    blocked inside the client (ReadOnlyTelegramClient), not just left unused;
  * rate-limited (requests_per_minute for history pages and image downloads) and honours FloodWait;
  * images are downloaded to memory, read with Tesseract (hin+eng) and discarded; no media is stored.

The output is raw data with phone numbers and UPI IDs in it: it is written owner-readable only and
should go through `python -m pii.redact` before anyone else sees it (see README).
API id / hash come from research/.env (TELEGRAM_API_ID, TELEGRAM_API_HASH).
"""
import argparse
import asyncio
import contextlib
import io
import json
import logging
import os
import re
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from common.io import load_env, write_jsonl

log = logging.getLogger("collect.telegram")

_USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")


# --------------------------------------------------------------------------- config

class ConfigError(ValueError):
    pass


def normalize_username(entry: str) -> str:
    """'@name', 't.me/name', 'https://t.me/s/name' -> 'name'. Invite links are rejected."""
    s = (entry or "").strip()
    if re.search(r"(joinchat/|t\.me/\+|^\+)", s):
        raise ConfigError(f"{entry!r} is an invite link: only public channels can be collected")
    s = re.sub(r"^(https?://)?(www\.)?(t|telegram)\.me/(s/)?", "", s).lstrip("@").strip("/")
    s = s.split("/")[0].split("?")[0]
    if not _USERNAME.match(s):
        raise ConfigError(f"{entry!r} is not a public channel username")
    return s


COLLECTABLE_LABELS = {"likely_fraud", "likely_legit"}


def is_approved(item: dict) -> bool:
    """Entries written by discover_channels carry a label and approved: false. They are collected only
    after a person sets approved: true, and only if labelled likely_fraud or likely_legit. Entries
    added to channels.yaml by hand (no label, no approved key) were chosen by a person already."""
    if "approved" not in item and "label" not in item:
        return True
    return item.get("approved") is True and item.get("label") in COLLECTABLE_LABELS


def load_config(path, approved_only: bool = False) -> dict:
    """approved_only: only entries a person marked approved: true (hand-written entries without the key are
    left out too)."""
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    settings = {"max_posts_per_channel": 5000, "requests_per_minute": 20, "pause_between_channels_s": 10,
                "ocr_images": True, "ocr_lang": "hin+eng", "max_image_bytes": 5_000_000}
    settings.update(cfg.get("settings") or {})
    if settings["requests_per_minute"] <= 0 or settings["requests_per_minute"] > 60:
        raise ConfigError("requests_per_minute must be between 1 and 60")
    channels, seen = [], set()
    for item in cfg.get("channels") or []:
        item = {"username": item} if isinstance(item, str) else dict(item)
        if not is_approved(item) or (approved_only and item.get("approved") is not True):
            continue
        name = normalize_username(item.get("username", ""))
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        since = item.get("since")
        if isinstance(since, str):
            since = date.fromisoformat(since)
        channels.append({"username": name, "since": since, "reason": item.get("reason", ""),
                         "label": item.get("label")})
    return {"channels": channels, "settings": settings}


# --------------------------------------------------------------------------- rate limit

class RateLimiter:
    """At most `per_minute` calls per minute, evenly spaced."""

    def __init__(self, per_minute: float, clock=time.monotonic, sleep=asyncio.sleep):
        self.interval = 60.0 / per_minute
        self.clock, self.sleep = clock, sleep
        self._next = 0.0

    async def wait(self):
        now = self.clock()
        if now < self._next:
            await self.sleep(self._next - now)
            now = self._next
        self._next = now + self.interval


# --------------------------------------------------------------------------- read-only client

def blocked_request_types():
    """Telegram API requests this collector must never send."""
    from telethon.tl.functions import channels, contacts, messages
    names = [
        (channels, "JoinChannelRequest"), (channels, "InviteToChannelRequest"), (channels, "CreateChannelRequest"),
        (messages, "ImportChatInviteRequest"), (messages, "CheckChatInviteRequest"),
        (messages, "SendMessageRequest"), (messages, "SendMediaRequest"), (messages, "SendMultiMediaRequest"),
        (messages, "ForwardMessagesRequest"), (messages, "SendReactionRequest"), (messages, "StartBotRequest"),
        (messages, "SendInlineBotResultRequest"), (messages, "SendVoteRequest"), (messages, "CreateChatRequest"),
        (messages, "AddChatUserRequest"), (messages, "ReadHistoryRequest"), (messages, "GetMessagesViewsRequest"),
        (channels, "ReadHistoryRequest"), (contacts, "AddContactRequest"), (contacts, "ImportContactsRequest"),
        (contacts, "BlockRequest"),
    ]
    return tuple(getattr(mod, n) for mod, n in names if hasattr(mod, n))


class ReadOnlyViolation(RuntimeError):
    pass


def make_client(session: str, api_id: int, api_hash: str, flood_sleep_threshold: int = 300):
    from telethon import TelegramClient

    blocked = blocked_request_types()

    class ReadOnlyTelegramClient(TelegramClient):
        async def __call__(self, request, ordered=False, flood_sleep_threshold=None):
            reqs = request if isinstance(request, (list, tuple)) else [request]
            for r in reqs:
                if isinstance(r, blocked):
                    raise ReadOnlyViolation(f"{type(r).__name__} is not allowed in the research collector")
            return await super().__call__(request, ordered, flood_sleep_threshold)

    # flood_sleep_threshold: Telethon sleeps through FloodWaits up to this many seconds by itself
    return ReadOnlyTelegramClient(session, api_id, api_hash, flood_sleep_threshold=flood_sleep_threshold)


@contextlib.contextmanager
def telegram_lock(path: str = "store/telegram.lock"):
    """Only one Telegram job (collector or discovery) at a time on this machine."""
    import fcntl
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        raise SystemExit(f"another Telegram job is running ({path}); wait for it to finish")
    try:
        f.write(str(os.getpid()))
        f.flush()
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def is_public_channel(entity) -> bool:
    """Public broadcast channel with a username. Groups and supergroups are excluded on purpose:
    their posts are written by ordinary members, not by an advertiser."""
    from telethon.tl.types import Channel
    return (isinstance(entity, Channel) and bool(getattr(entity, "username", None))
            and bool(getattr(entity, "broadcast", False)) and not getattr(entity, "megagroup", False))


# --------------------------------------------------------------------------- records

def media_type(msg) -> str:
    if getattr(msg, "photo", None):
        return "photo"
    if getattr(msg, "video", None) or getattr(msg, "gif", None):
        return "video"
    if getattr(msg, "voice", None) or getattr(msg, "audio", None):
        return "audio"
    if getattr(msg, "sticker", None):
        return "sticker"
    if getattr(msg, "poll", None):
        return "poll"
    if getattr(msg, "web_preview", None):
        return "webpage"
    if getattr(msg, "document", None):
        mime = getattr(msg.document, "mime_type", "") or ""
        return "image_document" if mime.startswith("image/") else "document"
    return "none" if getattr(msg, "media", None) is None else "other"


def image_size(msg) -> int:
    if getattr(msg, "document", None) is not None:
        return int(getattr(msg.document, "size", 0) or 0)
    photo = getattr(msg, "photo", None)
    sizes = getattr(photo, "sizes", None) or []
    best = 0
    for s in sizes:
        best = max(best, int(getattr(s, "size", 0) or 0), *[int(x) for x in (getattr(s, "sizes", None) or [0])])
    return best


def to_record(msg, channel: str, ocr_text: str = "") -> dict:
    d = msg.date if msg.date.tzinfo else msg.date.replace(tzinfo=timezone.utc)
    return {
        "post_id": f"tg:{channel.lower()}:{msg.id}",
        "message_id": msg.id,
        "channel": channel.lower(),
        "date": d.astimezone(timezone.utc).isoformat(),
        "text": msg.message or "",
        "media_type": media_type(msg),
        "ocr_text": ocr_text,
        "views": getattr(msg, "views", None),
        "forwards": getattr(msg, "forwards", None),
        "edited": bool(getattr(msg, "edit_date", None)),
        "source": "telegram_public",
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def ocr_bytes(data: bytes, lang: str = "hin+eng") -> str:
    import pytesseract
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as im:
            im = im.convert("RGB")
            return re.sub(r"[ \t]+", " ", pytesseract.image_to_string(im, lang=lang)).strip()
    except Exception as e:      # unreadable image or Tesseract missing: keep the post, skip its text
        log.warning("OCR failed: %s", e)
        return ""


# --------------------------------------------------------------------------- state

def load_state(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
    tmp.replace(path)


# --------------------------------------------------------------------------- collection

async def collect_channel(client, ch: dict, settings: dict, limiter: RateLimiter, last_id: int, out: Path) -> int:
    from telethon.errors import (ChannelInvalidError, ChannelPrivateError, FloodWaitError,
                                 UsernameInvalidError, UsernameNotOccupiedError)
    name = ch["username"]
    await limiter.wait()
    try:
        entity = await client.get_entity(name)
    except (UsernameNotOccupiedError, UsernameInvalidError, ChannelPrivateError, ChannelInvalidError, ValueError) as e:
        log.warning("skip %s: %s", name, type(e).__name__)
        return last_id
    if not is_public_channel(entity):
        log.warning("skip %s: not a public broadcast channel", name)
        return last_id

    # Telethon fetches history in pages of 100; wait_time spaces those page requests
    kwargs = {"limit": settings["max_posts_per_channel"], "wait_time": 60.0 / settings["requests_per_minute"]}
    first_pass = not last_id and not ch.get("since")
    if last_id:
        kwargs["min_id"] = last_id
    elif ch.get("since"):
        kwargs["offset_date"] = datetime.combine(ch["since"], datetime.min.time(), tzinfo=timezone.utc)

    async def messages():
        if first_pass:          # the newest max_posts posts, written oldest first; later runs continue from there
            page = [m async for m in client.iter_messages(entity, **kwargs)]
            for m in reversed(page):
                yield m
        else:                   # forward from the cursor (or the since date)
            async for m in client.iter_messages(entity, reverse=True, **kwargs):
                yield m

    n, newest, batch = 0, last_id, []
    try:
        async for msg in messages():
            if getattr(msg, "action", None):          # service messages (pinned, title changed ...)
                continue
            ocr = ""
            kind = media_type(msg)
            if settings["ocr_images"] and kind in ("photo", "image_document") \
                    and image_size(msg) <= settings["max_image_bytes"]:
                await limiter.wait()
                data = await client.download_media(msg, file=bytes)
                ocr = ocr_bytes(data, settings["ocr_lang"]) if data else ""
                del data
            rec = to_record(msg, name, ocr)
            if ch.get("label"):
                rec["channel_label"] = ch["label"]      # discovery label: likely_fraud / likely_legit
            batch.append(rec)
            newest = max(newest, msg.id)
            n += 1
            if len(batch) >= 100:
                write_jsonl(out, batch, append=True, private=True)
                batch = []
    except FloodWaitError as e:                       # longer than flood_sleep_threshold: stop this channel
        log.warning("FloodWait %ss on %s; stopping this channel for now", e.seconds, name)
    finally:
        if batch:
            write_jsonl(out, batch, append=True, private=True)
    log.info("%s: %d new posts (last id %s)", name, n, newest)
    return newest


async def run(config_path: str, out_path: str, state_path: str, approved_only: bool = False,
              max_posts: int | None = None) -> None:
    load_env()
    cfg = load_config(config_path, approved_only=approved_only)
    if not cfg["channels"]:
        raise SystemExit(f"no {'approved ' if approved_only else ''}channels in {config_path}")
    if max_posts:
        cfg["settings"]["max_posts_per_channel"] = max_posts
    log.info("%d channels (%s), at most %d posts each per run, %s requests/min", len(cfg["channels"]),
             ", ".join(f"{k} {v}" for k, v in sorted(Counter(c.get("label") or "hand-picked"
                                                               for c in cfg["channels"]).items())),
             cfg["settings"]["max_posts_per_channel"], cfg["settings"]["requests_per_minute"])
    api_id, api_hash = os.environ.get("TELEGRAM_API_ID"), os.environ.get("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        raise SystemExit("set TELEGRAM_API_ID and TELEGRAM_API_HASH in research/.env")
    session = os.environ.get("TELEGRAM_SESSION", "store/telegram_research.session")
    Path(session).parent.mkdir(parents=True, exist_ok=True)

    out, state_file = Path(out_path), Path(state_path)
    state = load_state(state_file)
    limiter = RateLimiter(cfg["settings"]["requests_per_minute"])
    client = make_client(session, int(api_id), api_hash)
    with telegram_lock():
        async with client:
            for i, ch in enumerate(cfg["channels"]):
                if i:
                    await asyncio.sleep(cfg["settings"]["pause_between_channels_s"])
                key = ch["username"].lower()
                state[key] = await collect_channel(client, ch, cfg["settings"], limiter, state.get(key, 0), out)
                save_state(state_file, state)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", default="config/channels.yaml")
    ap.add_argument("--out", default="store/raw/telegram.jsonl")
    ap.add_argument("--state", default="store/raw/telegram_state.json",
                    help="last message id per channel, so reruns only fetch new posts")
    ap.add_argument("--approved-only", action="store_true",
                    help="only entries marked approved: true (e.g. by collect.apply_review)")
    ap.add_argument("--max-posts", type=int, default=None,
                    help="posts per channel per run (default: settings.max_posts_per_channel). On a channel's "
                         "first run these are its newest posts")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    if args.max_posts is not None and args.max_posts <= 0:
        raise SystemExit("--max-posts must be positive")
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("telethon").setLevel(logging.WARNING)
    asyncio.run(run(args.config, args.out, args.state, args.approved_only, args.max_posts))


if __name__ == "__main__":
    main()
