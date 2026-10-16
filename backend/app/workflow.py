"""Police case lifecycle and the platform takedown clock.

  NEW ─▶ VERIFIED ─▶ NOTICE_DRAFTED ─▶ NOTICE_SENT ─▶ CONTENT_REMOVED ─▶ FIR_LINKED
   │        │              │                                  │
   └────────┴──────────────┴─────────▶ CLOSED_NO_ACTION ◀─────┘

The removal clock starts when the officer marks the notice as sent (that is when the platform's
obligation starts running). Under the IT Rules amendment notified on 10 Feb 2026 the window for
unlawful content is three hours; TAKEDOWN_WINDOW_HOURS changes it if the rule changes."""
import os
import threading
import time
import traceback
from datetime import datetime, timedelta

from .config import LEVEL_RANK

STATUSES = {
    "NEW": "New",
    "VERIFIED": "Verified",
    "NOTICE_DRAFTED": "Notice drafted",
    "NOTICE_SENT": "Notice sent",
    "CONTENT_REMOVED": "Content removed",
    "FIR_LINKED": "Linked to FIR",
    "CLOSED_NO_ACTION": "Closed – no action",
}
NEXT = {
    "NEW": ["VERIFIED", "CLOSED_NO_ACTION"],
    "VERIFIED": ["NOTICE_DRAFTED", "NOTICE_SENT", "FIR_LINKED", "CLOSED_NO_ACTION"],
    "NOTICE_DRAFTED": ["NOTICE_SENT", "VERIFIED", "CLOSED_NO_ACTION"],
    "NOTICE_SENT": ["CONTENT_REMOVED"],
    "CONTENT_REMOVED": ["FIR_LINKED", "CLOSED_NO_ACTION"],
    "FIR_LINKED": [],
    "CLOSED_NO_ACTION": ["NEW"],
}
OPEN = {"NEW", "VERIFIED", "NOTICE_DRAFTED", "NOTICE_SENT"}
WINDOW_HOURS = float(os.getenv("TAKEDOWN_WINDOW_HOURS", "3"))
WARN_MINUTES = float(os.getenv("TAKEDOWN_WARN_MINUTES", "30"))


class WorkflowError(Exception):
    pass


def allowed_next(post, user) -> list[str]:
    from .auth import can
    cur = post.status or "NEW"
    if can(user, "SUPERVISOR"):
        return [s for s in STATUSES if s != cur]
    if can(user, "IO"):
        return NEXT.get(cur, [])
    return []


def set_status(post, new: str, user, fir_number: str | None = None, now: datetime | None = None):
    """Validate and apply a status change. Raises WorkflowError with a readable reason."""
    if new not in STATUSES:
        raise WorkflowError(f"Unknown status {new}")
    cur = post.status or "NEW"
    if new == cur:
        return
    if new not in allowed_next(post, user):
        raise WorkflowError(f"A case can't go from “{STATUSES[cur]}” to “{STATUSES[new]}”"
                            + ("" if allowed_next(post, user) else " with your role"))
    if fir_number is not None:
        post.fir_number = fir_number.strip()
    if new == "FIR_LINKED" and not (post.fir_number or "").strip():
        raise WorkflowError("Enter the FIR number first")
    now = now or datetime.utcnow()
    if new == "NOTICE_SENT":
        post.notice_sent_at, post.removed_at, post.deadline_alerts = now, None, ""
    if new == "CONTENT_REMOVED":
        post.removed_at = now
    if new == "NEW":                     # reopened
        post.notice_sent_at = post.removed_at = None
    post.status = new
    post.status_changed_at = now


def clock(post, now: datetime | None = None) -> dict | None:
    """The platform's removal window for a case, or None if no notice has been sent."""
    if not post.notice_sent_at:
        return None
    now = now or datetime.utcnow()
    deadline = post.notice_sent_at + timedelta(hours=WINDOW_HOURS)
    if post.removed_at:
        took = (post.removed_at - post.notice_sent_at).total_seconds()
        state = "met" if post.removed_at <= deadline else "late"
        return {"state": state, "deadline": deadline.isoformat(), "sent_at": post.notice_sent_at.isoformat(),
                "removed_at": post.removed_at.isoformat(), "took_minutes": round(took / 60), "window_hours": WINDOW_HOURS}
    left = (deadline - now).total_seconds()
    state = "overdue" if left <= 0 else "warn" if left <= WARN_MINUTES * 60 else "running"
    return {"state": state, "deadline": deadline.isoformat(), "sent_at": post.notice_sent_at.isoformat(),
            "seconds_left": round(left), "window_hours": WINDOW_HOURS}


def check_clocks(session, now: datetime | None = None) -> int:
    """Alert once when a window is nearly over and once when it has run out without removal."""
    from .alerts import notify, officer_chats
    from .db import Post
    now = now or datetime.utcnow()
    n = 0
    for p in session.query(Post).filter(Post.status == "NOTICE_SENT", Post.notice_sent_at.isnot(None)).all():
        c = clock(p, now)
        sent = set(filter(None, (p.deadline_alerts or "").split(",")))
        chats = officer_chats(session, roles=("SUPERVISOR",), user_ids=(p.assigned_to,) if p.assigned_to else ())
        if c["state"] == "overdue" and "overdue" not in sent:
            notify(session, p, f"Takedown window over: {p.platform.split(' · ')[0]} has not removed the content "
                               f"{WINDOW_HOURS:g} h after the notice. Escalate or record non-compliance.", chats=chats)
            sent |= {"warn", "overdue"}
            n += 1
        elif c["state"] == "warn" and "warn" not in sent:
            notify(session, p, f"Takedown window: {max(1, c['seconds_left'] // 60)} min left for "
                               f"{p.platform.split(' · ')[0]} to remove this content.", chats=chats)
            sent.add("warn")
            n += 1
        p.deadline_alerts = ",".join(sorted(sent))
    session.commit()
    return n


def priority_key(p) -> tuple:
    """Queue order for 'recruiters first': recruiter score, then risk."""
    return (-(p.recruiter_score or 0), -LEVEL_RANK.get(p.risk_level, 0), -(p.risk_score or 0))


# ----------------------------------------------------------------------------- background jobs

_state = {"running": False, "last_brief": None}


def _loop():
    from .db import SessionLocal
    while _state["running"]:
        try:
            with SessionLocal() as s:
                check_clocks(s)
            from . import brief
            brief.maybe_send_scheduled()
        except Exception:
            traceback.print_exc()
        time.sleep(30)


def start():
    if not _state["running"]:
        _state["running"] = True
        threading.Thread(target=_loop, daemon=True, name="workflow").start()
