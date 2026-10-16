"""MuleWatch command-center API."""
import asyncio
import io
import json
import uuid
from collections import Counter, defaultdict
from datetime import datetime

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image as PILImage
from sqlalchemy import func

from . import audit, auth, bulk, crawler, evidence, llm, masking, police_api, reportbot, workflow
from .alerts import telegram_enabled
from .auth import can, current_user, ip_of, require
from .config import LEVEL_RANK, MEDIA_DIR, ROOT_DIR
from .coordination import entity_keys
from .db import Alert, Post, Report, SessionLocal, Source, WatchItem, init_db
from .imaging import OCR_AVAILABLE
from .ml import model, retrain
from .pipeline import apply_feedback, ingest, recompute_all, training_samples
from .report import build_report

app = FastAPI(title="MuleWatch", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.middleware("http")(auth.auth_middleware)
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")
app.include_router(auth.router)
app.include_router(auth.users_router)
app.include_router(police_api.router)


@app.on_event("startup")
def startup():
    init_db()
    auth.ensure_demo_users()
    if not model().trained:
        with SessionLocal() as s:
            retrain(training_samples(s))
    with SessionLocal() as s:          # bring cases captured by an older version up to the current rules
        from .pipeline import rescore_all
        rescore_all(s, alert=True)
    crawler.ensure_default_sources()
    crawler.start()
    reportbot.start()
    workflow.start()
    bulk.start()            # carries on with any list left unfinished when the app stopped


# ----------------------------------------------------------------------------- serializers

def summary(p: Post) -> dict:
    return {
        "id": p.id, "platform": p.platform, "author": p.author, "url": p.url,
        "excerpt": (p.text or p.ocr_text or "")[:220], "image": f"/media/{p.image_path}" if p.image_path else None,
        "risk_score": p.risk_score, "risk_level": p.risk_level, "category": p.category,
        "cluster_id": p.cluster_id, "cluster_size": p.cluster_size, "label": p.label,
        "language": p.language, "source": p.source, "takedown": p.takedown,
        "posted_at": p.posted_at.isoformat() if p.posted_at else None,
        "ingested_at": p.ingested_at.isoformat() if p.ingested_at else None,
        "top_reason": (p.reasons or [""])[0],
        "status": p.status or "NEW", "assigned_to": p.assigned_to, "recruiter_score": p.recruiter_score or 0,
        "complaint_count": p.complaint_count or 0, "complaint_amount": p.complaint_amount or 0,
        "repost_of": p.repost_of, "district": (p.jurisdiction or {}).get("district", ""),
        "entities": {k: v[:3] for k, v in (p.entities or {}).items()
                     if k in ("phone", "upi", "telegram", "whatsapp", "bank_account")},
        "reports": getattr(p, "_reports", 0),
    }


def _attach_report_counts(s, posts):
    if not posts:
        return posts
    counts = dict(s.query(Report.post_id, func.count(Report.id)).filter(Report.post_id.in_([p.id for p in posts]))
                  .group_by(Report.post_id).all())
    for p in posts:
        p._reports = counts.get(p.id, 0)
    return posts


def detail(s, p: Post) -> dict:
    _attach_report_counts(s, [p])
    reps = s.query(Report).filter_by(post_id=p.id).order_by(Report.id).all() if p.id else []
    d = summary(p)
    d["citizen_reports"] = [{"reporter": "Reporter " + r.reporter_hash[:6], "origin": r.origin,
                             "at": r.created_at.isoformat()} for r in reps]
    rel_ids = [r["id"] for r in p.related or []]
    rel = {x.id: x for x in s.query(Post).filter(Post.id.in_(rel_ids)).all()} if rel_ids else {}
    d.update({
        "text": p.text, "ocr_text": p.ocr_text, "matches": p.matches, "entities": p.entities,
        "scores": p.scores, "reasons": p.reasons, "llm": p.llm, "evidence_hash": p.evidence_hash,
        "related": [summary(rel[r["id"]]) | {"why": r["why"]} for r in p.related or [] if r["id"] in rel],
    })
    return d


# ----------------------------------------------------------------------------- posts

@app.get("/api/posts")
def list_posts(request: Request, level: str | None = None, platform: str | None = None, category: str | None = None,
               q: str | None = None, cluster: int | None = None, label: str | None = None, source: str | None = None,
               status: str | None = None, assigned: str | None = None, complaints: bool = False,
               district: str | None = None,
               sort: str = "recent", limit: int = Query(50, le=500), offset: int = 0, u=Depends(current_user)):
    if q:
        audit.log(u, "cases.searched", detail={"q": q[:100]}, ip=ip_of(request))
    with SessionLocal() as s:
        qry = s.query(Post)
        if level:
            qry = qry.filter(Post.risk_level.in_(level.split(",")))
        if platform:
            qry = qry.filter(Post.platform.like(f"%{platform}%"))
        if category:
            qry = qry.filter(Post.category == category)
        if cluster is not None:
            qry = qry.filter(Post.cluster_id == cluster)
        if source:
            qry = qry.filter(Post.source == source)
        if label:
            qry = qry.filter(Post.label == (None if label == "pending" else label))
        if status:
            qry = qry.filter(Post.status.in_(status.split(",")))
        if assigned == "me":
            qry = qry.filter(Post.assigned_to == u.id)
        elif assigned == "none":
            qry = qry.filter(Post.assigned_to.is_(None))
        if complaints:
            qry = qry.filter(Post.complaint_count > 0)
        if district:
            qry = qry.filter(Post.jurisdiction.like(f'%"district": "{district.replace(chr(34), "")}"%'))
        if q:
            like = f"%{q}%"
            digits = "".join(c for c in q if c.isdigit())
            cond = (Post.text.like(like)) | (Post.ocr_text.like(like)) | (Post.author.like(like))
            if len(digits) >= 6:          # a number typed with or without spaces / +91
                cond = cond | Post.entities.like(f"%{digits[-10:]}%")
            qry = qry.filter(cond)
        qry = qry.filter(Post.source != "preview")
        total = qry.count()
        order = {"risk": [Post.risk_score.desc()],
                 "recruiter": [Post.recruiter_score.desc(), Post.risk_score.desc()]}.get(sort, [Post.id.desc()])
        rows = _attach_report_counts(s, qry.order_by(*order).offset(offset).limit(limit).all())
        return {"total": total, "items": [masking.apply(summary(p), u) for p in rows]}


_last_view: dict[tuple, float] = {}


def _log_view(u, pid: int, ip: str):
    """Case views go to the audit log; repeat views by the same person within 15 minutes are one entry
    (the page refreshes itself whenever new posts arrive)."""
    import time
    key = (u.username, pid)
    if time.time() - _last_view.get(key, 0) > 900:
        _last_view[key] = time.time()
        audit.log(u, "case.viewed", pid, ip=ip)


@app.get("/api/posts/{pid}")
def get_post(pid: int, request: Request, u=Depends(current_user)):
    with SessionLocal() as s:
        p = s.get(Post, pid)
        if not p:
            raise HTTPException(404)
        out = masking.apply(detail(s, p), u)
    _log_view(u, pid, ip_of(request))
    return out


@app.post("/api/posts/{pid}/feedback")
def feedback(pid: int, request: Request, label: str = Body(..., embed=True), u=Depends(current_user)):
    if label not in ("confirmed", "false_positive", "clear"):
        raise HTTPException(400, "label must be confirmed | false_positive | clear")
    with SessionLocal() as s:
        p = s.get(Post, pid)
        if not p:
            raise HTTPException(404)
        apply_feedback(s, p, None if label == "clear" else label)
        s.commit()
        if label in ("confirmed", "false_positive"):
            reportbot.notify_reporters(pid, label)
        out = masking.apply(detail(s, s.get(Post, pid)), u)
    audit.log(u, "case.verdict", pid, {"label": label}, ip_of(request))
    return out


@app.post("/api/posts/{pid}/takedown")
def takedown(pid: int, request: Request, u=Depends(require("IO"))):
    """The demo forum's moderation API stands in for the platform acting on a notice: the content is
    removed at once, so the case moves to Content removed (and its removal clock stops)."""
    from datetime import datetime as _dt
    with SessionLocal() as s:
        p = s.get(Post, pid)
        if not p:
            raise HTTPException(404)
        ok, msg = crawler.request_takedown(p)
        if ok:
            p.takedown = "requested"
            now = _dt.utcnow()
            if not p.notice_sent_at:
                p.notice_sent_at = now
            p.status, p.removed_at, p.status_changed_at = "CONTENT_REMOVED", now, now
            s.commit()
            reportbot.notify_reporters(pid, "takedown")
            recompute_all(s, alert=True)
    audit.log(u, "case.takedown_requested", pid, {"ok": ok, "message": msg[:150]}, ip_of(request))
    return {"ok": ok, "message": msg}


@app.get("/api/posts/{pid}/report.pdf")
def report(pid: int, request: Request, u=Depends(current_user)):
    from .complaints import describe
    with SessionLocal() as s:
        p = s.get(Post, pid)
        if not p:
            raise HTTPException(404)
        rel_ids = [r["id"] for r in p.related or []]
        rel = s.query(Post).filter(Post.id.in_(rel_ids)).all() if rel_ids else []
        rel.sort(key=lambda x: rel_ids.index(x.id))
        pdf = build_report(p, rel, describe(p), masked=not can(u, "IO"))
    audit.log(u, "report.exported", pid, {"sha256": __import__("hashlib").sha256(pdf).hexdigest()}, ip_of(request))
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="MuleWatch-Case-MW-{pid:05d}.pdf"'})


# ----------------------------------------------------------------------------- analyze / ingest

@app.post("/api/analyze")
async def analyze_endpoint(request: Request, text: str = Form(""), platform: str = Form("Manual submission"),
                           url: str = Form(""), author: str = Form(""), save: bool = Form(True),
                           source: str = Form("manual"), image: UploadFile | None = File(None),
                           u=Depends(current_user)):
    image_path = ""
    if image is not None and image.filename:
        data = await image.read()
        if len(data) > 8 * 1024 * 1024:
            raise HTTPException(413, "Image too large (max 8 MB)")
        # only real images are stored: they are served from this origin, so an uploaded
        # .html/.svg would otherwise run as script on the command center
        try:
            with PILImage.open(io.BytesIO(data)) as im:
                fmt = (im.format or "").upper()
                im.verify()
        except Exception:
            raise HTTPException(400, "That file isn't a readable image (PNG, JPG, WEBP, GIF or BMP)")
        ext = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "GIF": ".gif", "BMP": ".bmp"}.get(fmt)
        if not ext:
            raise HTTPException(400, f"Unsupported image type {fmt or 'unknown'}")
        image_path = f"upload_{uuid.uuid4().hex[:10]}{ext}"
        (MEDIA_DIR / image_path).write_bytes(data)
    if not text.strip() and not image_path:
        raise HTTPException(400, "Provide text, a URL or an image")
    if source not in ("manual", "extension"):
        source = "manual"
    out = _score(save, text=text, platform=platform, author=author, url=url, image_path=image_path, source=source)
    if save:
        audit.log(u, "post.checked", out.get("id"), {"source": source, "url": url[:200]}, ip_of(request))
    return masking.apply(out, u)


def _score(save: bool, **kw) -> dict:
    """Score content; keep it as a case only when save is true (previews raise no alerts)."""
    with SessionLocal() as s:
        if save:
            p = ingest(s, use_llm=True, **kw)
            s.commit()
            return detail(s, p)
        kw["source"] = "preview"
        p = ingest(s, use_llm=True, recompute=False, **kw)
        recompute_all(s, alert=False)
        out = detail(s, p) | {"id": None}
        s.query(Alert).filter(Alert.post_id == p.id).delete()
        s.delete(p)
        s.commit()
        recompute_all(s, alert=False)
        return out


@app.post("/api/analyze/url")
def analyze_url(request: Request, url: str = Body(...), save: bool = Body(True), u=Depends(current_user)):
    """Fetch one public link (post, ad, Telegram post, web page or image) and score it."""
    from .fetcher import FetchError, fetch_url
    from .crawler import _parse_dt
    url = url.strip()
    if save:
        with SessionLocal() as s:
            existing = s.query(Post).filter(Post.url == url).order_by(Post.id.desc()).first()
            if existing:
                return masking.apply(detail(s, existing), u) | {"fetch": {"already_tracked": True, "how": "Already a case",
                                                        "final_url": url, "note": ""}}
    try:
        f = fetch_url(url)
    except FetchError as e:
        raise HTTPException(422, str(e))
    if not f["text"] and not f["image_paths"]:
        raise HTTPException(422, f["note"] or "Nothing readable was found at that link.")
    imgs = f["image_paths"]
    out = _score(save, text=f["text"], platform=f["platform"], author=f["author"], url=f["final_url"],
                 image_path=imgs[0] if imgs else "", extra_images=imgs[1:], posted_at=_parse_dt(f["posted_at"]),
                 source="url", html=f.get("html", ""))
    if save:
        audit.log(u, "post.checked", out.get("id"), {"source": "url", "url": url[:200]}, ip_of(request))
    out = masking.apply(out, u)
    return out | {"fetch": {k: f[k] for k in ("final_url", "how", "note", "title")} | {"images": len(imgs)}}


# ----------------------------------------------------------------------------- stats & trends

def _matched_complaint_amount(s, posts) -> float:
    """Money lost in complaints linked to any case, counting each complaint once."""
    from .db import Complaint
    ids = {c["complaint"] for p in posts for c in (p.complaint_matches or [])}
    if not ids:
        return 0
    return float(sum(a or 0 for (a,) in s.query(Complaint.amount).filter(Complaint.id.in_(ids)).all()))


@app.get("/api/stats")
def stats(u=Depends(current_user)):
    with SessionLocal() as s:
        posts = s.query(Post).filter(Post.source != "preview").all()
        by_level = Counter(p.risk_level for p in posts)
        by_cat = Counter(p.category for p in posts if p.category != "Benign")
        by_platform = Counter((p.platform or "").split(" · ")[0] for p in posts)
        flagged = [p for p in posts if LEVEL_RANK.get(p.risk_level, 0) >= 2]
        terms = Counter(m["term"] for p in flagged for m in (p.matches or []))
        ids = Counter()
        for p in posts:
            for k in entity_keys(p.entities or {}):
                ids[k] += 1
        rings = defaultdict(list)
        for p in posts:
            if p.cluster_id is not None:
                rings[p.cluster_id].append(p)
        ring_list = sorted(({
            "cluster_id": cid, "size": len(m), "max_score": max(x.risk_score for x in m),
            "platforms": sorted({x.platform.split(' · ')[0] for x in m}),
            "authors": sorted({x.author for x in m if x.author})[:6],
            "identifiers": sorted({k for x in m for k in entity_keys(x.entities or {})
                                    if ids[k] > 1})[:6],
        } for cid, m in rings.items()), key=lambda r: (-r["max_score"], -r["size"]))

        # timeline: flagged vs total per hour (last 48h) or per day
        now = datetime.utcnow()
        buckets = defaultdict(lambda: {"total": 0, "flagged": 0})
        span_days = max(1, (now - min((p.posted_at for p in posts if p.posted_at), default=now)).days)
        for p in posts:
            t = p.posted_at or p.ingested_at or now
            key = t.replace(hour=0, minute=0, second=0, microsecond=0) if span_days > 2 else \
                t.replace(minute=0, second=0, microsecond=0)
            buckets[key]["total"] += 1
            buckets[key]["flagged"] += LEVEL_RANK.get(p.risk_level, 0) >= 2
        fmt = "%d %b" if span_days > 2 else "%d %b %H:00"
        order = sorted(buckets)
        return {
            "total": len(posts), "flagged": len(flagged),
            "critical": by_level.get("Critical", 0), "high": by_level.get("High", 0),
            "medium": by_level.get("Medium", 0), "low": by_level.get("Low", 0),
            "confirmed": sum(1 for p in posts if p.label == "confirmed"),
            "false_positive": sum(1 for p in posts if p.label == "false_positive"),
            "rings": len(ring_list), "ring_list": ring_list[:12],
            "by_category": by_cat.most_common(), "by_platform": by_platform.most_common(),
            "top_terms": terms.most_common(12),
            "top_identifiers": [(k if can(u, "IO") else k.split(":", 1)[0] + ":" + masking.mask_text(k.split(":", 1)[1]), n)
                                for k, n in ids.most_common(12) if n > 1],
            "timeline": [{"bucket": k.strftime(fmt), **buckets[k]} for k in order][-30:],
            "alerts_unseen": s.query(Alert).filter_by(seen=False).count(),
            "citizen_reports": s.query(Report).count(),
            "complaint_linked": sum(1 for p in posts if p.complaint_count),
            "complaint_amount": _matched_complaint_amount(s, posts),
            "reappeared": sum(1 for p in posts if p.repost_of),
            "open_cases": sum(1 for p in posts if (p.status or "NEW") in workflow.OPEN and LEVEL_RANK.get(p.risk_level, 0) >= 2),
            "my_cases": sum(1 for p in posts if p.assigned_to == u.id and (p.status or "NEW") in workflow.OPEN),
            "clocks": {st: sum(1 for p in posts if p.status == "NOTICE_SENT" and workflow.clock(p)["state"] == st)
                       for st in ("running", "warn", "overdue")},
            "system": {"ocr": OCR_AVAILABLE, "llm": llm.enabled(), "telegram_alerts": telegram_enabled(),
                       "model_docs": model().docs, "crawler": crawler.status(),
                       "screenshots": evidence.status()["screenshots"]},
        }


# ----------------------------------------------------------------------------- graph

KIND_LABEL = {"phone": "Phone", "upi": "UPI", "telegram": "Telegram", "whatsapp": "WhatsApp", "handle": "Handle",
              "email": "Email", "crypto_wallet": "Wallet", "card_number": "Card", "ifsc": "IFSC", "domain": "Domain",
              "bank_account": "Account"}


@app.get("/api/graph")
def graph(min_score: float = 30, cluster: int | None = None, post: int | None = None, u=Depends(current_user)):
    with SessionLocal() as s:
        posts = s.query(Post).all()
        if post is not None:
            p0 = s.get(Post, post)
            cluster = p0.cluster_id if p0 else None
            if cluster is None:
                posts = [p0] if p0 else []
        if cluster is not None:
            posts = [p for p in posts if p.cluster_id == cluster]
        else:
            posts = [p for p in posts if p.risk_score >= min_score]
        owners = defaultdict(set)
        for p in posts:
            for k in entity_keys(p.entities or {}):
                owners[k].add(p.id)
        nodes, edges = [], []
        for p in posts:
            nodes.append({"id": f"p{p.id}", "type": "post", "label": f"MW-{p.id}", "post_id": p.id,
                          "level": p.risk_level, "score": p.risk_score, "platform": p.platform.split(" · ")[0],
                          "excerpt": (p.text or p.ocr_text or "")[:120] if can(u, "IO")
                          else masking.mask_text((p.text or p.ocr_text or "")[:120]), "author": p.author})
        keep_single = cluster is not None or post is not None
        for k, ids in owners.items():
            if len(ids) < 2 and not keep_single:
                continue
            kind, val = k.split(":", 1)
            nodes.append({"id": "e:" + k, "type": kind,
                          "label": val if can(u, "IO") or kind not in ("phone", "whatsapp", "bank_account")
                          else masking.mask_text(val), "kind_label": KIND_LABEL.get(kind, kind), "count": len(ids)})
            for pid in ids:
                edges.append({"source": f"p{pid}", "target": "e:" + k, "kind": kind})
        present = {p.id for p in posts}
        seen = set()
        for p in posts:
            for r in p.related or []:
                if r["id"] in present and any("duplicate" in w or "image" in w for w in r["why"]):
                    a, b = sorted((p.id, r["id"]))
                    if (a, b) not in seen:
                        seen.add((a, b))
                        edges.append({"source": f"p{a}", "target": f"p{b}", "kind": "similar",
                                      "label": ", ".join(w for w in r["why"] if "duplicate" in w or "image" in w)})
        return {"nodes": nodes, "edges": edges}


# ----------------------------------------------------------------------------- alerts & live events

@app.get("/api/alerts")
def alerts(limit: int = 50, u=Depends(current_user)):
    with SessionLocal() as s:
        rows = s.query(Alert).order_by(Alert.id.desc()).limit(limit).all()
        posts = {p.id: p for p in s.query(Post).filter(Post.id.in_([a.post_id for a in rows])).all()}
        return [{"id": a.id, "post_id": a.post_id, "level": a.level, "reason": a.reason, "seen": a.seen,
                 "channel": a.channel, "delivered": a.delivered, "created_at": a.created_at.isoformat(),
                 "post": masking.apply(summary(posts[a.post_id]), u) if a.post_id in posts else None} for a in rows]


@app.post("/api/alerts/seen")
def alerts_seen():
    with SessionLocal() as s:
        s.query(Alert).update({Alert.seen: True})
        s.commit()
    return {"ok": True}


@app.get("/api/events")
async def events(request: Request):
    """Server-Sent Events: pushes new posts and alerts to the command center in real time."""
    viewer = request.state.user

    async def gen():
        with SessionLocal() as s:
            last_post = s.query(func.max(Post.id)).scalar() or 0
            last_alert = s.query(func.max(Alert.id)).scalar() or 0
        yield "retry: 2000\n\n"
        tick = 0
        while True:
            await asyncio.sleep(1)
            tick += 1
            with SessionLocal() as s:
                for p in s.query(Post).filter(Post.id > last_post).order_by(Post.id).all():
                    if p.source == "preview":
                        continue
                    last_post = p.id
                    yield f"event: post\ndata: {json.dumps(masking.apply(summary(p), viewer))}\n\n"
                for a in s.query(Alert).filter(Alert.id > last_alert).order_by(Alert.id).all():
                    last_alert = a.id
                    p = s.get(Post, a.post_id)
                    yield ("event: alert\ndata: " + json.dumps({
                        "id": a.id, "level": a.level, "reason": a.reason, "channel": a.channel,
                        "post": masking.apply(summary(p), viewer) if p else None}) + "\n\n")
            if tick % 15 == 0:
                yield ": keep-alive\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ----------------------------------------------------------------------------- watchlist & sources

@app.get("/api/watchlist")
def get_watchlist():
    with SessionLocal() as s:
        return [{"id": w.id, "kind": w.kind, "value": w.value, "note": w.note,
                 "created_at": w.created_at.isoformat()} for w in s.query(WatchItem).order_by(WatchItem.id.desc())]


@app.post("/api/watchlist")
def add_watch(request: Request, kind: str = Body(...), value: str = Body(...), note: str = Body(""),
              u=Depends(current_user)):
    if "•" in value:
        raise HTTPException(400, "This number is partly hidden for your role. Ask an Investigating Officer to add it.")
    audit.log(u, "watchlist.added", detail={"kind": kind, "value": value[:100]}, ip=ip_of(request))
    with SessionLocal() as s:
        s.add(WatchItem(kind=kind, value=value.strip(), note=note))
        s.commit()
        recompute_all(s, alert=True)
    return get_watchlist()


@app.delete("/api/watchlist/{wid}")
def del_watch(wid: int, request: Request, u=Depends(current_user)):
    with SessionLocal() as s:
        w = s.get(WatchItem, wid)
        if w:
            audit.log(u, "watchlist.removed", detail={"kind": w.kind, "value": w.value}, ip=ip_of(request))
            s.delete(w)
            s.commit()
            recompute_all(s, alert=False)
    return get_watchlist()


@app.get("/api/health")
def health():
    """Open without signing in: the login page uses it to show the demo accounts while they exist."""
    return {"ok": True, "demo_accounts": auth.demo_accounts_active()}


@app.get("/api/sources")
def sources(u=Depends(current_user)):
    with SessionLocal() as s:
        return {"crawler": crawler.status(), "sources": [{
            "id": x.id, "kind": x.kind, "name": x.name, "url": x.url, "enabled": x.enabled,
            "last_crawl": x.last_crawl.isoformat() if x.last_crawl else None,
            "last_status": x.last_status, "items_seen": x.items_seen} for x in s.query(Source).all()]}


@app.post("/api/sources")
def add_source(request: Request, kind: str = Body(...), url: str = Body(...), name: str = Body(""),
               u=Depends(require("IO"))):
    audit.log(u, "source.added", detail={"kind": kind, "url": url[:200]}, ip=ip_of(request))
    if kind not in crawler.CRAWLERS:
        raise HTTPException(400, f"kind must be one of {list(crawler.CRAWLERS)}")
    with SessionLocal() as s:
        s.add(Source(kind=kind, url=url.strip(), name=name or url))
        s.commit()
    return sources()


@app.patch("/api/sources/{sid}")
def toggle_source(sid: int, request: Request, enabled: bool = Body(..., embed=True), u=Depends(require("IO"))):
    audit.log(u, "source.toggled", detail={"source": sid, "enabled": enabled}, ip=ip_of(request))
    with SessionLocal() as s:
        x = s.get(Source, sid)
        if x:
            x.enabled = enabled
            s.commit()
    return sources()


@app.get("/api/bot")
def bot_status(u=Depends(current_user)):
    with SessionLocal() as s:
        total = s.query(Report).count()
        reporters = s.query(func.count(func.distinct(Report.reporter_hash))).scalar() or 0
        cases = s.query(func.count(func.distinct(Report.post_id))).scalar() or 0
        last = s.query(func.max(Report.created_at)).scalar()
        recent = s.query(Report, Post).join(Post, Post.id == Report.post_id).order_by(Report.id.desc()).limit(8).all()
        from .alerts import alert_chat_id
        from .db import get_setting
        from .config import TELEGRAM_CHAT_ID
        return reportbot.status() | {
            "alerts_linked": bool(alert_chat_id()),
            "alerts_to": "TELEGRAM_CHAT_ID in .env" if TELEGRAM_CHAT_ID else get_setting("alert_chat_name"),
            "reports": total, "reporters": reporters, "cases": cases,
            "last_report_at": last.isoformat() if last else None,
            "link": f"https://t.me/{reportbot.status()['username']}" if reportbot.status()["username"] else "",
            "alert_code": reportbot.ALERT_CODE if can(u, "SUPERVISOR") else "",
            "recent": [{"post_id": p.id, "risk_level": p.risk_level, "risk_score": p.risk_score,
                        "excerpt": masking.mask_text((p.text or p.ocr_text or "")[:120]) if not can(u, "IO")
                        else (p.text or p.ocr_text or "")[:120], "origin": r.origin,
                        "at": r.created_at.isoformat()} for r, p in recent],
        }


@app.delete("/api/bot/alerts")
def unlink_alerts(request: Request, u=Depends(require("SUPERVISOR"))):
    audit.log(u, "bot.alerts_unlinked", ip=ip_of(request))
    from .db import set_setting
    set_setting("alert_chat_id", None)
    set_setting("alert_chat_name", None)
    return {"ok": True}


@app.post("/api/crawl")
def crawl_now():
    return {"new": crawler.crawl_once()}


# ----------------------------------------------------------------------------- frontend (built SPA)

DIST = ROOT_DIR / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
