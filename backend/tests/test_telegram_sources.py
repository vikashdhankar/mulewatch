"""Live Telegram sources: only hand-approved channels are added, and channels are polled in turn."""
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("MW_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crawler, telegram_sources  # noqa: E402
from app.db import SessionLocal, Source, init_db  # noqa: E402

YAML = """
generated: test
channels:
  - {username: demo_fraud_one, approved: true, label: likely_fraud, category: usdt_p2p, top_district: Jaipur}
  - {username: demo_legit_one, approved: true, label: likely_legit, category: legit_finance}
  - {username: demo_suggested, approved: false, label: likely_fraud, category: payout_mule}
  - {username: "bad name!", approved: true}
"""


def test_only_approved_channels_are_added_and_unapproved_switched_off(tmp_path):
    init_db()
    with SessionLocal() as s:                       # shared test database: start without Telegram sources
        s.query(Source).filter_by(kind="telegram").delete()
        s.commit()
    y = tmp_path / "channels.yaml"
    y.write_text(YAML, encoding="utf-8")
    dry = telegram_sources.sync(y, dry_run=True)
    assert dry["added"] == ["demo_fraud_one", "demo_legit_one"]
    with SessionLocal() as s:
        assert not s.query(Source).filter_by(kind="telegram").count()      # dry run wrote nothing
    r = telegram_sources.sync(y)
    assert r["approved"] == 2 and len(r["added"]) == 2
    with SessionLocal() as s:
        src = s.query(Source).filter_by(kind="telegram").order_by(Source.id).all()
        assert [x.url for x in src] == ["https://t.me/s/demo_fraud_one", "https://t.me/s/demo_legit_one"]
        assert src[0].name == "@demo_fraud_one (fraud · usdt_p2p · Jaipur)"
    assert telegram_sources.sync(y)["added"] == []                          # idempotent
    y.write_text(YAML.replace("demo_legit_one, approved: true", "demo_legit_one, approved: false"), encoding="utf-8")
    assert telegram_sources.sync(y)["switched_off"] == ["demo_legit_one"]
    with SessionLocal() as s:
        off = s.query(Source).filter_by(url="https://t.me/s/demo_legit_one").one()
        assert off.enabled is False                                         # kept, not deleted


def test_telegram_sources_are_polled_in_turn():
    now = datetime(2026, 11, 28, 10, 0)
    srcs = [SimpleNamespace(id=1, kind="forum", last_crawl=now),
            SimpleNamespace(id=2, kind="telegram", last_crawl=now - timedelta(seconds=30)),     # polled recently
            SimpleNamespace(id=3, kind="telegram", last_crawl=now - timedelta(hours=1)),
            SimpleNamespace(id=4, kind="telegram", last_crawl=None),                            # never polled
            SimpleNamespace(id=5, kind="telegram", last_crawl=now - timedelta(hours=2))]
    assert crawler._due_telegram(srcs, now) == {4}                     # one per cycle, never-polled first
    srcs[3].last_crawl = now
    assert crawler._due_telegram(srcs, now) == {5}                     # then the longest-waiting
    assert crawler._due_telegram([srcs[1]], now) == set()             # not again within TELEGRAM_INTERVAL
