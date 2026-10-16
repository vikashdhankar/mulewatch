from datetime import datetime

from sqlalchemy import (JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer,
                        String, Text, create_engine)
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 20} if DATABASE_URL.startswith("sqlite") else {},
)

if DATABASE_URL.startswith("sqlite"):
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        # crawler thread, API requests and the live-event stream all touch the DB at once
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True)
    platform = Column(String(40), index=True, default="unknown")
    author = Column(String(120), default="")
    url = Column(String(500), default="")
    text = Column(Text, default="")
    image_path = Column(String(300), default="")      # relative to MEDIA_DIR
    ocr_text = Column(Text, default="")
    image_phash = Column(String(32), default="")
    language = Column(String(20), default="en")
    source = Column(String(30), default="manual")      # forum | telegram | manual | extension
    remote_id = Column(String(120), default="", index=True)   # id on the monitored site
    takedown = Column(String(20), default="")                # requested | done
    posted_at = Column(DateTime, default=datetime.utcnow, index=True)
    ingested_at = Column(DateTime, default=datetime.utcnow)

    entities = Column(JSON, default=dict)     # {"phone": [...], "upi": [...], ...}
    matches = Column(JSON, default=list)      # keyword hits with spans
    scores = Column(JSON, default=dict)       # breakdown
    reasons = Column(JSON, default=list)      # human readable evidence lines
    llm = Column(JSON, default=dict)          # optional LLM opinion

    risk_score = Column(Float, default=0, index=True)
    risk_level = Column(String(12), default="Low", index=True)
    category = Column(String(40), default="Benign", index=True)

    cluster_id = Column(Integer, nullable=True, index=True)
    cluster_size = Column(Integer, default=1)
    related = Column(JSON, default=list)      # [{"id":..,"why":[..]}]

    label = Column(String(20), nullable=True)  # investigator verdict: confirmed | false_positive
    train_label = Column(Integer, nullable=True)  # labelled training data (1 suspicious / 0 benign)
    evidence_hash = Column(String(64), default="")

    # ---- police case workflow (see workflow.py)
    status = Column(String(24), default="NEW", index=True)
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    fir_number = Column(String(60), default="")
    police_station = Column(String(120), default="")
    case_notes = Column(Text, default="")
    status_changed_at = Column(DateTime, nullable=True)
    notice_sent_at = Column(DateTime, nullable=True)      # platform's removal window starts here
    removed_at = Column(DateTime, nullable=True)
    deadline_alerts = Column(String(20), default="")      # "warn" / "warn,overdue" once sent

    # ---- complaint matching (complaints.py) — only ids/counts here, the complaint data stays encrypted
    complaint_matches = Column(JSON, default=list)        # [{"complaint": pk, "kind": "phone"}]
    complaint_count = Column(Integer, default=0, index=True)
    complaint_amount = Column(Float, default=0)

    # ---- prioritisation and follow-up
    recruiter_score = Column(Float, default=0, index=True)
    recruiter_reasons = Column(JSON, default=list)
    repost_of = Column(Integer, nullable=True, index=True)  # case that was taken down and reappeared as this one
    jurisdiction = Column(JSON, default=dict)


class WatchItem(Base):
    __tablename__ = "watchlist"
    id = Column(Integer, primary_key=True)
    kind = Column(String(20))      # phone | upi | telegram | whatsapp | url | keyword ...
    value = Column(String(200), index=True)
    note = Column(String(300), default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("posts.id"), index=True)
    level = Column(String(12))
    reason = Column(String(300))
    delivered = Column(Boolean, default=False)
    channel = Column(String(30), default="dashboard")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    seen = Column(Boolean, default=False)


class KeywordStat(Base):
    """Investigator feedback per lexicon term -> adaptive weights."""
    __tablename__ = "keyword_stats"
    term = Column(String(120), primary_key=True)
    confirmed = Column(Integer, default=0)
    false_positive = Column(Integer, default=0)


class Setting(Base):
    """Small key/value store for things set at runtime (e.g. the chat that receives alerts)."""
    __tablename__ = "settings"
    key = Column(String(60), primary_key=True)
    value = Column(String(300), default="")


def get_setting(key: str, default: str = "") -> str:
    with SessionLocal() as s:
        row = s.get(Setting, key)
        return row.value if row else default


def set_setting(key: str, value: str | None):
    with SessionLocal() as s:
        row = s.get(Setting, key)
        if value is None:
            if row:
                s.delete(row)
        elif row:
            row.value = value
        else:
            s.add(Setting(key=key, value=value))
        s.commit()


class Report(Base):
    """A citizen report received through the Telegram reporting bot. Several reports can point to the
    same case (people forwarding the same ad)."""
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("posts.id"), index=True)
    chat_id = Column(String(40), index=True)        # needed to send the reporter updates
    reporter_hash = Column(String(16), index=True)  # shown in the UI instead of the person
    reporter_name = Column(String(80), default="")
    content_key = Column(String(32), index=True)
    origin = Column(String(200), default="")        # "forwarded from channel @x" etc.
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Source(Base):
    """A monitored website / channel."""
    __tablename__ = "sources"
    id = Column(Integer, primary_key=True)
    kind = Column(String(20))          # forum | telegram
    name = Column(String(120))
    url = Column(String(300))
    enabled = Column(Boolean, default=True)
    last_crawl = Column(DateTime, nullable=True)
    last_status = Column(String(200), default="")
    items_seen = Column(Integer, default=0)
    cursor = Column(String(100), default="")   # last seen remote id


class User(Base):
    """A police user of the command center."""
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(60), unique=True, index=True)
    name = Column(String(120), default="")
    designation = Column(String(80), default="")        # e.g. Sub-Inspector, SHO
    police_station = Column(String(120), default="")
    role = Column(String(20), default="ANALYST")         # ANALYST | IO | SUPERVISOR
    password_hash = Column(String(100))
    active = Column(Boolean, default=True)
    session_version = Column(Integer, default=1)          # bump to sign the user out everywhere
    must_change_password = Column(Boolean, default=False)
    telegram_chat_id = Column(String(40), default="")
    telegram_code = Column(String(12), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)


class AuditLog(Base):
    """Append-only, hash-chained record of who did what. SQLite triggers block UPDATE and DELETE."""
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    at = Column(DateTime, default=datetime.utcnow, index=True)
    user_id = Column(Integer, nullable=True, index=True)
    username = Column(String(60), default="")
    role = Column(String(20), default="")
    action = Column(String(60), index=True)
    case_id = Column(Integer, nullable=True, index=True)
    detail = Column(Text, default="")
    ip = Column(String(64), default="")
    prev_hash = Column(String(64), default="")
    hash = Column(String(64), default="")


class ComplaintImport(Base):
    __tablename__ = "complaint_imports"
    id = Column(Integer, primary_key=True)
    label = Column(String(160), default="")
    filename = Column(String(200), default="")
    imported_by = Column(String(60), default="")
    imported_at = Column(DateTime, default=datetime.utcnow)
    rows = Column(Integer, default=0)
    skipped = Column(Integer, default=0)
    mapping = Column(JSON, default=dict)


class Complaint(Base):
    """One victim complaint (NCRP / 1930 export). Everything identifying is in the encrypted payload;
    only date, amount and district stay readable for statistics."""
    __tablename__ = "complaints"
    id = Column(Integer, primary_key=True)
    import_id = Column(Integer, ForeignKey("complaint_imports.id"), index=True)
    ref_hash = Column(String(64), unique=True, index=True)   # HMAC of the complaint number (dedupe)
    complaint_date = Column(DateTime, nullable=True)
    amount = Column(Float, default=0)
    district = Column(String(80), default="")
    payload = Column(Text, default="")                      # Fernet-encrypted JSON


class ComplaintIdent(Base):
    """Keyed hash of each identifier in a complaint, so cases can be matched without decrypting."""
    __tablename__ = "complaint_idents"
    id = Column(Integer, primary_key=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id"), index=True)
    kind = Column(String(20))
    digest = Column(String(64), index=True)


class EvidenceFile(Base):
    """A file captured as evidence for a case, with its SHA-256 recorded at capture time."""
    __tablename__ = "evidence_files"
    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("posts.id"), index=True)
    kind = Column(String(20))              # html | screenshot | image | text
    path = Column(String(300))             # relative to EVIDENCE_DIR
    sha256 = Column(String(64))
    size = Column(Integer, default=0)
    source_url = Column(String(500), default="")
    captured_at = Column(DateTime, default=datetime.utcnow)
    note = Column(String(300), default="")


class BulkJob(Base):
    """A list of links an officer collected, checked one by one in the background."""
    __tablename__ = "bulk_jobs"
    id = Column(Integer, primary_key=True)
    label = Column(String(160), default="")
    created_by = Column(String(60), default="")
    created_by_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String(16), default="queued")      # queued | running | done | cancelled
    total = Column(Integer, default=0)


class BulkItem(Base):
    __tablename__ = "bulk_items"
    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("bulk_jobs.id"), index=True)
    url = Column(String(500))
    note = Column(String(300), default="")             # text next to the link in the officer's file
    status = Column(String(16), default="queued")      # queued | done | existing | error | cancelled
    post_id = Column(Integer, nullable=True)
    error = Column(String(300), default="")
    checked_at = Column(DateTime, nullable=True)


def _migrate():
    """create_all() never adds columns to an existing table. Add any that are missing so a database
    from an earlier version keeps working (SQLite ALTER TABLE ADD COLUMN)."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = col.type.compile(engine.dialect)
                default = ""
                if col.default is not None and getattr(col.default, "is_scalar", False):
                    v = col.default.arg
                    default = f" DEFAULT {int(v) if isinstance(v, bool) else repr(v) if isinstance(v, str) else v}"
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {ddl}{default}'))
        if DATABASE_URL.startswith("sqlite"):
            for op in ("UPDATE", "DELETE"):
                conn.execute(text(f"CREATE TRIGGER IF NOT EXISTS audit_no_{op.lower()} BEFORE {op} ON audit_log "
                                  "BEGIN SELECT RAISE(ABORT, 'the audit log is append-only'); END"))


def init_db():
    Base.metadata.create_all(engine)
    _migrate()
