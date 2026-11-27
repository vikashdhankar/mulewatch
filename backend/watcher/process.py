"""Run one post through the pipeline and act on the result, through the command center's own code:

  LOW     stored in watch_posts only (masked text and hashes)
  MEDIUM  + a case (app.pipeline.ingest: entities, district, capture.txt) in the review queue
  HIGH    + an Alert row (the command center shows it live over /api/events) and a Telegram message to the
          duty officer chat linked in the command center (app.alerts), masked
Every Medium/High case also gets the raw post JSON as an evidence file (app.evidence, EvidenceFile with its
SHA-256), next to the capture.txt that ingest writes.

Logs carry channel, message id, route, score and category only: never post text or identifier values."""
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError

from app import audit, evidence
from app.alerts import alert_chat_id, alert_token, send_to_chat
from app.config import PUBLIC_BASE_URL
from app.db import Alert, SessionLocal, WatchIdent, WatchPost
from app.jurisdiction import place_mentions
from app.pipeline import WATCHER_SOURCE, ingest, recompute_all

from . import store
from .pipeline import (CATEGORY_LABEL, AlertView, case_level, classify, compute_signals, format_alert, reasons,
                       redact, risk_score, route)

log = logging.getLogger("watcher.process")


@dataclass
class Outcome:
    uid: str
    channel: str
    message_id: int
    route: str
    score: float
    category: str
    p: float
    watch_post_id: int
    post_id: int | None = None
    alert_id: int | None = None
    pushed: bool | None = None          # None: no push attempted


def raw_bytes(raw: dict) -> bytes:
    """The raw post as stored in evidence; its SHA-256 is the post's hash of record."""
    return json.dumps(raw, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")


def utc_naive(iso: str) -> datetime:
    d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d


def default_sender(text: str) -> bool | None:
    """Send to the alert chat linked in the command center; None when no chat is linked."""
    chat = alert_chat_id()
    if not (alert_token() and chat):
        return None
    return send_to_chat(chat, text)


class Processor:
    def __init__(self, cfg: dict, redactor, model, llm=None, sender=default_sender, session_factory=SessionLocal,
                 places=place_mentions):
        self.cfg, self.redactor, self.model, self.llm = cfg, redactor, model, llm
        self.sender, self.Session, self.places = sender, session_factory, places
        self.dirty = False                # cases created since the last recompute
        self.counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "duplicate": 0, "history": 0}

    def handle(self, raw: dict, mode: str = "live", push: bool = True, history: bool = False) -> Outcome | None:
        """Process one post (collector record format). Returns None if it was processed before.
        history: score and store it (identifiers, channel rate) but raise no case or alert: posts from before a
        replay's demo window, so novelty and bursts in the window behave as they would live."""
        if history:
            mode, push = "history", False
        ch, mid = raw["channel"].lower(), int(raw["message_id"])
        uid = raw.get("post_id") or f"tg:{ch}:{mid}"
        raw = dict(raw, post_id=uid, channel=ch, link=raw.get("link") or f"https://t.me/{ch}/{mid}")
        with self.Session() as s:
            if store.seen(s, uid):
                self.counts["duplicate"] += 1
                return None
            red = redact(raw, self.redactor)
            cls = classify(red.model_text, self.model, self.cfg["llm"], self.llm)
            places = list(dict.fromkeys(self.places(red.text + "\n" + red.ocr_text)))
            posted_at = utc_naive(raw["date"])
            sig = compute_signals(red.keys, ch, posted_at, places, store.SqlHistory(s), self.cfg["risk"])
            score, parts = risk_score(cls, sig, self.cfg["risk"])
            level = route(score, self.cfg["risk"]["thresholds"])
            blob = raw_bytes(raw)
            wp = WatchPost(uid=uid, channel=ch, message_id=mid, link=raw["link"], posted_at=posted_at,
                           media_type=raw.get("media_type", ""), masked_text=red.text, masked_ocr=red.ocr_text,
                           category=cls.category, prob=cls.p, model=cls.model[:80], llm=cls.llm or {},
                           cues=list(cls.cues), score=score, route=level, ident_hashes=list(red.keys),
                           breakdown=parts | {"p_model": cls.p_model, "linked": sig.linked,
                                              "last_hour": sig.last_hour, "mean_hourly": sig.mean_hourly,
                                              "max_channels": sig.max_channels, "places": list(sig.places)},
                           district=places[0] if places else "", raw_sha256=hashlib.sha256(blob).hexdigest(),
                           mode=mode)
            s.add(wp)
            try:
                s.flush()
            except IntegrityError:            # another process took it a moment ago
                s.rollback()
                self.counts["duplicate"] += 1
                return None
            for k in red.keys:
                s.add(WatchIdent(hash=k, kind=k.split(":", 1)[0], channel=ch, watch_post_id=wp.id, seen_at=posted_at))
            store.touch(s, ch, posted_at, mid)
            out = Outcome(uid, ch, mid, level, score, cls.category, cls.p, wp.id)
            message = None
            if level in ("HIGH", "MEDIUM") and not history:
                post = self._case(s, raw, blob, wp, cls, sig, parts, score, level)
                wp.post_id = out.post_id = post.id
                wp.district = (post.jurisdiction or {}).get("district") or wp.district
                self.dirty = True
                if level == "HIGH":
                    alert = Alert(post_id=post.id, level=post.risk_level,
                                  reason=(f"Telegram watcher: {CATEGORY_LABEL[cls.category]} in @{ch}, "
                                          f"score {score:.0f}")[:300])
                    s.add(alert)
                    s.flush()
                    out.alert_id = alert.id
                    stale = mode == "live" and datetime.utcnow() - posted_at > timedelta(
                        hours=self.cfg["alerts"].get("push_max_age_h", 24))
                    if push and not stale and self.cfg["alerts"].get("telegram", True):
                        message = format_alert(AlertView(
                            masked_text=red.text or red.ocr_text, category=cls.category, score=score, channel=ch,
                            link=raw["link"], district=wp.district, linked=sig.linked,
                            case_url=f"{PUBLIC_BASE_URL}/case/{post.id}", cues=list(cls.cues)),
                            self.cfg["alerts"]["max_text_chars"])
            s.commit()
            self.counts["history" if history else level] += 1
            if message is not None:
                out.pushed = self._push(out.alert_id, message)
        log.info("%s/%s -> %s %.0f %s p=%.2f%s", ch, mid, level, score, cls.category, cls.p,
                 f" case MW-{out.post_id:05d}" if out.post_id else "")
        return out

    def _case(self, s, raw, blob, wp, cls, sig, parts, score, level):
        """A command-center case through app.pipeline.ingest, scored with the watcher's result."""
        post = ingest(s, text=raw.get("text") or "", ocr_text=raw.get("ocr_text") or "", platform="Telegram",
                      author="@" + wp.channel, url=raw["link"], posted_at=wp.posted_at, source=WATCHER_SOURCE,
                      recompute=False)
        post.remote_id = wp.uid
        post.risk_score = score
        post.risk_level = case_level(level, score)
        post.category = CATEGORY_LABEL[cls.category]
        post.scores = dict(post.scores or {}, base=score, final=score, final_done=True, watcher={
            "route": level, "category": cls.category, "p": cls.p, "p_model": cls.p_model, "model": cls.model,
            "llm": cls.llm, "cues": list(cls.cues), "parts": parts, "watch_post_id": wp.id, "linked": sig.linked})
        post.reasons = reasons(cls, sig, parts) + list(post.reasons or [])
        f = evidence.case_dir(post.id) / "telegram_post.json"
        f.write_bytes(blob)
        ef = evidence._record(s, post, "post_json", f, raw["link"],
                              f"Telegram post as received by the watcher (JSON with UTC time and OCR text), "
                              f"collected {raw.get('collected_at') or datetime.utcnow().isoformat(timespec='seconds')}")
        s.flush()
        audit.log(None, "watcher.case_created", post.id,
                  {"route": level, "score": score, "category": cls.category, "link": raw["link"],
                   "raw_sha256": ef.sha256}, session=s)
        return post

    def _push(self, alert_id: int, message: str) -> bool | None:
        ok = self.sender(message)
        if ok is None:
            return None
        with self.Session() as s:
            a = s.get(Alert, alert_id)
            if a:
                a.channel, a.delivered = "telegram", bool(ok)
                s.commit()
        if not ok:
            log.warning("Telegram alert for alert %s was not delivered", alert_id)
        return bool(ok)

    def recompute(self, push: bool = True):
        """Rings, complaint matches and recruiter priority over all cases, after new cases arrived."""
        if not self.dirty:
            return
        with self.Session() as s:
            recompute_all(s, alert=True, push=push)
        self.dirty = False
