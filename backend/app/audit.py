"""Append-only, hash-chained audit log.

Each row's hash covers its own fields and the previous row's hash, so editing or removing a row in the
middle breaks the chain from that point on; `verify()` reports where. The database also refuses UPDATE and
DELETE on the table (triggers created in db._migrate)."""
import hashlib
import json
import threading
from datetime import datetime

from .db import AuditLog, SessionLocal

_lock = threading.Lock()

# actor used for things the system does by itself (crawler capture, scheduled brief ...)
SYSTEM = {"id": None, "username": "system", "role": "SYSTEM"}


def _digest(prev: str, at: datetime, user_id, username: str, role: str, action: str, case_id, detail: str,
            ip: str) -> str:
    payload = json.dumps([prev, at.isoformat(timespec="microseconds"), user_id, username, role, action, case_id,
                          detail, ip], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def log(actor, action: str, case_id: int | None = None, detail="", ip: str = "", session=None):
    """actor: a User row, a dict with id/username/role, or None for the system.

    Pass `session` when the caller is in the middle of a write transaction (SQLite allows one writer, so
    writing the audit row through another connection would wait on ourselves). The entry is then written
    right after that session commits, and dropped if it rolls back, which is what should happen."""
    if session is not None:
        pending = session.info.setdefault("audit_pending", [])
        if not pending:
            from sqlalchemy import event

            def flush(sess):
                for args in sess.info.pop("audit_pending", []):
                    log(*args)

            def drop(sess):
                sess.info.pop("audit_pending", None)
            if not session.info.get("audit_hooked"):
                event.listen(session, "after_commit", flush)
                event.listen(session, "after_rollback", drop)
                session.info["audit_hooked"] = True
        pending.append((actor, action, case_id, detail, ip))
        return None
    if actor is None:
        actor = SYSTEM
    uid = actor["id"] if isinstance(actor, dict) else actor.id
    uname = actor["username"] if isinstance(actor, dict) else actor.username
    role = actor["role"] if isinstance(actor, dict) else actor.role
    if not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False, default=str)
    detail = detail[:2000]
    with _lock, SessionLocal() as s:
        last = s.query(AuditLog).order_by(AuditLog.id.desc()).first()
        prev = last.hash if last else ""
        at = datetime.utcnow()
        row = AuditLog(at=at, user_id=uid, username=uname, role=role, action=action, case_id=case_id,
                       detail=detail, ip=ip or "", prev_hash=prev,
                       hash=_digest(prev, at, uid, uname, role, action, case_id, detail, ip or ""))
        s.add(row)
        s.commit()
        return row.id


def verify() -> dict:
    """Walk the chain. Returns {"ok": bool, "rows": n, "broken_at": id | None}."""
    with SessionLocal() as s:
        prev, n = "", 0
        for r in s.query(AuditLog).order_by(AuditLog.id).yield_per(500):
            n += 1
            good = _digest(prev, r.at, r.user_id, r.username, r.role, r.action, r.case_id, r.detail or "", r.ip or "")
            if r.prev_hash != prev or r.hash != good:
                return {"ok": False, "rows": n, "broken_at": r.id}
            prev = r.hash
        return {"ok": True, "rows": n, "broken_at": None, "head": prev}


def as_dict(r: AuditLog) -> dict:
    return {"id": r.id, "at": r.at.isoformat(), "username": r.username, "role": r.role, "action": r.action,
            "case_id": r.case_id, "detail": r.detail, "ip": r.ip, "hash": r.hash}
