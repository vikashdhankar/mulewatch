"""Court-ready evidence capture.

For every captured post MuleWatch keeps, under backend/data/evidence/MW-<case>/:
  * capture.txt   the text as observed, with platform, URL, author and capture time (UTC and IST)
  * page.html     the full page as the server returned it, when there was a page
  * screenshot    a full-page PNG for High/Critical cases with a public URL, when Playwright is installed
  * the attached image (already stored under media/)
Each file's SHA-256 is recorded at capture time (EvidenceFile) and every capture, view and export is written
to the audit log, which is the chain of custody. `verify()` re-hashes the files to show they are unchanged.
These hashes are what Part B of the Section 63 BSA certificate asks for."""
import hashlib
import io
import json
import os
import platform as _platform
import queue
import threading
import zipfile
from datetime import datetime, timedelta

from . import audit
from .config import DATA_DIR, LEVEL_RANK
from .db import AuditLog, EvidenceFile, Post, SessionLocal

EVIDENCE_DIR = DATA_DIR / "evidence"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOTS = os.getenv("MW_SCREENSHOTS", "1") != "0"
APP_VERSION = "2.0"


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def ist(dt: datetime | None) -> str:
    return (dt + timedelta(hours=5, minutes=30)).strftime("%d %b %Y %H:%M:%S IST") if dt else "—"


def case_dir(post_id: int):
    d = EVIDENCE_DIR / f"MW-{post_id:05d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _record(session, post, kind, path, source_url="", note="") -> EvidenceFile:
    rel = path.relative_to(DATA_DIR).as_posix()
    ef = EvidenceFile(post_id=post.id, kind=kind, path=rel, sha256=sha256_file(path), size=path.stat().st_size,
                      source_url=source_url, note=note)
    session.add(ef)
    return ef


def capture(session, post, html: str = "") -> list[dict]:
    """Store what was observed for a newly ingested post. Called once, right after the post is created."""
    if post.id is None or post.source == "preview":
        return []
    d = case_dir(post.id)
    now = post.ingested_at or datetime.utcnow()
    files = []
    lines = [f"MuleWatch capture — case MW-{post.id:05d}",
             f"Captured at: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC ({ist(now)})",
             f"Source: {post.source}", f"Platform: {post.platform}", f"URL: {post.url or '—'}",
             f"Author / handle: {post.author or '—'}",
             f"Posted at (as published): {post.posted_at.strftime('%Y-%m-%d %H:%M:%S') + ' UTC' if post.posted_at else '—'}",
             "", "----- Text as observed -----", post.text or "(none)"]
    if post.ocr_text:
        lines += ["", "----- Text read from the attached image (OCR) -----", post.ocr_text]
    txt = d / "capture.txt"
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    files.append(_record(session, post, "text", txt, post.url))
    if html:
        page = d / "page.html"
        page.write_text(html, encoding="utf-8")
        files.append(_record(session, post, "html", page, post.url, "Page as returned by the server at capture time"))
    if post.image_path:
        img = DATA_DIR / "media" / post.image_path
        if img.exists():
            files.append(_record(session, post, "image", img, post.url, "Image attached to the post"))
    session.flush()
    audit.log(None, "evidence.captured", post.id,
              {"files": [{"kind": f.kind, "path": f.path, "sha256": f.sha256} for f in files]}, session=session)
    return [as_dict(f) for f in files]


def as_dict(f: EvidenceFile) -> dict:
    return {"id": f.id, "kind": f.kind, "path": f.path, "name": f.path.rsplit("/", 1)[-1], "sha256": f.sha256,
            "size": f.size, "source_url": f.source_url, "note": f.note,
            "captured_at": f.captured_at.isoformat() if f.captured_at else None}


def files_for(session, post_id: int) -> list[EvidenceFile]:
    return session.query(EvidenceFile).filter_by(post_id=post_id).order_by(EvidenceFile.id).all()


def verify(session, post_id: int) -> list[dict]:
    out = []
    for f in files_for(session, post_id):
        p = DATA_DIR / f.path
        now = sha256_file(p) if p.exists() else ""
        out.append(as_dict(f) | {"intact": now == f.sha256, "missing": not p.exists()})
    return out


def custody(session, post_id: int) -> list[dict]:
    return [audit.as_dict(r) for r in session.query(AuditLog).filter_by(case_id=post_id).order_by(AuditLog.id).all()]


def system_info() -> dict:
    """Describes the computer that captured the evidence (for Part A of the certificate)."""
    return {"hostname": _platform.node(), "os": f"{_platform.system()} {_platform.release()}",
            "python": _platform.python_version(), "software": f"MuleWatch {APP_VERSION}"}


# ----------------------------------------------------------------------------- screenshots

_q: "queue.Queue[int]" = queue.Queue()
_pending: set[int] = set()
_state = {"available": None, "error": "", "worker": False}


def screenshots_available() -> bool:
    if _state["available"] is None:
        try:
            import playwright.sync_api  # noqa: F401
            _state["available"] = SCREENSHOTS
        except ImportError:
            _state["available"] = False
            _state["error"] = "Playwright is not installed (pip install playwright && playwright install chromium)"
    return bool(_state["available"])


def status() -> dict:
    return {"screenshots": screenshots_available(), "error": _state["error"], "queued": len(_pending)}


def queue_screenshots(posts):
    """Ask for a full-page screenshot of every High/Critical case with a public URL that doesn't have one."""
    if not screenshots_available():
        return
    with SessionLocal() as s:
        have = {pid for (pid,) in s.query(EvidenceFile.post_id).filter_by(kind="screenshot").all()}
    for p in posts:
        if (p.id not in have and p.id not in _pending and p.url.startswith("http") and p.source != "preview"
                and LEVEL_RANK.get(p.risk_level, 0) >= LEVEL_RANK["High"]):
            _pending.add(p.id)
            _q.put(p.id)
    if _pending and not _state["worker"]:
        _state["worker"] = True
        threading.Thread(target=_worker, daemon=True, name="screenshots").start()


def _worker():
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=1,
                                      user_agent="Mozilla/5.0 MuleWatch-Evidence/2.0")
            while True:
                try:
                    pid = _q.get(timeout=60)
                except queue.Empty:
                    break
                try:
                    _shoot(ctx, pid)
                except Exception as e:          # one bad page must not stop the others
                    _state["error"] = f"{type(e).__name__}: {str(e)[:150]}"
                finally:
                    _pending.discard(pid)
            browser.close()
    except Exception as e:
        _state["available"] = False
        _state["error"] = f"Screenshots unavailable: {type(e).__name__}: {str(e)[:150]}"
        _pending.clear()
    finally:
        _state["worker"] = False


def _shoot(ctx, pid: int):
    with SessionLocal() as s:
        post = s.get(Post, pid)
        if not post:
            return
        url = post.url
    page = ctx.new_page()
    try:
        page.goto(url, wait_until="networkidle", timeout=20000)
        when = datetime.utcnow()
        path = case_dir(pid) / f"screenshot_{when.strftime('%Y%m%dT%H%M%SZ')}.png"
        page.screenshot(path=str(path), full_page=True)
    finally:
        page.close()
    with SessionLocal() as s:
        post = s.get(Post, pid)
        ef = _record(s, post, "screenshot", path, url, f"Full-page screenshot taken {ist(when)}")
        s.commit()
        audit.log(None, "evidence.screenshot", pid, {"path": ef.path, "sha256": ef.sha256, "url": url})


# ----------------------------------------------------------------------------- evidence pack

def build_pack(session, post, report_pdf: bytes, certificate: bytes | None) -> bytes:
    """ZIP with every evidence file, the evidence report, a draft Section 63 certificate, a manifest of
    SHA-256 hashes and the chain-of-custody log."""
    buf = io.BytesIO()
    files = verify(session, post.id)
    manifest = {"case": f"MW-{post.id:05d}", "generated_at_utc": datetime.utcnow().isoformat(timespec="seconds"),
                "source_url": post.url, "platform": post.platform, "evidence_hash_of_record": post.evidence_hash,
                "files": [], "system": system_info()}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            if f["missing"]:
                continue
            arc = "evidence/" + (f["name"] if f["name"].startswith(f["kind"]) else f"{f['kind']}_{f['name']}")
            z.write(DATA_DIR / f["path"], arc)
            manifest["files"].append({"file": arc, "sha256": f["sha256"], "bytes": f["size"], "kind": f["kind"],
                                      "captured_at_utc": f["captured_at"], "unchanged_since_capture": f["intact"],
                                      "source_url": f["source_url"]})
        z.writestr(f"MuleWatch-Case-MW-{post.id:05d}-report.pdf", report_pdf)
        if certificate:
            z.writestr(f"Section63-BSA-certificate-DRAFT-MW-{post.id:05d}.docx", certificate)
        z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        rows = ["id,at_utc,user,role,action,detail,row_hash"]
        for r in custody(session, post.id):
            det = (r["detail"] or "").replace('"', '""')
            rows.append(f'{r["id"]},{r["at"]},{r["username"]},{r["role"]},{r["action"]},"{det}",{r["hash"]}')
        z.writestr("chain_of_custody.csv", "\n".join(rows) + "\n")
        z.writestr("README.txt", (
            f"MuleWatch evidence pack for case MW-{post.id:05d}\n\n"
            "evidence/            files exactly as captured; manifest.json lists each SHA-256\n"
            "chain_of_custody.csv every capture, view and export of this case, from the hash-chained audit log\n"
            "*-report.pdf         the case evidence report\n"
            "Section63-*.docx     DRAFT certificate under Section 63(4) BSA, 2023, to be completed and signed\n\n"
            "To check a file: sha256sum evidence/<file>   (Windows: certutil -hashfile <file> SHA256)\n"))
    return buf.getvalue()
