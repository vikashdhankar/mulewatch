"""Command-center side of the real-time Telegram watcher (backend/watcher): health, pause switch, the live
alert feed with district/category filters, officers' decisions on alerts, the identifier (entity) view, per-channel
burst charts, the PDF evidence pack with a Section 63 BSA certificate, and the export of decisions as labelled
data for research/.

Everything shown here comes from watch_* tables, which hold masked text and keyed hashes only."""
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import func

from . import audit, evidence, legal
from .auth import current_user, ip_of, require
from .config import ROOT_DIR
from .db import (Alert, AlertDecision, Post, SessionLocal, WatchChannel, WatchIdent, WatchPost, get_setting,
                 set_setting)

router = APIRouter(prefix="/api")
DECISIONS = {"confirm": "confirmed", "false_alarm": "false_positive", "needs_info": None}
CATEGORY_LABEL = {
    "payout_mule": "Payout Mule", "account_sale": "Account Sale", "usdt_p2p": "USDT P2P",
    "crypto_investment_scam": "Crypto Investment Scam", "task_job_scam": "Task/Job Scam",
    "legit_finance": "Legit Finance", "unrelated": "Unrelated",
}


def watcher_config() -> dict:
    p = Path(os.getenv("WATCHER_CONFIG") or ROOT_DIR / "backend" / "watcher" / "watcher.yaml")
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except OSError:
        return {}


def _iso(d):
    return d.isoformat() if d else None


# ----------------------------------------------------------------------------- health and pause

def health_report(s) -> dict:
    now = datetime.utcnow()
    cfg = watcher_config()
    beat = get_setting("watcher_heartbeat")
    age = (now - datetime.fromisoformat(beat)).total_seconds() if beat else None
    chans = []
    for c in s.query(WatchChannel).order_by(WatchChannel.username).all():
        overdue = max(0.0, (now - c.next_poll_at).total_seconds()) if c.next_poll_at else 0.0
        chans.append({"username": c.username, "label": c.label, "last_poll_at": _iso(c.last_poll_at),
                      "last_ok_at": _iso(c.last_ok_at), "next_poll_at": _iso(c.next_poll_at),
                      "interval_s": c.interval_s, "overdue_s": round(overdue), "last_error": c.last_error,
                      "posts_seen": c.posts_seen, "last_post_at": _iso(c.last_post_at)})
    recent = s.query(WatchPost.processed_at, WatchPost.posted_at).filter(WatchPost.mode == "live") \
        .order_by(WatchPost.id.desc()).limit(50).all()
    lags = sorted((a - b).total_seconds() for a, b in recent if a and b)
    day = now - timedelta(hours=24)
    by_route = dict(s.query(WatchPost.route, func.count(WatchPost.id)).filter(WatchPost.processed_at >= day,
                                                                               WatchPost.mode != "history")
                    .group_by(WatchPost.route).all())
    return {
        "paused": bool(cfg.get("paused")) or get_setting("watcher_paused") == "1",
        "paused_in_config": bool(cfg.get("paused")),
        "mode": get_setting("watcher_mode") or None, "heartbeat": beat or None,
        "heartbeat_age_s": round(age) if age is not None else None,
        "running": age is not None and age < 120 and get_setting("watcher_mode") != "replay_done",
        "queue_lag_s": max((c["overdue_s"] for c in chans), default=0),     # how far polling is behind schedule
        "processing_lag_s": round(lags[len(lags) // 2]) if lags else None,  # published -> processed, median
        "channels": chans,
        "last_24h": {k: by_route.get(k, 0) for k in ("HIGH", "MEDIUM", "LOW")},
        "review_queue": _queue(s).count(),
    }


@router.get("/watcher/health")
def health(u=Depends(current_user)):
    with SessionLocal() as s:
        return health_report(s)


@router.post("/watcher/pause")
def pause(request: Request, paused: bool = Body(..., embed=True), u=Depends(require("SUPERVISOR"))):
    set_setting("watcher_paused", "1" if paused else None)
    audit.log(u, "watcher.paused" if paused else "watcher.resumed", ip=ip_of(request))
    with SessionLocal() as s:
        return health_report(s)


# ----------------------------------------------------------------------------- alert feed and review queue

def _latest_decisions(s, post_ids) -> dict:
    out = {}
    if post_ids:
        for d in s.query(AlertDecision).filter(AlertDecision.post_id.in_(post_ids)).order_by(AlertDecision.id):
            out[d.post_id] = d
    return out


def _decision_dict(d):
    return {"decision": d.decision, "reviewer": d.reviewer, "at": _iso(d.at), "note": d.note} if d else None


def _queue(s):
    decided = s.query(AlertDecision.post_id)
    return s.query(WatchPost).filter(WatchPost.route == "MEDIUM", WatchPost.post_id.isnot(None),
                                     ~WatchPost.post_id.in_(decided))


def _row(w: WatchPost, alert, decision, case_level=None) -> dict:
    return {"watch_id": w.id, "post_id": w.post_id, "alert_id": alert.id if alert else None,
            "route": w.route, "level": case_level, "score": w.score, "category": w.category,
            "category_label": CATEGORY_LABEL.get(w.category, w.category), "p": w.prob, "cues": w.cues or [],
            "channel": w.channel, "link": w.link, "district": w.district, "posted_at": _iso(w.posted_at),
            "processed_at": _iso(w.processed_at), "text": (w.masked_text or w.masked_ocr or "")[:400],
            "breakdown": w.breakdown or {}, "identifiers": len(w.ident_hashes or []),
            "ident_hashes": list(w.ident_hashes or []), "mode": w.mode,
            "decision": _decision_dict(decision)}


@router.get("/watcher/alerts")
def watcher_alerts(district: str | None = None, category: str | None = None, route: str = "HIGH,MEDIUM",
                   decided: str | None = None, limit: int = Query(100, le=500), u=Depends(current_user)):
    """Watcher alerts, newest first. decided: 'no' = still to review, 'yes' = reviewed."""
    with SessionLocal() as s:
        q = s.query(WatchPost).filter(WatchPost.route.in_(route.split(",")), WatchPost.post_id.isnot(None))
        if district:
            q = q.filter(WatchPost.district == district)
        if category:
            q = q.filter(WatchPost.category.in_(category.split(",")))
        if decided in ("yes", "no"):
            ids = s.query(AlertDecision.post_id)
            q = q.filter(WatchPost.post_id.in_(ids) if decided == "yes" else ~WatchPost.post_id.in_(ids))
        rows = q.order_by(WatchPost.id.desc()).limit(limit).all()
        pids = [w.post_id for w in rows]
        alerts = {a.post_id: a for a in s.query(Alert).filter(Alert.post_id.in_(pids)).order_by(Alert.id.desc())} \
            if pids else {}
        levels = dict(s.query(Post.id, Post.risk_level).filter(Post.id.in_(pids)).all()) if pids else {}
        dec = _latest_decisions(s, pids)
        facets = s.query(WatchPost.district, WatchPost.category, func.count(WatchPost.id)) \
            .filter(WatchPost.route.in_(route.split(",")), WatchPost.post_id.isnot(None)) \
            .group_by(WatchPost.district, WatchPost.category).all()
        dist, cat = Counter(), Counter()
        for d_, c_, n in facets:
            dist[d_ or ""] += n
            cat[c_] += n
        return {"items": [_row(w, alerts.get(w.post_id), dec.get(w.post_id), levels.get(w.post_id)) for w in rows],
                "districts": sorted(([k, n] for k, n in dist.items() if k), key=lambda x: -x[1]),
                "unknown_district": dist.get("", 0),
                "categories": [[k, CATEGORY_LABEL.get(k, k), n] for k, n in cat.most_common()],
                "review_queue": _queue(s).count()}


# ----------------------------------------------------------------------------- decisions (any alert)

@router.post("/alerts/{aid}/decision")
def decide(aid: int, request: Request, decision: str = Body(...), note: str = Body(""), u=Depends(current_user)):
    """Confirm / False alarm / Needs info on an alert. Every decision is kept with reviewer and time; confirm and
    false alarm also set the case verdict (which retrains the command center's own classifier)."""
    from .pipeline import apply_feedback
    if decision not in DECISIONS:
        raise HTTPException(400, "decision must be confirm | false_alarm | needs_info")
    with SessionLocal() as s:
        a = s.get(Alert, aid)
        if not a:
            raise HTTPException(404)
        d = AlertDecision(alert_id=aid, post_id=a.post_id, decision=decision, reviewer=u.username,
                          reviewer_id=u.id, note=(note or "")[:300])
        s.add(d)
        a.seen = True
        post = s.get(Post, a.post_id)
        if post and DECISIONS[decision]:
            apply_feedback(s, post, DECISIONS[decision])
        s.commit()
        out = {"alert_id": aid, "post_id": a.post_id, **_decision_dict(d)}
    audit.log(u, "alert.decision", out["post_id"], {"alert": aid, "decision": decision}, ip_of(request))
    if DECISIONS[decision]:
        from . import reportbot
        reportbot.notify_reporters(out["post_id"], DECISIONS[decision])
    return out


@router.post("/watcher/queue/{pid}/decision")
def decide_case(pid: int, request: Request, decision: str = Body(...), note: str = Body(""),
                u=Depends(current_user)):
    """The same for a review-queue case (MEDIUM), which has no Alert row."""
    from .pipeline import apply_feedback
    if decision not in DECISIONS:
        raise HTTPException(400, "decision must be confirm | false_alarm | needs_info")
    with SessionLocal() as s:
        post = s.get(Post, pid)
        if not post:
            raise HTTPException(404)
        d = AlertDecision(alert_id=None, post_id=pid, decision=decision, reviewer=u.username, reviewer_id=u.id,
                          note=(note or "")[:300])
        s.add(d)
        if DECISIONS[decision]:
            apply_feedback(s, post, DECISIONS[decision])
        s.commit()
        out = {"alert_id": None, "post_id": pid, **_decision_dict(d)}
    audit.log(u, "alert.decision", pid, {"decision": decision, "queue": True}, ip_of(request))
    return out


@router.get("/posts/{pid}/decisions")
def decisions(pid: int, u=Depends(current_user)):
    with SessionLocal() as s:
        return [{"alert_id": d.alert_id, **_decision_dict(d)}
                for d in s.query(AlertDecision).filter_by(post_id=pid).order_by(AlertDecision.id)]


# ----------------------------------------------------------------------------- entities and bursts

@router.get("/watcher/entities")
def entities(limit: int = Query(30, le=200), u=Depends(current_user)):
    """Identifiers (keyed hashes) seen in the most channels and posts."""
    with SessionLocal() as s:
        rows = s.query(WatchIdent.hash, WatchIdent.kind, func.count(func.distinct(WatchIdent.channel)),
                       func.count(func.distinct(WatchIdent.watch_post_id)), func.min(WatchIdent.seen_at),
                       func.max(WatchIdent.seen_at)) \
            .group_by(WatchIdent.hash, WatchIdent.kind) \
            .order_by(func.count(func.distinct(WatchIdent.channel)).desc(),
                      func.count(func.distinct(WatchIdent.watch_post_id)).desc()).limit(limit).all()
        return [{"hash": h, "kind": k, "channels": c, "posts": p, "first_seen": _iso(f), "last_seen": _iso(la)}
                for h, k, c, p, f, la in rows]


@router.get("/watcher/entities/{key}")
def entity(key: str, u=Depends(current_user)):
    """One identifier hash: the channels and posts it appears in, and when it was first seen."""
    with SessionLocal() as s:
        ids = s.query(WatchIdent).filter_by(hash=key).order_by(WatchIdent.seen_at).all()
        if not ids:
            raise HTTPException(404, "This identifier hasn't been seen")
        posts = {w.id: w for w in s.query(WatchPost).filter(WatchPost.id.in_({i.watch_post_id for i in ids}))}
        dec = _latest_decisions(s, [w.post_id for w in posts.values() if w.post_id])
        per = defaultdict(lambda: {"posts": 0, "first_seen": None, "last_seen": None})
        for i in ids:
            c = per[i.channel]
            c["posts"] += 1
            c["first_seen"] = c["first_seen"] or _iso(i.seen_at)
            c["last_seen"] = _iso(i.seen_at)
        return {"hash": key, "kind": ids[0].kind, "first_seen": _iso(ids[0].seen_at),
                "first_channel": ids[0].channel, "channels": [{"channel": k, **v} for k, v in per.items()],
                "posts": [_row(posts[i.watch_post_id], None, dec.get(posts[i.watch_post_id].post_id))
                          for i in reversed(ids) if i.watch_post_id in posts]}


@router.get("/watcher/bursts")
def bursts(channel: str | None = None, hours: int = Query(72, le=24 * 14), u=Depends(current_user)):
    """Posts per hour for each channel (or one), with its 7-day hourly mean, ending at its newest post."""
    with SessionLocal() as s:
        names = [channel.lower()] if channel else \
            [c for (c,) in s.query(WatchPost.channel).group_by(WatchPost.channel)
             .order_by(func.count(WatchPost.id).desc()).limit(12)]
        out = []
        for ch in names:
            end = s.query(func.max(WatchPost.posted_at)).filter(WatchPost.channel == ch).scalar()
            if not end:
                continue
            end = end.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            start = end - timedelta(hours=hours)
            rows = s.query(WatchPost.posted_at, WatchPost.route).filter(
                WatchPost.channel == ch, WatchPost.posted_at >= min(start, end - timedelta(days=7))).all()
            counts, flagged = [0] * hours, [0] * hours
            for t, r in rows:
                if t >= start:
                    i = int((t - start).total_seconds() // 3600)
                    if 0 <= i < hours:
                        counts[i] += 1
                        flagged[i] += r in ("HIGH", "MEDIUM")
            week = sum(1 for t, _ in rows if t >= end - timedelta(days=7))
            first = min((t for t, _ in rows), default=end)
            span = max(1.0, min(168.0, (end - first).total_seconds() / 3600))
            mean = week / span
            out.append({"channel": ch, "start": _iso(start), "counts": counts, "flagged": flagged,
                        "mean_hourly": round(mean, 3), "peak": max(counts) if counts else 0,
                        "burst_hours": sum(1 for c in counts if c >= 3 and c > 3 * mean)})
        return out


# ----------------------------------------------------------------------------- PDF evidence pack

_MARKERS = ("# ", "## ", ">> ", "- ", "~~")


def _safe_line(s: str) -> str:
    s = legal._one_line(s, 2000)
    return ("· " + s) if s.startswith(_MARKERS) or s == "~~" else s


def evidence_text(s, post: Post, user, lang: str = "en") -> str:
    w = s.query(WatchPost).filter_by(post_id=post.id).first()
    files = evidence.verify(s, post.id)
    raw = next((f for f in files if f["kind"] == "post_json"), None)
    when = lambda d: d.strftime("%Y-%m-%d %H:%M:%S UTC") if d else "—"  # noqa: E731
    n = iter(range(1, 10))
    lines = [f"# EVIDENCE PACK — CASE MW-{post.id:05d}",
             f">> Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC",
             "", f"## {next(n)}. The post", "| Field | Value |", "|---|---|",
             f"| Source link | {_safe_line(post.url)} |",
             f"| Platform / channel | {_safe_line(post.platform)} {_safe_line(post.author)} |",
             f"| Published (UTC) | {when(post.posted_at)} |",
             f"| Captured (UTC) | {when(post.ingested_at)} |",
             f"| SHA-256 of the raw post | {raw['sha256'] if raw else (w.raw_sha256 if w else '—')} |",
             f"| Assessment | {_safe_line(post.category)}, risk {post.risk_score:.0f}/100 ({post.risk_level}) |"]
    if w:
        lines.append(f"| District (approximate) | {w.district or '—'} |")
    lines += ["", f"## {next(n)}. Text as observed"] + [_safe_line(x) for x in (post.text or "(none)").splitlines() if x.strip()]
    if post.ocr_text:
        lines += ["", f"## {next(n)}. Text read from the attached image (OCR)"] + \
                 [_safe_line(x) for x in post.ocr_text.splitlines() if x.strip()]
    lines += ["", f"## {next(n)}. Why it was flagged"] + [f"- {_safe_line(r)}" for r in (post.reasons or [])[:8]]
    lines += ["", f"## {next(n)}. Evidence files and hashes", "| File | Kind | Captured (UTC) | Intact | SHA-256 |",
              "|---|---|---|---|---|"]
    for f in files:
        lines.append(f"| {f['name']} | {f['kind']} | {(f['captured_at'] or '')[:19].replace('T', ' ')} | "
                     f"{'yes' if f['intact'] else 'NO'} | {f['sha256']} |")
    lines += ["", "To check a file: sha256sum <file> (Windows: certutil -hashfile <file> SHA256). The raw post "
              "(telegram_post.json) is the JSON exactly as received, with its UTC time stamps, link and OCR text.",
              "", f"## {next(n)}. Certificate", "The certificate below is a template: complete every highlighted field, "
              "then sign.", ""]
    return "\n".join(lines) + "\n" + legal.render(s, post, user, "bsa63", lang)


@router.get("/posts/{pid}/evidence-pack.pdf")
def evidence_pdf(pid: int, request: Request, lang: str = "en", u=Depends(require("IO"))):
    if lang not in ("en", "hi"):
        raise HTTPException(400, "lang must be en or hi")
    with SessionLocal() as s:
        post = s.get(Post, pid)
        if not post:
            raise HTTPException(404)
        pdf = legal.to_pdf(evidence_text(s, post, u, lang), "Evidence pack with Section 63 BSA certificate",
                           f"MW-{pid:05d}")
    sha = hashlib.sha256(pdf).hexdigest()
    audit.log(u, "evidence.pdf_exported", pid, {"sha256": sha, "bytes": len(pdf)}, ip_of(request))
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="MuleWatch-MW-{pid:05d}-evidence-pack.pdf"',
        "X-Pack-SHA256": sha})


# ----------------------------------------------------------------------------- decisions -> research labels

def export_feedback(s, out_dir: str | None = None) -> dict:
    """Officers' latest decision on each watcher case, as labelled data for research/:

      posts.jsonl      the posts, redacted (research pii format: placeholders + keyed hashes, no values)
      decisions.jsonl  every decided post: decision, watcher category (false alarm -> unrelated), research label
      gold.jsonl       annotate.importer gold format, only posts whose category maps to a research class
    Needs-info decisions are counted but not labelled. Reviewers appear as a short hash, not by name."""
    cfg = (watcher_config().get("classifier") or {})
    to_label, fa_label = cfg.get("research_label") or {}, cfg.get("false_alarm_label", "benign")
    out = Path(out_dir) if out_dir else ROOT_DIR / "research" / "store" / "annotations" / "watcher"
    out.mkdir(parents=True, exist_ok=True)
    latest = {}
    for d in s.query(AlertDecision).order_by(AlertDecision.id):
        latest[d.post_id] = d
    wps = {w.post_id: w for w in s.query(WatchPost).filter(WatchPost.post_id.in_(list(latest)))} if latest else {}
    posts, decs, gold, pending = [], [], [], 0
    for pid, d in latest.items():
        w = wps.get(pid)
        if not w:
            continue                      # an alert from another source (forum, URL check ...)
        if d.decision == "needs_info":
            pending += 1
            continue
        confirmed = d.decision == "confirm"
        category = w.category if confirmed else "unrelated"
        label = to_label.get(w.category) if confirmed else fa_label
        posts.append({"post_id": w.uid, "channel": w.channel, "date": w.posted_at.isoformat() + "+00:00",
                      "text": w.masked_text, "ocr_text": w.masked_ocr, "media_type": w.media_type,
                      "entities": [{"type": k.split(":", 1)[0], "hash": k.split(":", 1)[1]} for k in w.ident_hashes or []],
                      "source": "mulewatch_watcher", "redaction_version": 1})
        reviewer = hashlib.sha256(d.reviewer.encode()).hexdigest()[:8]
        decs.append({"post_id": w.uid, "decision": d.decision, "category": category, "label": label,
                     "model_category": w.category, "model_p": w.prob, "score": w.score, "reviewer": reviewer,
                     "reviewed_at": d.at.isoformat() + "+00:00"})
        if label:
            gold.append({"post_id": w.uid, "label": label, "language": None, "spans": [], "source": "watcher_review",
                         "n_annotators": 1})
    for name, rows in (("posts", posts), ("decisions", decs), ("gold", gold)):
        with open(out / f"{name}.jsonl", "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.chmod(out / f"{name}.jsonl", 0o600)
    return {"dir": str(out), "posts": len(posts), "gold": len(gold), "needs_info": pending}


@router.post("/watcher/feedback/export")
def export(request: Request, u=Depends(require("IO"))):
    with SessionLocal() as s:
        res = export_feedback(s)
    audit.log(u, "watcher.feedback_exported", detail={k: v for k, v in res.items() if k != "dir"}, ip=ip_of(request))
    return res | {"dir": re.sub(r"^.*?(research/)", r"\1", res["dir"])}
