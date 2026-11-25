"""Channel discovery against a fake Telethon client: filtering, dedup, scoring, labels, stop rule,
FloodWait handling, output format, and that no post text or contact value leaks into logs or files."""
import asyncio
import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import yaml

telethon = pytest.importorskip("telethon")
from telethon.errors import FloodWaitError  # noqa: E402
from telethon.tl.functions.channels import GetFullChannelRequest  # noqa: E402
from telethon.tl.functions.contacts import SearchRequest  # noqa: E402
from telethon.tl.types import Channel, Chat, ChatPhotoEmpty, User  # noqa: E402

from collect import discover_channels as dc  # noqa: E402
from collect import telegram_public as tp  # noqa: E402

NOW = datetime(2026, 11, 20, tzinfo=timezone.utc)
SECRET_PHONE = "9829041736"
SECRET_UPI = "kitwala77@ybl"
FRAUD_POSTS = [f"Corporate current account kit available, full kit with passbook ATM net banking. SBI HDFC. "
               f"Price 25000. WhatsApp {SECRET_PHONE}",
               f"Payout account ready, USDT to INR, commission per transaction. Pay {SECRET_UPI}",
               "Khata kiraye par do, roz 2000 kamao, DM @kit_dealer_x",
               "करंट अकाउंट किट उपलब्ध, खाता किराये पर, संपर्क t.me/kitwala_bhai"]
LEGIT_POSTS = ["RBI keeps repo rate unchanged at 6.5%, monetary policy statement released.",
               "Sensex up 300 points, Nifty closes at record high.", "New mutual fund NFO opens today."]
AWARE_POSTS = ["Beware! Renting your bank account is a crime. Never share your passbook or ATM card. Call 1930.",
               "सावधान! अपना खाता किराये पर न दें। साइबर अपराध की शिकायत 1930 पर करें।"]
ALL_TEXT = FRAUD_POSTS + LEGIT_POSTS + AWARE_POSTS


def chan(cid, username, title="Some channel", broadcast=True, megagroup=False, **kw):
    return Channel(id=cid, title=title, photo=ChatPhotoEmpty(), date=NOW, broadcast=broadcast, megagroup=megagroup,
                   username=username, **kw)


def msgs(texts, days_ago=0):
    return [SimpleNamespace(message=t, date=NOW - timedelta(days=days_ago + i), action=None) for i, t in enumerate(texts)]


class FakeClient:
    def __init__(self, search: dict, posts: dict, entities: dict | None = None, flood_once: bool = False,
                 subscribers: int = 1234):
        self.search, self.posts, self.entities = search, posts, entities or {}
        self.flood_once, self.subscribers = flood_once, subscribers
        self.calls = []

    async def __call__(self, req):
        self.calls.append(type(req).__name__)
        if isinstance(req, SearchRequest):
            if self.flood_once:
                self.flood_once = False
                raise FloodWaitError(request=None, capture=7)
            return SimpleNamespace(chats=self.search.get(req.q, []), users=[], results=[])
        if isinstance(req, GetFullChannelRequest):
            return SimpleNamespace(full_chat=SimpleNamespace(participants_count=self.subscribers))
        raise AssertionError(f"unexpected request {type(req).__name__}")

    async def get_entity(self, username):
        self.calls.append("get_entity")
        if username not in self.entities:
            raise ValueError("No user has that username")
        return self.entities[username]

    async def get_messages(self, entity, limit=30):
        self.calls.append("get_messages")
        return self.posts.get(entity.id, [])[:limit]


def cfg(fraud=(), legit=(), seeds=(), **scoring):
    s = {"posts_per_channel": 30, "contact_weight": 4.0, "title_weight": 0.5, "post_cap": 10.0,
         "likely_fraud": 5.0, "likely_legit": 2.0, "search_limit": 100, **scoring}
    return {"fraud": [("english", k) for k in fraud], "legit": [("english", k) for k in legit],
            "seeds": list(seeds), "settings": s}


async def no_sleep(_):
    pass


def run(client, c, tmp_path, **kw):
    out = tmp_path / "channels.discovered.yaml"
    res = asyncio.run(dc.discover(client, c, out, sleep=no_sleep, **kw))
    return res, out


# ----------------------------------------------------------------------------- scoring

def test_cues_rank_fraud_over_legit_and_awareness():
    fraud = [dc.cue_score(t) for t in FRAUD_POSTS]
    legit = [dc.cue_score(t) for t in LEGIT_POSTS]
    aware = [dc.cue_score(t) for t in AWARE_POSTS]
    assert min(fraud) >= 5 and max(legit) <= 0 and max(aware) < 2


def test_contacts_counted_not_returned():
    assert [dc.has_contact(t) for t in FRAUD_POSTS] == [True, True, True, True]
    assert not dc.has_contact(LEGIT_POSTS[0]) and not dc.has_contact(AWARE_POSTS[0])     # "1930" is no contact


def test_lang_mix():
    m = dc.lang_mix(["Khata kiraye par do aur paise kamao", "खाता किराये पर", "current account kit"])
    assert m["devanagari"] > 0 and m["roman_hindi"] > 0 and m["english"] > 0
    assert abs(sum(m.values()) - 1) < 0.01


def test_title_is_masked():
    assert dc.mask_title(f"Account kit call {SECRET_PHONE}") == "Account kit call [PHONE]"


# ----------------------------------------------------------------------------- discovery

def scenario():
    fraud1 = chan(1, "kit_seller_one", "Corporate Account Kit Seller")
    fraud2 = chan(2, "payout_hub", "Payout Hub")
    mega = chan(3, "kit_chat_group", "Kit chat", broadcast=False, megagroup=True)
    private = chan(4, None, "Private one")                       # no username: not public
    aware = chan(5, "cyber_alerts", "Cyber Alerts")
    bank = chan(6, "official_bank", "Bank official", verified=True)
    news = chan(7, "market_news_in", "Market news")
    seed = chan(8, "seed_chan", "Seed")
    search = {"current account kit": [fraud1, fraud2, mega, private, User(id=99), Chat(id=98, title="x", photo=ChatPhotoEmpty(), participants_count=1, date=NOW, version=1)],
              "payout account": [fraud2, aware],                  # fraud2 again: dedup by id
              "bank official": [bank, news, fraud1]}
    posts = {1: msgs(FRAUD_POSTS), 2: msgs(FRAUD_POSTS[1:]), 3: msgs(FRAUD_POSTS[:2] + LEGIT_POSTS),
             5: msgs(AWARE_POSTS), 6: msgs(LEGIT_POSTS[:1]), 7: msgs(LEGIT_POSTS), 8: msgs(FRAUD_POSTS[:1], 3)}
    return FakeClient(search, posts, entities={"seed_chan": seed})


def test_discovery_filters_dedupes_and_labels(tmp_path):
    client = scenario()
    res, out = run(client, cfg(["current account kit", "payout account"], ["bank official"],
                               seeds=["seed_chan", "missing_seed"]), tmp_path)
    doc = yaml.safe_load(out.read_text())
    by = {c["username"]: c for c in doc["channels"]}
    assert set(by) == {"kit_seller_one", "payout_hub", "kit_chat_group", "cyber_alerts", "official_bank",
                       "market_news_in", "seed_chan"}
    assert by["kit_seller_one"]["label"] == "likely_fraud" and by["payout_hub"]["label"] == "likely_fraud"
    assert by["seed_chan"]["label"] == "likely_fraud" and by["seed_chan"]["found_by"] == ["seed list"]
    assert by["kit_chat_group"]["kind"] == "megagroup"
    assert by["cyber_alerts"]["label"] == "likely_legit"               # awareness wording counts against
    assert by["official_bank"]["label"] == "likely_legit" and by["official_bank"]["verified"]
    assert by["market_news_in"]["label"] == "likely_legit"
    assert by["payout_hub"]["found_by"] == ["keyword 'current account kit'", "keyword 'payout account'"]
    assert by["kit_seller_one"]["found_by"][-1] == "keyword 'bank official'"
    assert by["kit_seller_one"]["contact_share"] == 1.0 and by["kit_seller_one"]["posts_sampled"] == 4
    assert by["kit_seller_one"]["subscribers"] == 1234 and by["kit_seller_one"]["last_post"] == "2026-11-20"
    assert all(c["approved"] is False for c in doc["channels"])
    assert by["kit_seller_one"]["reason"].startswith("auto-discovered ") and \
        by["kit_seller_one"]["reason"].endswith("by keyword 'current account kit'")
    scores = [c["score"] for c in doc["channels"]]
    assert scores == sorted(scores, reverse=True)
    assert res["labels"]["likely_fraud"] == 4
    # read-only: only search, resolve, history and full-channel requests were made
    assert set(client.calls) <= {"SearchRequest", "get_entity", "get_messages", "GetFullChannelRequest"}


def test_outputs_have_no_post_text_or_contacts(tmp_path, caplog):
    caplog.set_level(logging.DEBUG, logger="collect.discover")
    res, out = run(scenario(), cfg(["current account kit", "payout account"], ["bank official"], seeds=["seed_chan"]),
                   tmp_path)
    buf = io.StringIO()
    dc.print_report(res, out, stream=buf)
    blobs = [out.read_text(), out.with_suffix(".csv").read_text(),
             out.with_name(out.stem + ".keywords.csv").read_text(), caplog.text, buf.getvalue()]
    for blob in blobs:
        for secret in (SECRET_PHONE, SECRET_UPI, "kit_dealer_x", "kitwala_bhai", "Price 25000", "repo rate"):
            assert secret not in blob


def test_keyword_csv_counts(tmp_path):
    _, out = run(scenario(), cfg(["current account kit", "payout account"], ["bank official"]), tmp_path)
    rows = list(csv.DictReader(open(out.with_name(out.stem + ".keywords.csv"))))
    by = {r["keyword"]: r for r in rows}
    assert by["current account kit"]["results"] == "6" and by["current account kit"]["new_public"] == "3"
    assert by["payout account"]["new_public"] == "1" and by["payout account"]["likely_legit"] == "1"
    assert by["bank official"]["new_public"] == "2"


def test_stops_at_fraud_target(tmp_path):
    client = scenario()
    res, _ = run(client, cfg(["current account kit", "payout account"]), tmp_path, target_fraud=2)
    assert res["stopped_at_target"]
    assert [r["keyword"] for r in res["keywords"]] == ["(seed list)", "current account kit"]
    assert client.calls.count("SearchRequest") == 1


def test_floodwait_sleeps_and_retries(tmp_path):
    client = scenario()
    client.flood_once = True
    slept = []

    async def rec_sleep(s):
        slept.append(s)
    out = tmp_path / "d.yaml"
    res = asyncio.run(dc.discover(client, cfg(["current account kit"]), out, sleep=rec_sleep))
    assert 8 in slept and client.calls.count("SearchRequest") == 2 and res["candidates"] == 3


def test_rate_limit_spacing(tmp_path):
    t = [0.0]
    slept = []

    async def fake_sleep(s):
        slept.append(s)
        t[0] += s
    d = dc.Discoverer(scenario(), cfg()["settings"], tp.RateLimiter(20, clock=lambda: t[0], sleep=fake_sleep))
    asyncio.run(d.search("current account kit", "fraud"))
    asyncio.run(d.search("payout account", "fraud"))
    assert slept == [3.0]                                      # 20 per minute -> 3 s apart


def test_dry_run_makes_no_requests(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("dry run must not create a client")
    monkeypatch.setattr(dc, "make_client", boom)
    monkeypatch.chdir(tmp_path.parent)
    out = tmp_path / "x.yaml"
    root = __import__("pathlib").Path(__file__).resolve().parent.parent
    dc.main(["--dry-run", "--out", str(out), "--keywords", str(root / "config/discovery_keywords.yaml"),
             "--seeds", str(root / "config/discovery_seeds.yaml"), "--channels-config",
             str(root / "config/channels.yaml")])
    assert not out.exists()


def test_repo_configs_load():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    c = dc.load_discovery_config(root / "config/discovery_keywords.yaml", root / "config/discovery_seeds.yaml")
    assert len(c["fraud"]) == 40 and len(c["legit"]) == 5 and len(c["seeds"]) == 6
    assert {g for g, _ in c["fraud"]} == {"english", "hinglish", "hindi"}


# ----------------------------------------------------------------------------- collector approval gate

def test_collector_reads_only_approved_collectable_entries(tmp_path):
    p = tmp_path / "d.yaml"
    p.write_text(yaml.safe_dump({"channels": [
        {"username": "aaaa_fraud", "label": "likely_fraud", "approved": True},
        {"username": "bbbb_legit", "label": "likely_legit", "approved": True},
        {"username": "cccc_unclear", "label": "unclear", "approved": True},
        {"username": "dddd_notyet", "label": "likely_fraud", "approved": False},
        {"username": "eeee_nokey", "label": "likely_fraud"},
        {"username": "ffff_yes_str", "label": "likely_fraud", "approved": "yes"},
        {"username": "gggg_manual"},
    ]}))
    names = [c["username"] for c in tp.load_config(p)["channels"]]
    assert names == ["aaaa_fraud", "bbbb_legit", "gggg_manual"]
    assert tp.load_config(p)["channels"][0]["label"] == "likely_fraud"


def test_discovered_file_round_trips_into_collector(tmp_path):
    _, out = run(scenario(), cfg(["current account kit"]), tmp_path)
    assert tp.load_config(out)["channels"] == []               # nothing approved yet
    doc = yaml.safe_load(out.read_text())
    doc["channels"][0]["approved"] = True
    out.write_text(yaml.safe_dump(doc, allow_unicode=True))
    assert [c["username"] for c in tp.load_config(out)["channels"]] == [doc["channels"][0]["username"]]
