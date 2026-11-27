"""The watcher's state in the command center's database: channel cursors, processed posts and identifier hashes."""
from datetime import datetime

from sqlalchemy import func

from app.db import WatchChannel, WatchIdent, WatchPost, get_setting


class SqlHistory:
    """pipeline.History over the watch_* tables (earlier posts only: the current one isn't stored yet)."""

    def __init__(self, session):
        self.s = session

    def known(self, keys):
        return {h for (h,) in self.s.query(WatchIdent.hash).filter(WatchIdent.hash.in_(keys)).distinct()}

    def channels_of(self, keys):
        out: dict[str, set] = {}
        for h, ch in self.s.query(WatchIdent.hash, WatchIdent.channel).filter(WatchIdent.hash.in_(keys)).distinct():
            out.setdefault(h, set()).add(ch)
        return out

    def channel_times(self, channel, since, until):
        return [t for (t,) in self.s.query(WatchPost.posted_at).filter(
            WatchPost.channel == channel, WatchPost.posted_at >= since, WatchPost.posted_at <= until)]

    def channel_first_seen(self, channel):
        return self.s.query(func.min(WatchPost.posted_at)).filter(WatchPost.channel == channel).scalar()


def seen(session, uid: str) -> bool:
    return session.query(WatchPost.id).filter_by(uid=uid).first() is not None


def channel(session, username: str, label: str = "") -> WatchChannel:
    ch = session.query(WatchChannel).filter_by(username=username).first()
    if ch is None:
        ch = WatchChannel(username=username, label=label or "")
        session.add(ch)
        session.flush()
    elif label and ch.label != label:
        ch.label = label
    return ch


def paused(cfg: dict) -> bool:
    """The config flag, or the switch in the command center (Monitored sources -> Telegram watcher)."""
    return bool(cfg.get("paused")) or get_setting("watcher_paused") == "1"


def touch(session, channel_name: str, posted_at: datetime, message_id: int):
    ch = channel(session, channel_name)
    ch.posts_seen = (ch.posts_seen or 0) + 1
    ch.last_id = max(ch.last_id or 0, message_id)
    if not ch.last_post_at or posted_at > ch.last_post_at:
        ch.last_post_at = posted_at
