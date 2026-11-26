"""Import a dataset of posts (CSV, Excel, JSON, JSONL, a Telegram Desktop export, or a ZIP of any of these plus the
images they refer to) and score every post exactly like a live one.

Flow: upload -> parse + guess which column is which (preview) -> officer confirms the mapping -> background job
ingests each row (text, original time, channel/platform, author, link, image) -> cases, alerts, identifiers, seller
rings and evidence hashes appear as for crawled posts.

* Posts keep their original time; the channel goes into the platform label ("Telegram · @channel").
* Importing the same file twice adds nothing: each row gets a stable id from platform, channel, its own id or text and time.
* Images: a column naming a file inside the ZIP (path or just the file name), or an http(s) link (fetched with the
  same safety checks as "Check a link"). Only real images up to 6 MB are kept; OCR and image fingerprints run on them.
* Alerts show in the command center; Telegram push is off unless the officer asks for it (a dataset can hold
  hundreds of historical posts).
"""
import hashlib
import io
import json
import re
import secrets
import threading
import time
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import PurePosixPath

from . import audit
from .config import MEDIA_DIR
from .db import Post, SessionLocal

MAX_FILE = 60 * 1024 * 1024
MAX_ROWS = 20000
MAX_IMAGE = 6 * 1024 * 1024
DATA_EXT = (".json", ".jsonl", ".ndjson", ".csv", ".tsv", ".txt", ".xlsx", ".xlsm")
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")

FIELDS = {"text": "Post text", "time": "Posted at", "channel": "Channel / group", "platform": "Platform",
          "author": "Author / sender", "url": "Link to the post", "image": "Image (file in the ZIP or link)",
          "external_id": "Post id"}
GUESS = [   # first match wins; checked against the lower-cased column name
    ("external_id", r"^(id|message_?id|msg_?id|post_?id|tweet_?id)$"),
    ("text", r"^(text|message|msg|content|post|body|caption|post_?text|message_?text|full_?text|description)$"),
    ("time", r"date|time|timestamp|posted|created|published"),
    ("channel", r"channel|group|chat|community|subreddit|page|source_?name"),
    ("platform", r"platform|site|network|^source$|^app$"),
    ("author", r"author|user(name)?|sender|^from$|handle|posted_?by|account"),
    ("url", r"url|link|permalink|href"),
    ("image", r"image|photo|media|picture|poster|img|thumbnail|file"),
    ("text", r"text|message|content|caption"),
]

_uploads: dict[str, dict] = {}     # token -> parsed upload waiting for the mapping
_jobs: dict[int, dict] = {}        # job id -> progress (kept in memory; the posts themselves are in the database)
_lock = threading.Lock()


class ImportError_(Exception):
    pass


# ----------------------------------------------------------------------------- reading files

def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, list):        # Telegram export: text is a list of strings and {"type", "text"} pieces
        return "".join(x if isinstance(x, str) else str(x.get("text", "")) if isinstance(x, dict) else _cell(x)
                       for x in v)
    if isinstance(v, dict):
        return str(v.get("name") or v.get("username") or v.get("text") or json.dumps(v, ensure_ascii=False))
    return str(v)


def _flatten(obj: dict, prefix: str = "") -> dict:
    """One level of nesting is kept as 'outer.inner' columns ({"author": {"name": ..}} -> author.name)."""
    out = {}
    for k, v in obj.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict) and not prefix:
            for k2, v2 in v.items():
                out[f"{key}.{k2}"] = _cell(v2)
        else:
            out[key] = _cell(v)
    return out


def _records_from_json(data: bytes, name: str) -> tuple[list[dict], str, dict]:
    """(records, format, defaults). Handles a list, {"messages"| "posts"| "data"| "items": [...]}, JSONL, and the
    Telegram Desktop export (result.json: channel name at the top, messages below)."""
    text = data.decode("utf-8-sig", errors="replace")
    if name.endswith((".jsonl", ".ndjson")) or (text.lstrip().startswith("{") and _is_jsonl(text)):
        return [_flatten(json.loads(line)) for line in text.splitlines() if line.strip()], "JSON lines", {}
    doc = json.loads(text)
    defaults = {}
    if isinstance(doc, dict):
        if isinstance(doc.get("messages"), list) and ("type" in doc or "name" in doc):        # Telegram export
            defaults = {"platform": "Telegram", "channel": str(doc.get("name") or "")}
            if doc.get("username"):
                defaults["channel"] = "@" + str(doc["username"]).lstrip("@")
            msgs = [m for m in doc["messages"] if isinstance(m, dict) and m.get("type", "message") == "message"]
            recs = []
            for m in msgs:
                r = _flatten({k: v for k, v in m.items() if k not in ("text_entities", "reactions")})
                r["text"] = _cell(m.get("text"))
                recs.append(r)
            return recs, "Telegram export", defaults
        for key in ("messages", "posts", "data", "items", "records", "results"):
            if isinstance(doc.get(key), list):
                doc = doc[key]
                break
    if not isinstance(doc, list):
        raise ImportError_("The JSON file should hold a list of posts (or a Telegram export).")
    return [_flatten(r) for r in doc if isinstance(r, dict)], "JSON", defaults


def _is_jsonl(text: str) -> bool:
    lines = [l for l in text.splitlines()[:5] if l.strip()]
    try:
        return len(lines) > 1 and all(isinstance(json.loads(l), dict) for l in lines)
    except ValueError:
        return False


def _records_from_table(data: bytes, name: str) -> tuple[list[dict], str, dict]:
    from .complaints import _rows_from_csv, _rows_from_xlsx
    rows = _rows_from_xlsx(data) if name.endswith((".xlsx", ".xlsm")) else _rows_from_csv(data)
    start = next((i for i, r in enumerate(rows[:20]) if sum(1 for c in r if str(c).strip()) >= 2), None)
    if start is None:
        raise ImportError_("No header row found (the first row should name the columns).")
    headers = [str(h).strip() or f"Column {i + 1}" for i, h in enumerate(rows[start])]
    recs = [{h: (r[i] if i < len(r) else "") for i, h in enumerate(headers)}
            for r in rows[start + 1:] if any(str(c).strip() for c in r)]
    return recs, "Excel" if name.endswith((".xlsx", ".xlsm")) else "CSV", {}


def _read(data: bytes, name: str) -> tuple[list[dict], str, dict]:
    if name.endswith((".json", ".jsonl", ".ndjson")):
        return _records_from_json(data, name)
    if name.endswith(DATA_EXT):
        return _records_from_table(data, name)
    raise ImportError_("Upload a CSV, Excel, JSON or JSONL file, a Telegram export (result.json), or a ZIP of one with its images.")


def _from_zip(data: bytes) -> tuple[bytes, str, dict[str, bytes]]:
    """(data file bytes, its name, images by path and by bare file name)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ImportError_("That ZIP file is damaged.")
    infos = [i for i in zf.infolist() if not i.is_dir() and not i.filename.startswith("__MACOSX/")]
    if sum(i.file_size for i in infos) > 4 * MAX_FILE:
        raise ImportError_("The ZIP unpacks to more than 240 MB.")
    data_files = sorted((i for i in infos if i.filename.lower().endswith(DATA_EXT)),
                        key=lambda i: (PurePosixPath(i.filename).name.lower() != "result.json", i.filename.count("/"),
                                       i.filename))
    if not data_files:
        raise ImportError_("No CSV, Excel or JSON file found inside the ZIP.")
    images = {}
    for i in infos:
        if i.filename.lower().endswith(IMG_EXT) and i.file_size <= MAX_IMAGE:
            b = zf.read(i)
            path = i.filename.replace("\\", "/")
            images[path.lower()] = b
            images.setdefault(PurePosixPath(path).name.lower(), b)
            top, _, rest = path.partition("/")           # also findable relative to the data file's folder
            if rest:
                images.setdefault(rest.lower(), b)
    main = data_files[0]
    return zf.read(main), main.filename.lower(), images


def guess_mapping(columns: list[str], defaults: dict) -> dict:
    out, used = {}, set()
    for c in columns:
        low = c.lower().strip()
        field = ""
        for f, rx in GUESS:
            if f not in used and re.search(rx, low):
                field = f
                break
        out[c] = field
        if field:
            used.add(field)
    if defaults.get("platform") == "Telegram":            # Telegram export: these are the useful columns
        out = {c: {"text": "text", "date": "time", "id": "external_id", "from": "author", "photo": "image"}.get(c, "")
               for c in columns}
    return out


def parse_upload(filename: str, data: bytes, user) -> dict:
    name = (filename or "").lower()
    if len(data) > MAX_FILE:
        raise ImportError_("File too large (max 60 MB).")
    images: dict[str, bytes] = {}
    inner = name
    try:
        if name.endswith(".zip"):
            data, inner, images = _from_zip(data)
        records, fmt, defaults = _read(data, inner)
    except ImportError_:
        raise
    except (ValueError, UnicodeDecodeError, KeyError) as e:
        raise ImportError_(f"Couldn't read the file ({type(e).__name__}: {str(e)[:120]}).")
    if not records:
        raise ImportError_("The file has no posts in it.")
    truncated = max(0, len(records) - MAX_ROWS)
    records = records[:MAX_ROWS]
    columns = list(dict.fromkeys(k for r in records[:200] for k in r))
    mapping = guess_mapping(columns, defaults)
    token = secrets.token_urlsafe(12)
    with _lock:
        for k in [k for k, v in _uploads.items() if v["at"] < time.time() - 3600]:
            _uploads.pop(k, None)
        _uploads[token] = {"filename": filename, "records": records, "images": images, "defaults": defaults,
                           "user": user.username, "at": time.time()}
    return {"token": token, "filename": filename, "format": fmt + (" in a ZIP" if name.endswith(".zip") else ""),
            "rows": len(records), "truncated": truncated, "columns": columns,
            "preview": [[str(r.get(c, ""))[:160] for c in columns] for r in records[:5]],
            "mapping": mapping, "fields": FIELDS, "images": len({id(b) for b in images.values()}),
            "platform": defaults.get("platform", ""), "channel": defaults.get("channel", "")}


# ----------------------------------------------------------------------------- one row -> post fields

def parse_time(v: str) -> datetime | None:
    """ISO 8601, Unix seconds or milliseconds, or the usual Indian date formats. Returns naive UTC."""
    v = str(v or "").strip()
    if not v:
        return None
    if re.fullmatch(r"\d{9,13}(\.\d+)?", v):
        x = float(v)
        return datetime.fromtimestamp(x / 1000 if x > 1e11 else x, timezone.utc).replace(tzinfo=None)
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d
    except ValueError:
        pass
    from .complaints import _date
    for fmt in ("%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M %p", "%d/%m/%Y %I:%M %p", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    return _date(v)


def row_fields(rec: dict, mapping: dict, defaults: dict) -> dict:
    get = {}
    for col, field in mapping.items():
        if field and field in FIELDS and str(rec.get(col, "")).strip() and field not in get:
            get[field] = str(rec[col]).strip()
    channel = get.get("channel") or defaults.get("channel", "")
    platform = (get.get("platform") or defaults.get("platform") or "Imported").strip()[:30]
    return {"text": get.get("text", ""), "time": parse_time(get.get("time", "")), "channel": channel[:80],
            "platform": platform, "author": (get.get("author") or channel)[:120], "url": get.get("url", "")[:500],
            "image": get.get("image", ""), "external_id": get.get("external_id", "")}


def remote_id(f: dict) -> str:
    key = "|".join([f["platform"].lower(), f["channel"].lower(),
                    f["external_id"] or f["text"], f["time"].isoformat() if f["time"] and not f["external_id"] else ""])
    return "import:" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:32]


def _save_image(ref: str, images: dict[str, bytes], stem: str) -> str:
    """Saved file name under MEDIA_DIR, or ""."""
    if not ref:
        return ""
    if ref.lower().startswith(("http://", "https://")):
        from .fetcher import FetchError, download_image
        try:
            return download_image(ref, stem) or ""
        except FetchError:
            return ""
    key = ref.replace("\\", "/").lstrip("./").lower()
    data = images.get(key) or images.get(PurePosixPath(key).name)
    if not data:
        return ""
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
            ext = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif"}.get(im.format, "")
    except Exception:
        return ""
    if not ext:
        return ""
    name = f"{stem}{ext}"
    (MEDIA_DIR / name).write_bytes(data)
    return name


# ----------------------------------------------------------------------------- the job

def start_import(token: str, mapping: dict, platform: str, channel: str, label: str, push: bool, user) -> dict:
    with _lock:
        up = _uploads.pop(token, None)
    if not up:
        raise ImportError_("This upload has expired. Choose the file again.")
    if "text" not in mapping.values() and "image" not in mapping.values():
        raise ImportError_("Choose the column that holds the post text (or an image column).")
    defaults = dict(up["defaults"])
    if platform.strip():
        defaults["platform"] = platform.strip()
    if channel.strip():
        defaults["channel"] = channel.strip()
    with _lock:
        jid = max(_jobs, default=0) + 1
        _jobs[jid] = {"id": jid, "label": (label or up["filename"]).strip()[:160], "filename": up["filename"],
                      "by": user.username, "started": datetime.utcnow().isoformat(), "finished": None,
                      "status": "running", "total": len(up["records"]), "done": 0, "added": 0, "duplicates": 0,
                      "empty": 0, "errors": 0, "images": 0, "levels": {}, "post_ids": [], "error": ""}
    audit.log(user, "import.started", detail={"job": jid, "file": up["filename"], "rows": len(up["records"]),
                                               "mapping": {k: v for k, v in mapping.items() if v}})
    threading.Thread(target=_run, args=(jid, up, mapping, defaults, push), daemon=True, name=f"import-{jid}").start()
    return {"id": jid, "rows": len(up["records"])}


def _run(jid: int, up: dict, mapping: dict, defaults: dict, push: bool):
    from .pipeline import ingest, recompute_all
    job = _jobs[jid]
    try:
        with SessionLocal() as s:
            known = {r for (r,) in s.query(Post.remote_id).filter(Post.remote_id.like("import:%")).all()}
        batch = 0
        s = SessionLocal()
        try:
            for rec in up["records"]:
                if job["status"] == "cancelled":
                    break
                try:
                    f = row_fields(rec, mapping, defaults)
                    rid = remote_id(f)
                    if rid in known:
                        job["duplicates"] += 1
                    else:
                        image = _save_image(f["image"], up["images"], "import_" + rid[7:19])
                        if not f["text"].strip() and not image:
                            job["empty"] += 1
                        else:
                            job["images"] += bool(image)
                            platform = f["platform"] + (f" · {f['channel']}" if f["channel"] else "")
                            p = ingest(s, text=f["text"][:20000], platform=platform[:40], author=f["author"],
                                       url=f["url"], image_path=image, posted_at=f["time"], source="import",
                                       recompute=False)
                            p.remote_id = rid
                            known.add(rid)
                            job["added"] += 1
                            job["post_ids"].append(p.id)
                            job["levels"][p.risk_level] = job["levels"].get(p.risk_level, 0) + 1
                            batch += 1
                except Exception as e:               # one bad row must not stop the import
                    s.rollback()
                    job["errors"] += 1
                    job["error"] = f"{type(e).__name__}: {str(e)[:160]}"
                job["done"] += 1
                if batch >= 25:                      # short write transactions: the crawler shares the database
                    s.commit()
                    batch = 0
            s.commit()
            if job["added"]:
                job["status"] = "linking"
                recompute_all(s, alert=True, push=push)
                s.commit()
        finally:
            s.close()
        if job["status"] != "cancelled":
            job["status"] = "done"
    except Exception as e:
        traceback.print_exc()
        job["status"], job["error"] = "failed", f"{type(e).__name__}: {str(e)[:200]}"
    job["finished"] = datetime.utcnow().isoformat()


def cancel(jid: int) -> bool:
    job = _jobs.get(jid)
    if not job or job["status"] not in ("running",):
        return False
    job["status"] = "cancelled"
    return True


def job_out(jid: int, with_posts: bool = False) -> dict | None:
    job = _jobs.get(jid)
    if not job:
        return None
    out = {k: v for k, v in job.items() if k != "post_ids"}
    if with_posts and job["post_ids"]:
        with SessionLocal() as s:
            posts = (s.query(Post).filter(Post.id.in_(job["post_ids"]))
                     .order_by(Post.risk_score.desc(), Post.id).limit(25).all())
            out["top"] = [{"id": p.id, "risk_level": p.risk_level, "risk_score": p.risk_score, "category": p.category,
                           "platform": p.platform, "author": p.author, "excerpt": (p.text or p.ocr_text or "")[:160],
                           "posted_at": p.posted_at.isoformat() if p.posted_at else None,
                           "cluster_size": p.cluster_size or 1} for p in posts]
    return out


def jobs() -> list[dict]:
    return [job_out(j) for j in sorted(_jobs, reverse=True)[:20]]
