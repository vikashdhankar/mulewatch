"""Alerting: every High/Critical post becomes a dashboard alert; Telegram push if configured."""
import os
import threading

import requests

from .config import (ALERT_MIN_LEVEL, LEVEL_RANK, PUBLIC_BASE_URL, REPORT_BOT_TOKEN, TELEGRAM_BOT_TOKEN,
                     TELEGRAM_CHAT_ID)
from .db import Alert


def alert_token() -> str:
    return TELEGRAM_BOT_TOKEN or REPORT_BOT_TOKEN


def alert_chat_id() -> str:
    """TELEGRAM_CHAT_ID from .env, or the chat linked by sending /alerts <code> to the bot."""
    from .db import get_setting
    return TELEGRAM_CHAT_ID or get_setting("alert_chat_id")


def telegram_enabled() -> bool:
    return bool(alert_token() and alert_chat_id())


def _send_telegram(text: str) -> bool:
    try:
        root = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
        r = requests.post(f"{root}/bot{alert_token()}/sendMessage",
                          json={"chat_id": alert_chat_id(), "text": text, "parse_mode": "HTML",
                                "disable_web_page_preview": True}, timeout=10)
        return r.ok
    except requests.RequestException:
        return False


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def maybe_alert(session, post, watch_hits: list[str] | None = None, previous_level: str | None = None,
                push_allowed: bool = True):
    """Create an alert when a post newly reaches High/Critical (or hits the watchlist)."""
    rank = LEVEL_RANK.get(post.risk_level, 0)
    if rank < LEVEL_RANK["High"] and not watch_hits:
        return None
    if previous_level and LEVEL_RANK.get(previous_level, 0) >= rank and not watch_hits:
        return None
    if session.query(Alert).filter_by(post_id=post.id, level=post.risk_level).first():
        return None

    reason = "Watchlist hit: " + ", ".join(watch_hits) if watch_hits else (post.reasons or ["High risk"])[0]
    alert = Alert(post_id=post.id, level=post.risk_level, reason=reason[:300])
    session.add(alert)
    session.flush()

    push = watch_hits or rank >= LEVEL_RANK.get(ALERT_MIN_LEVEL, 3)
    if push and push_allowed and telegram_enabled():
        ents = post.entities or {}
        contacts = ", ".join((ents.get("phone", []) + ents.get("upi", []) + ents.get("telegram", []))[:4])
        msg = (f"🚨 <b>MuleWatch {post.risk_level} alert</b> — score {post.risk_score:.0f}\n"
               f"<b>{_esc(post.category)}</b> on {_esc(post.platform)}"
               + (f" (ring of {post.cluster_size} posts)" if post.cluster_size > 1 else "") + "\n\n"
               f"<i>{_esc((post.text or post.ocr_text or '')[:220])}</i>\n\n"
               f"Why: {_esc(reason[:160])}\n"
               + (f"Identifiers: {_esc(contacts)}\n" if contacts else "")
               + f"\n🔎 {PUBLIC_BASE_URL}/case/{post.id}")
        alert.channel = "telegram"
        aid = alert.id

        def worker():
            import time
            from .db import SessionLocal
            ok = _send_telegram(msg)
            time.sleep(1.5)          # let the request that created the alert commit first
            with SessionLocal() as s:
                a = s.get(Alert, aid)
                if a:
                    a.delivered = ok
                    s.commit()
        threading.Thread(target=worker, daemon=True).start()
    return alert


def send_to_chat(chat_id: str, text: str) -> bool:
    try:
        root = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
        r = requests.post(f"{root}/bot{alert_token()}/sendMessage",
                          json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                "disable_web_page_preview": True}, timeout=10)
        return r.ok
    except requests.RequestException:
        return False


def send_document(chat_id: str, filename: str, data: bytes, caption: str = "") -> bool:
    try:
        root = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
        r = requests.post(f"{root}/bot{alert_token()}/sendDocument",
                          data={"chat_id": chat_id, "caption": caption[:1000], "parse_mode": "HTML"},
                          files={"document": (filename, data, "application/pdf")}, timeout=30)
        return r.ok
    except requests.RequestException:
        return False


def officer_chats(session, roles=("SUPERVISOR",), user_ids=()) -> list[str]:
    """Telegram chats linked by officers (/officer <code>) with any of these roles, or these users."""
    from .db import User
    q = session.query(User).filter(User.active, User.telegram_chat_id != "")
    out = []
    for u in q.all():
        if u.role in roles or u.id in user_ids:
            out.append(u.telegram_chat_id)
    return out


def notify(session, post, reason: str, push: bool = True, chats: list[str] | None = None,
           level: str | None = None):
    """An alert that isn't tied to a risk level change (complaint match, reappearance, takedown clock).
    Shown in the command center; pushed to the alert chat and any officer chats given."""
    alert = Alert(post_id=post.id, level=level or post.risk_level, reason=reason[:300])
    session.add(alert)
    session.flush()
    if not push or not alert_token():
        return alert
    targets = set(chats or [])
    if alert_chat_id():
        targets.add(alert_chat_id())
    if not targets:
        return alert
    msg = (f"🚨 <b>MuleWatch</b> — case MW-{post.id:05d} ({_esc(post.category)}, score {post.risk_score:.0f})\n"
           f"{_esc(reason)}\n\n🔎 {PUBLIC_BASE_URL}/case/{post.id}")
    alert.channel = "telegram"
    aid = alert.id

    def worker():
        import time
        from .db import SessionLocal
        ok = all([send_to_chat(c, msg) for c in targets])
        time.sleep(1.5)
        with SessionLocal() as s:
            a = s.get(Alert, aid)
            if a:
                a.delivered = ok
                s.commit()
    threading.Thread(target=worker, daemon=True).start()
    return alert
