"""Citizen reporting bot for Telegram.

People forward a suspicious message, send a link, a screenshot or just type what they saw. The bot
checks it with the same engine as the command center, replies with a verdict and safety advice in
English and Hindi, and files it as a case (identical reports are grouped on one case). When an
investigator confirms a case, marks it a false positive or gets it taken down, everyone who reported
it is told.

Runs inside the command center with long polling, so it works from a laptop with no public URL.
Token: REPORT_BOT_TOKEN (or TELEGRAM_BOT_TOKEN) in .env.
"""
import hashlib
import html
import os
import secrets
import re
import threading
import time
import traceback
from collections import defaultdict, deque
from datetime import datetime

import requests

from .config import MEDIA_DIR, REPORT_BOT_TOKEN, REPORTS_PER_HOUR
from .db import Post, Report, SessionLocal

MAX_FILE = 8 * 1024 * 1024
URL_RX = re.compile(r"(?:https?://|www\.|t\.me/)\S+", re.I)

# one-time code shown in the command center; whoever sends "/alerts <code>" gets the alerts
ALERT_CODE = f"{secrets.randbelow(900000) + 100000}"

_status = {"enabled": bool(REPORT_BOT_TOKEN), "running": False, "username": "", "name": "",
           "last_update": None, "last_error": "", "handled": 0}


def status() -> dict:
    return dict(_status)


# ----------------------------------------------------------------------------- Telegram transport

class TelegramAPI:
    def __init__(self, token: str):
        # TELEGRAM_API_BASE: a self-hosted Bot API server (or a local mock for testing)
        root = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
        self.base = f"{root}/bot{token}"
        self.file_base = f"{root}/file/bot{token}"

    def call(self, method: str, http_timeout=15, **params):
        r = requests.post(f"{self.base}/{method}", json=params, timeout=http_timeout)
        d = r.json()
        if not d.get("ok"):
            raise RuntimeError(d.get("description", f"{method} failed"))
        return d["result"]

    def send(self, chat_id, text: str, reply_to=None):
        params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        if reply_to:
            params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        try:
            return self.call("sendMessage", **params)
        except Exception:
            params.pop("reply_parameters", None)          # older Bot API servers
            return self.call("sendMessage", **params)

    def typing(self, chat_id):
        try:
            self.call("sendChatAction", chat_id=chat_id, action="typing")
        except Exception:
            pass

    def download(self, file_id: str) -> bytes:
        f = self.call("getFile", file_id=file_id)
        if f.get("file_size", 0) > MAX_FILE:
            raise RuntimeError("file too large")
        r = requests.get(f"{self.file_base}/{f['file_path']}", timeout=30)
        r.raise_for_status()
        return r.content


# ----------------------------------------------------------------------------- message texts

WELCOME = (
    "👋 <b>MuleWatch — report suspicious financial ads</b>\n\n"
    "Saw someone <b>selling or renting bank accounts, ATM cards, SIM + passbook \"kits\"</b>, or offering easy money "
    "for using your account? Send it here:\n"
    "• <b>forward</b> the message or post,\n"
    "• send a <b>link</b> to it, or\n"
    "• send a <b>screenshot</b>.\n\n"
    "I'll check it in a few seconds and pass it to investigators. Your identity is not shown to anyone.\n\n"
    "🇮🇳 बैंक खाता, एटीएम कार्ड या \"किट\" बेचने/किराये पर लेने का कोई संदेश दिखे तो उसे यहाँ फ़ॉरवर्ड करें, "
    "लिंक या स्क्रीनशॉट भेजें। हम तुरंत जाँच करेंगे।\n\n"
    "Commands: /status — your recent reports · /help\n"
    "Lost money? Call <b>1930</b> or report at cybercrime.gov.in"
)

HELP = (
    "<b>How to report</b>\n"
    "1. Long-press the suspicious message → Forward → choose this bot. Or paste a link, or send a screenshot.\n"
    "2. I reply with a risk level and the reasons.\n"
    "3. Investigators review it; I'll message you if they act on it.\n\n"
    "/status shows your last 5 reports.\n"
    "Never share your OTP, PIN, ATM card or bank account with anyone. Renting out your account is a crime "
    "(you become a money mule).\n"
    "पैसे गँवाए हैं? तुरंत <b>1930</b> पर कॉल करें या cybercrime.gov.in पर शिकायत करें।"
)

ADVICE = {
    "Critical": "⛔ Don't contact them, don't pay, and never give your bank account, ATM card, SIM or OTP to anyone. "
                "Selling or renting an account is a crime.\n"
                "संपर्क न करें, पैसे न दें, अपना खाता/कार्ड/OTP किसी को न दें।",
    "High": "⚠️ Treat this as a scam. Don't share your bank or card details and don't pay anything up front.\n"
            "इसे धोखाधड़ी मानें — बैंक या कार्ड की जानकारी साझा न करें।",
    "Medium": "Be careful: some warning signs are present. Investigators will take a look.\n"
              "सावधान रहें — कुछ संदिग्ध संकेत हैं।",
    "Low": "I didn't find signs of bank-account or card selling in this message. Investigators can still see your "
           "report. If someone asked for your OTP, PIN or card details, or you lost money, call <b>1930</b> now.\n"
           "खाता/कार्ड बेचने के संकेत नहीं मिले। अगर किसी ने OTP, PIN या कार्ड नंबर माँगा या पैसे कटे हैं, तो तुरंत 1930 पर कॉल करें।",
}
HEAD = {"Critical": "🚨 <b>Very likely a scam</b>", "High": "⚠️ <b>Likely a scam</b>",
        "Medium": "🟡 <b>Suspicious</b>", "Low": "ℹ️ <b>No signs of account or card selling</b>"}

VICTIM_ADVICE = (
    "<b>What to do now</b>\n"
    "• Never share your card number, PIN, CVV or OTP. Banks and officials never ask for them.\n"
    "• If you shared anything or money was taken: call your bank to block the card/account, then call "
    "<b>1930</b> right away (the first hour matters) and file at cybercrime.gov.in.\n"
    "• Keep the caller's number, call log and screenshots as evidence.\n\n"
    "कार्ड नंबर, PIN, CVV या OTP कभी किसी को न बताएं। अगर बता दिया है या पैसे कटे हैं, तो तुरंत बैंक से कार्ड ब्लॉक "
    "करवाएं और 1930 पर कॉल करें।"
)


def case_id(pid: int) -> str:
    return f"MW-{pid:05d}"


def verdict_text(p: Post, reports_count: int, already: bool) -> str:
    e = lambda s: html.escape(str(s))
    if p.category == "Reported Fraud Attempt":
        lines = ["🛡️ <b>Thank you. This is a fraud attempt.</b>", f"Case <b>{case_id(p.id)}</b> has been sent to investigators."]
        cues = next((r.split(": ", 1)[1] for r in (p.reasons or []) if r.startswith("Fraud attempt reported")), "")
        if cues:
            lines.append("\n<b>What you described:</b> " + e(cues))
        ents = p.entities or {}
        nums = [*ents.get("phone", [])[:2], *ents.get("phone_like", [])[:1], *ents.get("upi", [])[:1]]
        if nums:
            lines.append("<b>Numbers noted:</b> " + ", ".join(f"<code>{e(n)}</code>" for n in nums))
        lines.append("\n" + VICTIM_ADVICE)
        return "\n".join(lines)
    head = HEAD.get(p.risk_level, "") if p.risk_level == "Low" else \
        f"{HEAD.get(p.risk_level, '')} — {e(p.category)}  ({p.risk_score:.0f}/100)"
    lines = [head, f"Case <b>{case_id(p.id)}</b>"]
    if already:
        lines.append(f"Already reported by {reports_count} {'person' if reports_count == 1 else 'people'} — "
                     "thank you, your report was added to the same case.")
    reasons = [r for r in (p.reasons or []) if not r.startswith("Posted as a comment")][:4]
    if reasons and p.risk_level != "Low":
        lines.append("\n<b>Why:</b>")
        lines += [f"• {e(r[:160])}" for r in reasons]
    ents = p.entities or {}
    ids = [*ents.get("phone", [])[:2], *ents.get("upi", [])[:2], *ents.get("telegram", [])[:2],
           *ents.get("whatsapp", [])[:1]]
    if ids and p.risk_level != "Low":
        lines.append("<b>Details found:</b> " + ", ".join(f"<code>{e(i)}</code>" for i in ids))
    if (p.cluster_size or 1) > 1 and p.risk_level != "Low":
        lines.append(f"🔗 Linked to {p.cluster_size - 1} other post{'s' if p.cluster_size > 2 else ''} "
                     "from the same seller network.")
    lines.append("\n" + ADVICE.get(p.risk_level, ""))
    if p.risk_level != "Low":
        lines.append("\nLost money? Call <b>1930</b> · cybercrime.gov.in")
    return "\n".join(lines)


UPDATE_TEXT = {
    "confirmed": "✅ Update on your report <b>{cid}</b>: investigators have <b>confirmed it as fraud</b>. "
                 "Thank you for reporting — you may have protected someone.\nआपकी रिपोर्ट सही पाई गई। धन्यवाद!",
    "false_positive": "ℹ️ Update on your report <b>{cid}</b>: investigators reviewed it and found it was "
                      "<b>not fraud</b>. Thanks for staying alert.",
    "takedown": "🚔 Update on your report <b>{cid}</b>: the post has been <b>taken down for review</b> by the "
                "Cyber Cell. Thank you!\nपोस्ट हटाने की कार्रवाई की गई है। धन्यवाद!",
}


# ----------------------------------------------------------------------------- core handling

_rate = defaultdict(deque)


def _rate_ok(chat_id) -> bool:
    q, now = _rate[chat_id], time.time()
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= REPORTS_PER_HOUR:
        return False
    q.append(now)
    return True


def _origin(msg: dict) -> tuple[str, str]:
    """(human readable origin, extra text that lets the engine link it, e.g. t.me/<channel>)."""
    fo = msg.get("forward_origin") or {}
    chat = fo.get("chat") or msg.get("forward_from_chat") or {}
    if chat:
        uname = chat.get("username")
        title = chat.get("title", "")
        kind = "channel" if (fo.get("type") == "channel" or chat.get("type") == "channel") else "group"
        return (f"Forwarded from {kind} {title}" + (f" (@{uname})" if uname else ""),
                f"t.me/{uname}" if uname else "")
    user = fo.get("sender_user") or msg.get("forward_from") or {}
    if user:
        uname = user.get("username")
        name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x)
        return f"Forwarded from {name}" + (f" (@{uname})" if uname else ""), (f"@{uname}" if uname else "")
    hidden = fo.get("sender_user_name") or msg.get("forward_sender_name")
    if hidden:
        return f"Forwarded from {hidden}", ""
    return "Sent directly to the bot", ""


def _reporter_hash(chat_id) -> str:
    return hashlib.sha256(f"mulewatch-reporter-{chat_id}".encode()).hexdigest()[:10]


def handle_update(update: dict, tg) -> None:
    from .pipeline import ingest
    msg = update.get("message")
    if not msg or msg.get("chat", {}).get("type") != "private":
        return
    chat_id = msg["chat"]["id"]
    mid = msg.get("message_id")
    text = (msg.get("text") or msg.get("caption") or "").strip()

    if text.startswith("/start"):
        tg.send(chat_id, WELCOME)
        return
    if text.startswith("/help"):
        tg.send(chat_id, HELP)
        return
    if text.startswith("/status"):
        tg.send(chat_id, _status_text(chat_id))
        return
    if text.startswith("/alerts"):
        tg.send(chat_id, _link_alerts(chat_id, text.split()[1:], msg))
        return
    if text.startswith("/officer"):
        tg.send(chat_id, _link_officer(chat_id, text.split()[1:]))
        return
    if text.startswith("/"):
        tg.send(chat_id, "Send me a suspicious message, link or screenshot. /help explains how.")
        return

    photo = msg.get("photo")
    doc = msg.get("document") if (msg.get("document") or {}).get("mime_type", "").startswith("image/") else None
    if not text and not photo and not doc:
        tg.send(chat_id, "Please forward the message, or send a link or a screenshot of it.", reply_to=mid)
        return
    if not _rate_ok(chat_id):
        tg.send(chat_id, "You've sent a lot of reports in the last hour. Please try again a bit later.", reply_to=mid)
        return
    tg.typing(chat_id)

    origin, link_hint = _origin(msg)
    image_path, extra_images, image_hash = "", [], ""
    if photo or doc:
        try:
            data = tg.download((photo[-1] if photo else doc)["file_id"])
            image_hash = hashlib.sha1(data).hexdigest()
            image_path = f"report_{image_hash[:12]}.jpg"
            (MEDIA_DIR / image_path).write_bytes(data)
        except Exception as e:
            tg.send(chat_id, f"I couldn't download that image ({html.escape(str(e))[:80]}). "
                             "Try sending it again or send the text.", reply_to=mid)
            if not text:
                return

    url, platform, author, posted_at, how = "", "Citizen report (Telegram)", "", None, ""
    urls = URL_RX.findall(text)
    if urls and len(URL_RX.sub("", text).strip()) < 40 and not image_path:
        # mostly a link: open it like the command center's link check
        from .crawler import _parse_dt
        from .fetcher import FetchError, fetch_url
        try:
            f = fetch_url(urls[0])
            url = f["final_url"]
            platform = f"Citizen report · {f['platform']}"
            author = f["author"]
            posted_at = _parse_dt(f["posted_at"])
            imgs = f["image_paths"]
            image_path, extra_images = (imgs[0], imgs[1:]) if imgs else ("", [])
            text = "\n".join(x for x in (text, f["text"]) if x)
            how = "link"
            if f["note"] and len(f["text"]) < 40 and not imgs:
                tg.send(chat_id, "That page needs a login, so I can only see the link itself. "
                                 "A screenshot or the forwarded message works better.", reply_to=mid)
        except FetchError as e:
            tg.send(chat_id, f"I couldn't open that link: {html.escape(str(e))}. "
                             "Please forward the message or send a screenshot instead.", reply_to=mid)
    if link_hint and link_hint not in text:
        text = (text + f"\n(forwarded from {link_hint})").strip()

    norm = re.sub(r"\s+", " ", re.sub(r"\d", "0", text.lower())).strip()
    key = hashlib.sha1(f"{norm}|{image_hash}".encode()).hexdigest()[:32]
    rhash = _reporter_hash(chat_id)
    name = (msg.get("from") or {}).get("first_name", "")[:80]

    with SessionLocal() as s:
        prev = s.query(Report).filter_by(content_key=key).order_by(Report.id).first()
        post = s.get(Post, prev.post_id) if prev else None
        already = post is not None
        if not post:
            post = ingest(s, text=text, platform=platform[:60], author=author, url=url, image_path=image_path,
                          extra_images=extra_images, posted_at=posted_at, source="citizen", use_llm=True)
            post.reasons = (post.reasons or []) + [f"Citizen report: {origin}" + (" (link opened)" if how else "")]
        if not s.query(Report).filter_by(post_id=post.id, reporter_hash=rhash).first():
            s.add(Report(post_id=post.id, chat_id=str(chat_id), reporter_hash=rhash, reporter_name=name,
                         content_key=key, origin=origin[:200]))
        s.commit()
        count = s.query(Report).filter_by(post_id=post.id).count()
        reply = verdict_text(post, count, already)
    tg.send(chat_id, reply, reply_to=mid)
    _status["handled"] += 1
    _status["last_update"] = datetime.utcnow().isoformat()


def _link_alerts(chat_id, args, msg) -> str:
    from .db import get_setting, set_setting
    if args and args[0].lower() == "off":
        if get_setting("alert_chat_id") == str(chat_id):
            set_setting("alert_chat_id", None)
            set_setting("alert_chat_name", None)
            return "🔕 Alerts turned off for this chat."
        return "This chat isn't receiving alerts."
    if not args or not secrets.compare_digest(args[0], ALERT_CODE):
        return ("To receive MuleWatch alerts here, send <code>/alerts</code> followed by the code shown on the "
                "command center (Monitored sources → Phone alerts).")
    who = (msg.get("from") or {}).get("first_name", "") or "this chat"
    set_setting("alert_chat_id", str(chat_id))
    set_setting("alert_chat_name", who[:60])
    return ("✅ Linked. This chat will now get MuleWatch <b>Critical</b> alerts (and watchlist hits).\n"
            "Send <code>/alerts off</code> to stop.")


def _link_officer(chat_id, args) -> str:
    """An officer links their own Telegram with the code from their profile in the command center."""
    from . import audit
    from .db import User
    if not args or not args[0].isdigit():
        return ("To get case alerts and the daily brief here, open the command center → your name → "
                "<b>Link Telegram</b>, then send <code>/officer</code> followed by the code shown there.")
    with SessionLocal() as s:
        u = s.query(User).filter(User.telegram_code == args[0], User.active).first()
        if not u:
            return "That code isn't valid any more. Get a new one from the command center."
        u.telegram_chat_id, u.telegram_code = str(chat_id), ""
        s.commit()
        audit.log(u, "user.telegram_linked")
        name = u.name
    return (f"✅ Linked to <b>{name}</b>. You'll get alerts for cases assigned to you"
            " (and the daily brief if you're a supervisor).")


def _status_text(chat_id) -> str:
    with SessionLocal() as s:
        rows = (s.query(Report, Post).join(Post, Post.id == Report.post_id)
                .filter(Report.chat_id == str(chat_id)).order_by(Report.id.desc()).limit(5).all())
        if not rows:
            return "You haven't reported anything yet. Forward a suspicious message to start."
        out = ["<b>Your recent reports</b>"]
        for r, p in rows:
            state = {"confirmed": "confirmed fraud", "false_positive": "not fraud"}.get(p.label or "", "under review")
            if p.takedown:
                state += ", taken down"
            out.append(f"• {case_id(p.id)} — {p.risk_level} ({p.risk_score:.0f}), {state}")
        return "\n".join(out)


def notify_reporters(post_id: int, event: str):
    """Tell everyone who reported this case what happened. Runs in the background."""
    if not REPORT_BOT_TOKEN or event not in UPDATE_TEXT:
        return

    def run():
        tg = TelegramAPI(REPORT_BOT_TOKEN)
        with SessionLocal() as s:
            chats = {r.chat_id for r in s.query(Report).filter_by(post_id=post_id).all()}
        for chat in chats:
            try:
                tg.send(chat, UPDATE_TEXT[event].format(cid=case_id(post_id)))
            except Exception:
                pass
    threading.Thread(target=run, daemon=True).start()


# ----------------------------------------------------------------------------- polling loop

def _loop():
    tg = TelegramAPI(REPORT_BOT_TOKEN)
    offset = None
    backoff = 2
    while True:
        try:
            if not _status["username"]:
                me = tg.call("getMe")
                _status.update(username=me.get("username", ""), name=me.get("first_name", ""), last_error="")
                try:
                    tg.call("setMyCommands", commands=[
                        {"command": "start", "description": "How to report a suspicious ad"},
                        {"command": "status", "description": "Your recent reports"},
                        {"command": "help", "description": "Help and safety tips"}])
                except Exception:
                    pass
            params = {"timeout": 25, "allowed_updates": ["message"]}
            if offset is not None:
                params["offset"] = offset
            updates = tg.call("getUpdates", http_timeout=35, **params)
            _status["running"], backoff = True, 2
            for u in updates:
                offset = u["update_id"] + 1
                try:
                    handle_update(u, tg)
                except Exception as e:
                    traceback.print_exc()
                    _status["last_error"] = f"{type(e).__name__}: {str(e)[:120]}"
                    chat = ((u.get("message") or {}).get("chat") or {}).get("id")
                    if chat:
                        try:
                            tg.send(chat, "Sorry, something went wrong checking that. Please try again.")
                        except Exception:
                            pass
        except Exception as e:
            _status["running"] = False
            _status["last_error"] = f"{type(e).__name__}: {str(e)[:160]}"
            time.sleep(backoff)
            backoff = min(60, backoff * 2)


def start():
    if REPORT_BOT_TOKEN and not getattr(start, "_started", False):
        start._started = True
        threading.Thread(target=_loop, daemon=True, name="report-bot").start()
