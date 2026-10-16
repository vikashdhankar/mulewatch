"""API for the police workflow: case status and assignment, complaint matching, legal drafts, bank routing,
evidence, jurisdiction map, audit log and the daily brief."""
import csv
import hashlib
import io
from collections import Counter, defaultdict
from datetime import datetime

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response

from . import audit, banks, brief, complaints, evidence, jurisdiction, legal, workflow
from .auth import can, current_user, ip_of, require
from .config import DATA_DIR, LEVEL_RANK
from .db import AuditLog, Complaint, ComplaintImport, EvidenceFile, Post, SessionLocal, User
from .pipeline import recompute_all

router = APIRouter(prefix="/api")


def _post(s, pid: int) -> Post:
    p = s.get(Post, pid)
    if not p:
        raise HTTPException(404, "No such case")
    return p


def _juris_for(p: Post, u) -> dict:
    j = dict(p.jurisdiction or {})
    if not can(u, "IO"):
        from .masking import mask_text
        j["signals"] = [dict(x, value=mask_text(x["value"])) if x.get("kind") == "phone" else x
                        for x in j.get("signals", [])]
    return j


def case_info(s, p: Post, u) -> dict:
    """Everything the police side of the case page needs."""
    users = {x.id: x for x in s.query(User).all()}
    a = users.get(p.assigned_to)
    out = {
        "status": p.status or "NEW", "status_label": workflow.STATUSES.get(p.status or "NEW"),
        "allowed_next": [{"status": x, "label": workflow.STATUSES[x]} for x in workflow.allowed_next(p, u)],
        "assigned_to": {"id": a.id, "name": a.name, "designation": a.designation} if a else None,
        "can_assign_others": can(u, "SUPERVISOR"), "can_act": can(u, "IO"),
        "fir_number": p.fir_number or "", "police_station": p.police_station or "", "notes": p.case_notes or "",
        "status_changed_at": p.status_changed_at.isoformat() if p.status_changed_at else None,
        "clock": workflow.clock(p),
        "recruiter_score": p.recruiter_score or 0, "recruiter_reasons": p.recruiter_reasons or [],
        "repost_of": p.repost_of,
        "complaints": {"count": p.complaint_count or 0, "amount": p.complaint_amount or 0, "items": None},
        "jurisdiction": _juris_for(p, u),
        "banks": banks.routes(p) if can(u, "IO") else [],
        "evidence": evidence.verify(s, p.id),
        "screenshots": evidence.status(),
        "drafts": [{"kind": k, "label": v["en"], "label_hi": v["hi"]} for k, v in legal.KINDS.items()],
    }
    if can(u, "IO"):
        if p.complaint_count:
            out["complaints"]["items"] = complaints.complaint_details(s, p)
        out["custody"] = evidence.custody(s, p.id)[-60:]
    return out


@router.get("/posts/{pid}/police")
def police_view(pid: int, request: Request, u=Depends(current_user)):
    with SessionLocal() as s:
        p = _post(s, pid)
        out = case_info(s, p, u)
    if out["complaints"]["items"]:
        audit.log(u, "complaints.viewed", pid, {"complaints": len(out["complaints"]["items"])}, ip_of(request))
    return out


@router.patch("/posts/{pid}/case")
def update_case(pid: int, request: Request, data: dict = Body(...), u=Depends(require("IO"))):
    with SessionLocal() as s:
        p = _post(s, pid)
        changes = {}
        if "assigned_to" in data:
            target = data["assigned_to"]
            if target not in (None, u.id) and not can(u, "SUPERVISOR"):
                raise HTTPException(403, "Only a supervisor can assign a case to someone else")
            if target is None and p.assigned_to not in (None, u.id) and not can(u, "SUPERVISOR"):
                raise HTTPException(403, "Only a supervisor can take a case away from another officer")
            if target is not None:
                t = s.get(User, target)
                if not t or not t.active or not can(t, "IO"):
                    raise HTTPException(400, "Cases can be assigned to active Investigating Officers or supervisors")
            p.assigned_to = target
            changes["assigned_to"] = target
        for key, col, n in (("fir_number", "fir_number", 60), ("police_station", "police_station", 120),
                            ("notes", "case_notes", 4000)):
            if key in data:
                setattr(p, col, str(data[key] or "")[:n])
                changes[key] = str(data[key] or "")[:120]
        if data.get("status"):
            try:
                old = p.status or "NEW"
                workflow.set_status(p, data["status"], u)
                changes["status"] = f"{old} -> {p.status}"
            except workflow.WorkflowError as e:
                raise HTTPException(400, str(e))
        s.commit()
        if "status" in changes and p.status == "CONTENT_REMOVED":
            recompute_all(s, alert=True)          # start watching for it to come back
        out = case_info(s, p, u)
    audit.log(u, "case.updated", pid, changes, ip_of(request))
    return out


@router.get("/workflow")
def workflow_meta(u=Depends(current_user)):
    return {"statuses": workflow.STATUSES, "window_hours": workflow.WINDOW_HOURS}


@router.get("/clocks")
def clocks(u=Depends(current_user)):
    """Cases whose platform removal window is running, soonest deadline first."""
    with SessionLocal() as s:
        rows = s.query(Post).filter(Post.status == "NOTICE_SENT").all()
        users = {x.id: x.name for x in s.query(User).all()}
        out = [{"id": p.id, "platform": p.platform.split(" · ")[0], "category": p.category,
                "risk_level": p.risk_level, "officer": users.get(p.assigned_to, ""), "clock": workflow.clock(p)}
               for p in rows]
    return sorted(out, key=lambda x: x["clock"]["seconds_left"])


# ----------------------------------------------------------------------------- legal drafts

@router.get("/posts/{pid}/drafts/{kind}")
def draft(pid: int, kind: str, request: Request, lang: str = "en", bank: str | None = None,
          u=Depends(require("IO"))):
    if kind not in legal.KINDS:
        raise HTTPException(404)
    with SessionLocal() as s:
        p = _post(s, pid)
        try:
            text = legal.render(s, p, u, kind, lang, bank)
        except Exception as e:                       # a broken override template shouldn't take the page down
            raise HTTPException(500, f"Template error in {kind}_{lang}.j2: {e}")
        options = [{"code": g["bank_code"] or "?", "bank": g["bank"]} for g in banks.routes(p)] if kind == "bank" else []
    audit.log(u, "draft.generated", pid, {"kind": kind, "lang": lang, "bank": bank}, ip_of(request))
    return {"text": text, "banks": options, "kind": kind, "lang": lang}


@router.post("/posts/{pid}/drafts/{kind}/export")
def draft_export(pid: int, kind: str, request: Request, text: str = Body(...), lang: str = Body("en"),
                 format: str = Body("docx"), u=Depends(require("IO"))):
    if kind not in legal.KINDS or format not in ("docx", "pdf"):
        raise HTTPException(400)
    case = f"MW-{pid:05d}"
    with SessionLocal() as s:
        p = _post(s, pid)
        data, name, mime = legal.export(text, format, kind, lang, case)
        moved = ""
        if kind in ("takedown", "preservation") and (p.status or "NEW") == "VERIFIED":
            workflow.set_status(p, "NOTICE_DRAFTED", u)
            moved = "VERIFIED -> NOTICE_DRAFTED"
            s.commit()
    audit.log(u, "draft.exported", pid, {"kind": kind, "lang": lang, "format": format, "file": name,
                                         "sha256": hashlib.sha256(data).hexdigest(), "status": moved},
              ip_of(request))
    return Response(data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ----------------------------------------------------------------------------- evidence

@router.get("/posts/{pid}/evidence/{fid}")
def evidence_file(pid: int, fid: int, request: Request, u=Depends(require("IO"))):
    with SessionLocal() as s:
        f = s.get(EvidenceFile, fid)
        if not f or f.post_id != pid:
            raise HTTPException(404)
        path = DATA_DIR / f.path
        name, sha = f.path.rsplit("/", 1)[-1], f.sha256
    if not path.exists():
        raise HTTPException(410, "The file is missing from the evidence store")
    audit.log(u, "evidence.downloaded", pid, {"file": name, "sha256": sha}, ip_of(request))
    media = "text/plain" if name.endswith(".html") else None     # never render captured pages as live HTML
    return FileResponse(path, filename=name, media_type=media,
                        headers={"Content-Security-Policy": "sandbox", "X-Content-Type-Options": "nosniff"})


@router.get("/posts/{pid}/evidence-pack.zip")
def evidence_pack(pid: int, request: Request, u=Depends(require("IO"))):
    from .report import build_report
    with SessionLocal() as s:
        p = _post(s, pid)
        rel_ids = [r["id"] for r in p.related or []]
        rel = s.query(Post).filter(Post.id.in_(rel_ids)).all() if rel_ids else []
        pdf = build_report(p, rel, complaints.describe(p))
        cert = legal.to_docx(legal.render(s, p, u, "bsa63", "en"), legal.KINDS["bsa63"]["en"], f"MW-{pid:05d}")
        data = evidence.build_pack(s, p, pdf, cert)
    sha = hashlib.sha256(data).hexdigest()
    audit.log(u, "evidence.pack_exported", pid, {"sha256": sha, "bytes": len(data)}, ip_of(request))
    return Response(data, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="MuleWatch-MW-{pid:05d}-evidence.zip"', "X-Pack-SHA256": sha})


# ----------------------------------------------------------------------------- complaints

@router.post("/complaints/upload")
async def complaints_upload(request: Request, file: UploadFile = File(...), u=Depends(require("IO"))):
    data = await file.read()
    try:
        out = complaints.parse_upload(file.filename, data, u)
    except complaints.ImportError_ as e:
        raise HTTPException(400, str(e))
    audit.log(u, "complaints.uploaded", None, {"file": file.filename, "rows": out["rows"]}, ip_of(request))
    return out


@router.post("/complaints/import")
def complaints_import(request: Request, token: str = Body(...), mapping: dict = Body(...), label: str = Body(""),
                      u=Depends(require("IO"))):
    with SessionLocal() as s:
        try:
            res = complaints.do_import(s, token, mapping, label, u)
        except complaints.ImportError_ as e:
            raise HTTPException(400, str(e))
        s.commit()
        recompute_all(s, alert=True)
        res["cases_linked"] = s.query(Post).filter(Post.complaint_count > 0).count()
    audit.log(u, "complaints.imported", None, res | {"mapping": mapping}, ip_of(request))
    return res


@router.get("/complaints")
def complaints_summary(u=Depends(require("IO"))):
    with SessionLocal() as s:
        imports = s.query(ComplaintImport).order_by(ComplaintImport.id.desc()).all()
        total = s.query(Complaint).count()
        matched_ids = {m["complaint"] for p in s.query(Post).filter(Post.complaint_count > 0).all()
                       for m in p.complaint_matches or []}
        linked_cases = s.query(Post).filter(Post.complaint_count > 0).order_by(Post.complaint_amount.desc()).limit(30).all()
        amount = sum(a or 0 for (a,) in s.query(Complaint.amount).filter(Complaint.id.in_(matched_ids)).all()) if matched_ids else 0
        return {
            "total": total, "matched": len(matched_ids), "matched_amount": amount,
            "imports": [{"id": i.id, "label": i.label, "filename": i.filename, "by": i.imported_by,
                         "at": i.imported_at.isoformat(), "rows": i.rows, "skipped": i.skipped} for i in imports],
            "cases": [{"id": p.id, "risk_level": p.risk_level, "risk_score": p.risk_score, "category": p.category,
                       "complaints": p.complaint_count, "amount": p.complaint_amount, "status": p.status or "NEW",
                       "platform": p.platform.split(" · ")[0]} for p in linked_cases],
            "fields": complaints.FIELDS,
        }


@router.delete("/complaints/imports/{iid}")
def complaints_delete(iid: int, request: Request, u=Depends(require("SUPERVISOR"))):
    with SessionLocal() as s:
        n = complaints.delete_import(s, iid)
        s.commit()
        recompute_all(s, alert=False)
    audit.log(u, "complaints.deleted", None, {"import": iid, "complaints": n}, ip_of(request))
    return {"deleted": n}


# ----------------------------------------------------------------------------- map

@router.get("/districts")
def districts(u=Depends(current_user)):
    with SessionLocal() as s:
        posts = s.query(Post).filter(Post.source != "preview").all()
    flagged = defaultdict(list)
    for p in posts:
        d = (p.jurisdiction or {}).get("district")
        if d and LEVEL_RANK.get(p.risk_level, 0) >= 2:
            flagged[d].append(p)
    out = []
    for pt in jurisdiction.district_points():
        ps = flagged.get(pt["name"], [])
        out.append(pt | {"cases": len(ps), "critical": sum(p.risk_level == "Critical" for p in ps),
                         "complaints": sum(p.complaint_count or 0 for p in ps),
                         "open": sum((p.status or "NEW") in workflow.OPEN for p in ps),
                         "top": [{"id": p.id, "category": p.category, "risk_score": p.risk_score}
                                 for p in sorted(ps, key=lambda x: -x.risk_score)[:4]]})
    unplaced = sum(1 for p in posts if LEVEL_RANK.get(p.risk_level, 0) >= 2 and not (p.jurisdiction or {}).get("district"))
    circles = Counter(c for p in posts if LEVEL_RANK.get(p.risk_level, 0) >= 2 for c in (p.jurisdiction or {}).get("circles", []))
    return {"districts": out, "unplaced": unplaced, "circles": circles.most_common()}


# ----------------------------------------------------------------------------- audit

@router.get("/audit")
def audit_list(user: str | None = None, action: str | None = None, case: int | None = None,
               limit: int = Query(100, le=1000), offset: int = 0, u=Depends(require("SUPERVISOR"))):
    with SessionLocal() as s:
        q = s.query(AuditLog)
        if user:
            q = q.filter(AuditLog.username == user)
        if action:
            q = q.filter(AuditLog.action.like(f"{action}%"))
        if case is not None:
            q = q.filter(AuditLog.case_id == case)
        total = q.count()
        rows = q.order_by(AuditLog.id.desc()).offset(offset).limit(limit).all()
        actions = [a for (a,) in s.query(AuditLog.action).distinct().order_by(AuditLog.action).all()]
        return {"total": total, "items": [audit.as_dict(r) for r in rows], "actions": actions}


@router.get("/audit/verify")
def audit_verify(u=Depends(require("SUPERVISOR"))):
    return audit.verify()


@router.get("/audit.csv")
def audit_csv(request: Request, u=Depends(require("SUPERVISOR"))):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "at_utc", "username", "role", "action", "case", "detail", "ip", "prev_hash", "hash"])
    with SessionLocal() as s:
        for r in s.query(AuditLog).order_by(AuditLog.id).yield_per(500):
            w.writerow([r.id, r.at.isoformat(), r.username, r.role, r.action,
                        f"MW-{r.case_id:05d}" if r.case_id else "", r.detail, r.ip, r.prev_hash, r.hash])
    audit.log(u, "audit.exported", ip=ip_of(request))
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="mulewatch-audit-log.csv"'})


# ----------------------------------------------------------------------------- daily brief

@router.get("/brief.pdf")
def brief_pdf(request: Request, lang: str = "en", hours: int = Query(24, ge=1, le=24 * 31),
              district: str | None = None, u=Depends(require("SUPERVISOR"))):
    if district and district not in jurisdiction.DISTRICTS:
        raise HTTPException(400, "Unknown district")
    with SessionLocal() as s:
        pdf = brief.build_pdf(s, lang, hours=hours, district=district or None)
    audit.log(u, "brief.generated", detail={"lang": lang, "hours": hours, "district": district}, ip=ip_of(request))
    name = f"MuleWatch-brief-{datetime.now().strftime('%Y-%m-%d')}-{lang}.pdf"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'})


@router.post("/brief/send")
def brief_send(lang: str = Body("en", embed=True), u=Depends(require("SUPERVISOR"))):
    return brief.send(lang, actor=u)


@router.get("/brief/schedule")
def brief_schedule(u=Depends(require("SUPERVISOR"))):
    from .alerts import alert_token, officer_chats
    with SessionLocal() as s:
        chats = len(officer_chats(s, roles=("SUPERVISOR",)))
    return {"time": brief.BRIEF_TIME, "lang": brief.BRIEF_LANG, "enabled": brief.BRIEF_ON,
            "bot": bool(alert_token()), "supervisor_chats": chats}


# ----------------------------------------------------------------------------- bulk link checks

def _bulk_out(s, job, u, with_items=False):
    from . import bulk
    from .masking import mask_text
    out = bulk.summary(s, job)
    if with_items:
        out["items"] = bulk.items(s, job.id)
        if not can(u, "IO"):
            for it in out["items"]:
                if it["post"]:
                    it["post"]["excerpt"] = mask_text(it["post"]["excerpt"])
                it["note"] = mask_text(it["note"])
    return out


@router.post("/bulk")
def bulk_create(request: Request, text: str = Body(...), label: str = Body(""), u=Depends(current_user)):
    from . import bulk
    try:
        return bulk.create_job(bulk.extract_links(text), label, u)
    except bulk.BulkError as e:
        raise HTTPException(400, str(e))


@router.post("/bulk/upload")
async def bulk_upload(request: Request, file: UploadFile = File(...), label: str = Form(""), u=Depends(current_user)):
    from . import bulk
    data = await file.read()
    try:
        return bulk.create_job(bulk.links_from_file(file.filename, data), label or file.filename, u)
    except bulk.BulkError as e:
        raise HTTPException(400, str(e))


@router.get("/bulk")
def bulk_list(u=Depends(current_user)):
    from .db import BulkJob
    with SessionLocal() as s:
        return [_bulk_out(s, j, u) for j in s.query(BulkJob).order_by(BulkJob.id.desc()).limit(50).all()]


@router.get("/bulk/{jid}")
def bulk_get(jid: int, u=Depends(current_user)):
    from .db import BulkJob
    with SessionLocal() as s:
        j = s.get(BulkJob, jid)
        if not j:
            raise HTTPException(404)
        return _bulk_out(s, j, u, with_items=True)


@router.post("/bulk/{jid}/cancel")
def bulk_cancel(jid: int, u=Depends(current_user)):
    from . import bulk
    from .db import BulkJob
    with SessionLocal() as s:
        j = s.get(BulkJob, jid)
        if not j:
            raise HTTPException(404)
        if j.created_by_id != u.id and not can(u, "IO"):
            raise HTTPException(403, "Only the officer who started this list, or an IO, can stop it")
    return {"skipped": bulk.cancel(jid, u)}


# ----------------------------------------------------------------------------- internet discovery

def _hit_out(h, p, u):
    from .masking import mask_text
    snip = h.snippet or ""
    out = {"id": h.id, "url": h.url, "title": h.title, "snippet": snip if can(u, "IO") else mask_text(snip),
           "platform": h.platform, "district": h.district, "found_at": h.found_at.isoformat(), "provider": h.provider,
           "published": h.published, "triage": h.triage, "status": h.status, "how": h.how, "error": h.error,
           "seen": h.seen_count, "post": None}
    if p:
        out["post"] = {"id": p.id, "risk_level": p.risk_level, "risk_score": p.risk_score, "category": p.category,
                       "complaint_count": p.complaint_count or 0}
    return out


@router.get("/discovery")
def discovery_status(u=Depends(current_user)):
    from . import discovery
    with SessionLocal() as s:
        discovery.ensure_queries(s)
        return discovery.status(s) | discovery.coverage(s)


@router.get("/discovery/hits")
def discovery_hits(district: str = "", platform: str = "", show: str = "flagged", limit: int = Query(100, le=500),
                   offset: int = 0, u=Depends(current_user)):
    from .db import DiscoveryHit
    with SessionLocal() as s:
        q = s.query(DiscoveryHit)
        if district:
            q = q.filter(DiscoveryHit.district == ("" if district == "-" else district))
        if platform:
            q = q.filter(DiscoveryHit.platform == platform)
        if show == "flagged":
            q = q.join(Post, Post.id == DiscoveryHit.post_id).filter(DiscoveryHit.status.in_(("case", "existing")),
                                                                     Post.risk_level.in_(("High", "Critical")))
        elif show == "cases":
            q = q.filter(DiscoveryHit.status.in_(("case", "existing")))
        elif show == "skipped":
            q = q.filter(DiscoveryHit.status == "skipped")
        total = q.count()
        rows = q.order_by(DiscoveryHit.id.desc()).offset(offset).limit(limit).all()
        posts = {p.id: p for p in s.query(Post).filter(Post.id.in_([h.post_id for h in rows if h.post_id])).all()}
        return {"total": total, "items": [_hit_out(h, posts.get(h.post_id), u) for h in rows]}


@router.get("/discovery/queries")
def discovery_queries(district: str = "", kind: str = "", u=Depends(current_user)):
    from .db import DiscoveryQuery
    with SessionLocal() as s:
        q = s.query(DiscoveryQuery)
        if district:
            q = q.filter(DiscoveryQuery.district == ("" if district == "-" else district))
        if kind:
            q = q.filter(DiscoveryQuery.kind == kind)
        rows = q.order_by(DiscoveryQuery.kind.desc(), DiscoveryQuery.flagged.desc(), DiscoveryQuery.new_hits.desc(),
                          DiscoveryQuery.id).limit(400).all()
        return [{"id": x.id, "text": x.text, "district": x.district, "site": x.site, "kind": x.kind,
                 "enabled": x.enabled, "runs": x.runs, "results": x.results, "new_hits": x.new_hits,
                 "flagged": x.flagged, "last_run": x.last_run.isoformat() if x.last_run else None,
                 "last_error": x.last_error, "by": x.created_by} for x in rows]


@router.post("/discovery/queries")
def discovery_add_query(request: Request, text: str = Body(...), district: str = Body(""), site: str = Body(""),
                        u=Depends(require("IO"))):
    from .db import DiscoveryQuery
    text = " ".join(text.split())[:250]
    site = site.strip().lower().removeprefix("https://").removeprefix("www.").strip("/")
    if len(text) < 3:
        raise HTTPException(400, "Write the words to search for")
    if district and district not in jurisdiction.DISTRICTS:
        raise HTTPException(400, "Unknown district")
    full = " ".join(x for x in (text, district if district and district.lower() not in text.lower() else "",
                                f"site:{site}" if site and "site:" not in text else "") if x)
    with SessionLocal() as s:
        if s.query(DiscoveryQuery).filter_by(text=full).first():
            raise HTTPException(400, "This search is already in the list")
        s.add(DiscoveryQuery(text=full, term=text, district=district, site=site, kind="custom", created_by=u.username))
        s.commit()
    audit.log(u, "discovery.query_added", detail={"query": full}, ip=ip_of(request))
    return {"ok": True, "text": full}


@router.patch("/discovery/queries/{qid}")
def discovery_toggle_query(qid: int, request: Request, enabled: bool = Body(..., embed=True), u=Depends(require("IO"))):
    from .db import DiscoveryQuery
    with SessionLocal() as s:
        q = s.get(DiscoveryQuery, qid)
        if not q:
            raise HTTPException(404)
        q.enabled = enabled
        q.created_by = q.created_by if q.kind == "custom" else ("" if enabled else u.username)
        s.commit()
    audit.log(u, "discovery.query_toggled", detail={"query": qid, "enabled": enabled}, ip=ip_of(request))
    return {"ok": True}


@router.post("/discovery/run")
def discovery_run(request: Request, u=Depends(require("IO"))):
    from . import discovery
    return discovery.run_now(u)


@router.get("/discovery/channels")
def discovery_channels(u=Depends(current_user)):
    from .db import DiscoveredChannel
    with SessionLocal() as s:
        rows = s.query(DiscoveredChannel).order_by(DiscoveredChannel.status, DiscoveredChannel.mentions.desc()).limit(200).all()
        return [{"id": c.id, "handle": c.handle, "mentions": c.mentions, "districts": c.districts or [],
                 "first_seen": c.first_seen.isoformat(), "last_seen": c.last_seen.isoformat(),
                 "example_url": c.example_url, "status": c.status, "by": c.decided_by} for c in rows]


@router.post("/discovery/channels/{cid}")
def discovery_channel_decide(cid: int, request: Request, action: str = Body(..., embed=True), u=Depends(require("IO"))):
    from .db import DiscoveredChannel, Source
    if action not in ("monitor", "ignore", "reset"):
        raise HTTPException(400, "action must be monitor, ignore or reset")
    with SessionLocal() as s:
        c = s.get(DiscoveredChannel, cid)
        if not c:
            raise HTTPException(404)
        if action == "monitor":
            url = f"https://t.me/s/{c.handle}"
            if not s.query(Source).filter(Source.kind == "telegram", Source.url.ilike(f"%/{c.handle}")).first():
                s.add(Source(kind="telegram", url=url, name=f"Telegram @{c.handle} (found by discovery)"))
        c.status = {"monitor": "monitored", "ignore": "ignored", "reset": "suggested"}[action]
        c.decided_by = u.username
        s.commit()
    audit.log(u, f"discovery.channel_{action}", detail={"channel": c.handle}, ip=ip_of(request))
    return {"ok": True}
