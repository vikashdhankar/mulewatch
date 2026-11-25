"""Channel discovery against a fake Telethon client: filtering, dedup, scoring, labels, stop rule,
FloodWait handling, output format, and that no post text or contact value leaks into logs or files."""
import asyncio
import csv
from collections import Counter
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


class FakeSession:
    """Telethon's on-disk entity cache: knows the usernames in `cached`."""

    def __init__(self, client, cached=()):
        self.client = client
        self.cached = dict(cached) if isinstance(cached, dict) else {u: None for u in cached}

    def get_input_entity(self, username):
        if username not in self.cached:
            raise ValueError("not cached")
        ent = self.client.entities.get(username)
        return SimpleNamespace(username=username, id=ent.id if ent else self.cached[username])


class FakeClient:
    def __init__(self, search: dict, posts: dict, entities: dict | None = None, flood_once: bool = False,
                 subscribers: int = 1234, cached=(), flood_seconds: int = 7):
        self.search, self.posts, self.entities = search, posts, entities or {}
        self.flood_once, self.subscribers, self.flood_seconds = flood_once, subscribers, flood_seconds
        self.session = FakeSession(self, cached)
        self.calls = []

    async def __call__(self, req):
        self.calls.append(type(req).__name__)
        if isinstance(req, SearchRequest):
            if self.flood_once:
                self.flood_once = False
                raise FloodWaitError(request=None, capture=self.flood_seconds)
            return SimpleNamespace(chats=self.search.get(req.q, []), users=[], results=[])
        if isinstance(req, GetFullChannelRequest):
            return SimpleNamespace(full_chat=SimpleNamespace(participants_count=self.subscribers))
        raise AssertionError(f"unexpected request {type(req).__name__}")

    async def get_input_entity(self, username):
        self.calls.append("resolve_username")
        if username not in self.entities:
            raise ValueError("No user has that username")
        return SimpleNamespace(username=username, id=self.entities[username].id)

    async def get_entity(self, inputs):
        self.calls.append("get_entity")
        if isinstance(inputs, list):
            return [self.entities[x.username] for x in inputs]
        return self.entities[inputs.username]

    async def get_messages(self, entity, limit=30):
        self.calls.append("get_messages")
        return self.posts.get(entity.id, [])[:limit]


def cfg(fraud=(), legit=(), seeds=(), **scoring):
    s = {"posts_per_channel": 30, "contact_weight": 4.0, "title_weight": 0.5, "post_cap": 10.0,
         "likely_fraud": 5.0, "likely_legit": 2.0, "rajasthan_focus": 0.2, "search_limit": 100, **scoring}
    return {"fraud": [("english", k) for k in fraud], "legit": [("english", k) for k in legit],
            "seeds": [(x, "") if isinstance(x, str) else tuple(x) for x in seeds], "settings": s}


async def no_sleep(_):
    pass


def run(client, c, tmp_path, **kw):
    out = tmp_path / "channels.discovered.yaml"
    kw.setdefault("today", "2026-11-25")
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
    assert set(client.calls) <= {"SearchRequest", "resolve_username", "get_entity", "get_messages",
                                 "GetFullChannelRequest"}
    assert client.calls.count("get_entity") == 1                  # all seeds in one batched request


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
    res, _ = run(client, cfg(["current account kit", "payout account"]), tmp_path, target_fraud=2, target_rajasthan=0)
    assert res["stopped_at_target"]
    assert [r["keyword"] for r in res["keywords"]] == ["current account kit"]
    assert client.calls.count("SearchRequest") == 1


def test_floodwait_sleeps_and_retries(tmp_path):
    client = scenario()
    client.flood_once = True
    slept = []

    async def rec_sleep(s):
        slept.append(s)
    out = tmp_path / "d.yaml"
    res = asyncio.run(dc.discover(client, cfg(["current account kit"]), out, sleep=rec_sleep, today="2026-11-25"))
    assert 8 in slept and client.calls.count("SearchRequest") == 2 and res["candidates"] == 3
    assert any(x >= 20 for x in slept)                            # pace halved after the FloodWait: 10 s -> 20 s


def test_rate_limit_spacing(tmp_path):
    t = [0.0]
    slept = []

    async def fake_sleep(s):
        slept.append(s)
        t[0] += s
    budget = dc.DailyBudget(300, {}, "2026-11-25")
    d = dc.Discoverer(scenario(), cfg()["settings"], tp.RateLimiter(20, clock=lambda: t[0], sleep=fake_sleep), budget)
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
    assert len(c["legit"]) == 12 and len(c["seeds"]) == 6
    groups = Counter(g for g, _ in c["fraud"])
    assert groups == {"english": 26, "hinglish": 9, "hindi": 5, "crypto": 16, "rajasthan": 21 * 6 + 10 * 3}
    kws = [k for _, k in c["fraud"]]
    assert len(kws) == len(set(kws)) and "sri ganganagar usdt" in kws and "जयपुर खाता" in kws
    assert kws.index("rbl account") < kws.index("usdt seller") < kws.index("jaipur usdt")


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


# ----------------------------------------------------------------------------- geo, categories, seeds

from collect.rajasthan import places_in  # noqa: E402


@pytest.mark.parametrize("text,expected", [
    ("Jaipur current account kit", {"jaipur"}), ("जयपुर में खाता", {"jaipur"}),
    ("Jhunjhunun wale bhai", {"jhunjhunu"}), ("झुंझुनूं", {"jhunjhunu"}),
    ("sriganganagar", {"sri_ganganagar"}), ("Ganganagar", {"sri_ganganagar"}),
    ("Chittaurgarh", {"chittorgarh"}), ("PIN 302001", {"rajasthan_pin"}), ("pincode 333 001", {"rajasthan_pin"}),
    ("Price 300000", set()), ("₹300000", set()), ("300000 rs", set()), ("limit 340000 daily", set()),
    ("call 9829041736", set()), ("kotak bank", set()), ("Delhi 110001", set()),
])
def test_places(text, expected):
    assert places_in(text) == expected


RAJ_POSTS = ["Jaipur current account kit available, full kit passbook net banking, WhatsApp 9829041736",
             "Jodhpur payout account ready, commission per transaction, DM @kit_dealer_x",
             "जयपुर करंट अकाउंट किट उपलब्ध, खाता किराये पर, संपर्क t.me/kitwala_bhai"]
USDT_POSTS = ["USDT seller, INR to USDT best rate, binance p2p, f2f cash, DM @usdt_dealer_y",
              "Buy USDT TRC20, p2p trusted, tether rate today, call 9829041736",
              "USDT to INR f2f in Jaipur, p2p binance, commission 2%, WhatsApp 9829041736"]
INVEST_POSTS = ["Double money in 7 days! 100% profit guaranteed, investment plan daily return, DM @inv_x",
                "Trading profit daily, VIP signal, guaranteed return, join t.me/profit_x",
                "Forex signals, 100% profit, daily profit plan, WhatsApp 9829041736"]
TASK_POSTS = ["Part time job, work from home, daily payment, like videos and earn, DM @task_x",
              "Ghar baithe kamai, task job, daily income 3000, salary daily, contact 9829041736",
              "पार्ट टाइम जॉब, घर बैठे कमाई, रोज पेमेंट, संपर्क t.me/task_y"]


def scored(posts, title="x", **kw):
    c = dc.Candidate(id=1, username="u", title=title, kind="broadcast", **kw)
    dc.score_candidate(c, posts, [NOW], cfg()["settings"] | {"rajasthan_focus": 0.2})
    return c


def test_geo_score_and_focus():
    c = scored(RAJ_POSTS + FRAUD_POSTS)                           # 3 of 7 posts name a Rajasthan place
    assert c.geo_score == round(3 / 7, 3) and c.rajasthan_focus and c.top_district == "jaipur"
    assert c.districts["jaipur"] == 2 and c.districts["jodhpur"] == 1
    c = scored(FRAUD_POSTS)
    assert c.geo_score == 0 and not c.rajasthan_focus and c.top_district == ""


@pytest.mark.parametrize("posts,category", [
    (FRAUD_POSTS[:1] + RAJ_POSTS[::2], "account_sale"),
    (USDT_POSTS, "usdt_p2p"), (INVEST_POSTS, "crypto_investment_scam"), (TASK_POSTS, "task_job_scam"),
    (["Gaming payout available, payin payout, betting payout, settlement daily, commission per transaction",
      "Payin payout service, casino gaming payout, running account, WhatsApp 9829041736",
      "Payout account, fund transfer, per transaction 2%, DM @payout_x"], "payout_mule"),
    (LEGIT_POSTS, "legit_finance"),
    (["Good morning everyone", "Cricket match today", "Movie review: great film"], "unrelated"),
])
def test_categories(posts, category):
    assert scored(posts).category == category


def test_mixed_signals_are_unclear():
    tie = Counter({"usdt_p2p": 4, "payout_mule": 4})
    assert dc.decide_category(tie, "likely_fraud", False, 5) == "unclear"
    assert dc.secondary_category(tie, "unclear") == "payout_mule+usdt_p2p"
    near = Counter({"usdt_p2p": 4, "payout_mule": 3})               # ahead by one: still a winner
    assert dc.decide_category(near, "likely_fraud", False, 5) == "usdt_p2p"
    assert dc.secondary_category(near, "usdt_p2p") == "payout_mule"
    assert dc.decide_category(Counter({"usdt_p2p": 6, "account_sale": 3}), "likely_fraud", False, 5) == "usdt_p2p"
    assert dc.secondary_category(Counter({"usdt_p2p": 9, "account_sale": 3}), "usdt_p2p") == ""
    assert dc.decide_category(Counter({"usdt_p2p": 2}), "likely_fraud", False, 5) == "unclear"   # too few cues
    assert dc.decide_category(Counter({"legit_finance": 1}), "likely_legit", True, 5) == "legit_finance"
    assert dc.decide_category(Counter(), "likely_fraud", False, 0) == "unclear"


def test_investment_and_usdt_ads_score_as_fraud():
    assert scored(USDT_POSTS).label == "likely_fraud" and scored(INVEST_POSTS).label == "likely_fraud"


def test_awareness_share():
    c = scored(AWARE_POSTS + LEGIT_POSTS[:2])
    assert c.awareness_share == 0.5 and c.label == "likely_legit"


def test_seed_files_merge_and_keep_group(tmp_path):
    a, b = tmp_path / "a.yaml", tmp_path / "b.yaml"
    a.write_text("seeds:\n  - alpha_chan\n  - beta_chan\n")
    b.write_text("seeds:\n  - username: '@Beta_chan'\n    group: rajasthan_usdt\n  - {username: gamma_chan, group: usdt_p2p}\n"
                 "  - delta_chan\n")
    assert dc.load_seeds(a, b, tmp_path / "missing.yaml") == [
        ("alpha_chan", ""), ("beta_chan", "rajasthan_usdt"), ("gamma_chan", "usdt_p2p"), ("delta_chan", "")]


def test_seed_group_kept_in_output(tmp_path):
    seed = chan(8, "seed_chan", "Seed")
    client = FakeClient({}, {8: msgs(RAJ_POSTS)}, entities={"seed_chan": seed})
    c = cfg(seeds=[("seed_chan", "rajasthan_usdt")])
    _, out = run(client, c, tmp_path)
    entry = yaml.safe_load(out.read_text())["channels"][0]
    assert entry["seed_group"] == "rajasthan_usdt" and entry["found_by"] == ["seed list (group: rajasthan_usdt)"]
    assert entry["rajasthan_focus"] and entry["category"] == "account_sale"


def test_csv_columns(tmp_path):
    _, out = run(scenario(), cfg(["current account kit"]), tmp_path)
    header = out.with_suffix(".csv").read_text().splitlines()[0].split(",")
    assert header[:10] == ["username", "title", "subscribers", "last_post", "score", "category", "rajasthan_focus",
                           "geo_score", "lang_mix", "found_by"]
    row = next(csv.DictReader(open(out.with_suffix(".csv"))))
    assert row["lang_mix"].startswith("dev=") and ";rom=" in row["lang_mix"]


def raj_scenario(n_plain=4, n_raj=3):
    """n_plain fraud channels from 'kit seller', n_raj Rajasthan fraud channels from 'jaipur kit'."""
    plain = [chan(100 + i, f"plain_kit_{i}") for i in range(n_plain)]
    raj = [chan(200 + i, f"jaipur_kit_{i}") for i in range(n_raj)]
    other = [chan(300 + i, f"other_kit_{i}") for i in range(2)]
    news = [chan(400 + i, f"fin_news_{i}") for i in range(3)]
    posts = {**{c.id: msgs(FRAUD_POSTS) for c in plain + other}, **{c.id: msgs(RAJ_POSTS) for c in raj},
             **{c.id: msgs(LEGIT_POSTS) for c in news}}
    search = {"kit seller": plain, "usdt seller": other, "jaipur kit": raj, "nifty": news[:2], "sebi": news[2:]}
    return FakeClient(search, posts)


def raj_cfg():
    c = cfg(["kit seller", "usdt seller"], ["nifty", "sebi"])
    c["fraud"].append(("rajasthan", "jaipur kit"))
    return c


def test_stop_rule_keeps_searching_rajasthan_until_its_target(tmp_path):
    client = raj_scenario()
    res, _ = run(client, raj_cfg(), tmp_path, target_fraud=3, target_rajasthan=2, legit_target=2)
    searched = [r["keyword"] for r in res["keywords"]]
    assert "usdt seller" not in searched and "jaipur kit" in searched     # skipped once fraud target met
    assert res["skipped_keywords"] == 1 and res["rajasthan_fraud"] == 3
    assert "sebi" not in searched and res["legit_finance"] == 2           # legit target reached after 'nifty'
    assert res["districts"] == {"jaipur": 3}


def test_stops_when_both_targets_met(tmp_path):
    client = raj_scenario()
    res, _ = run(client, raj_cfg(), tmp_path, target_fraud=3, target_rajasthan=0)
    assert res["stopped_at_target"] and [r["keyword"] for r in res["keywords"]][:1] == ["kit seller"]
    assert client.calls.count("SearchRequest") == 1 + 2                    # 'kit seller' + both legit keywords


def test_report_prints_categories_and_districts(tmp_path):
    res, out = run(raj_scenario(), raj_cfg(), tmp_path, target_fraud=50, target_rajasthan=2)
    buf = io.StringIO()
    dc.print_report(res, out, stream=buf)
    text = buf.getvalue()
    assert "per category:" in text and "account_sale" in text and "legit_finance" in text
    assert "per district" in text and "jaipur" in text and "keywords exhausted" in text


# ----------------------------------------------------------------------------- pacing, budget, resume

def test_seeds_use_session_cache_before_resolving(tmp_path):
    seeds = {f"seed_{i}": chan(500 + i, f"seed_{i}") for i in range(4)}
    client = FakeClient({}, {500 + i: msgs(FRAUD_POSTS) for i in range(4)}, entities=seeds,
                        cached=["seed_0", "seed_1", "seed_2"])
    res, _ = run(client, cfg(seeds=list(seeds)), tmp_path)
    assert client.calls.count("resolve_username") == 1          # only the uncached seed
    assert client.calls.count("get_entity") == 1 and res["candidates"] == 4


def test_daily_budget_pauses_and_next_run_resumes(tmp_path):
    kws = ["current account kit", "payout account", "bank official"]
    first, out = run(scenario(), cfg(kws), tmp_path, daily_budget=12, max_new_per_keyword=3)
    assert first["paused"].startswith("daily budget") and first["requests_today"] <= 12
    assert first["keywords_done"] == 1                          # 'current account kit' only
    state = __import__("json").loads(out.with_name(out.stem + ".state.json").read_text())
    assert state["budget_date"] == "2026-11-25" and state["requests_today"] == first["requests_today"]

    # same day: nothing left, so no requests at all
    client = scenario()
    again, _ = run(client, cfg(kws), tmp_path, daily_budget=12, max_new_per_keyword=3)
    assert again["requests"] == 0 and client.calls == []

    # next day: continues with the remaining keywords, nothing done twice
    client = scenario()
    nxt, _ = run(client, cfg(kws), tmp_path, daily_budget=12, max_new_per_keyword=3, today="2026-11-26")
    assert nxt["finished"] and nxt["keywords_done"] == 3
    assert client.calls.count("SearchRequest") == 2
    searched = [r["keyword"] for r in nxt["keywords"]]
    assert searched.count("current account kit") == 1
    full, _ = run(scenario(), cfg(kws), tmp_path / "full", daily_budget=300, max_new_per_keyword=3)
    assert {c for c in full["labels"]} == {c for c in nxt["labels"]} and full["candidates"] == nxt["candidates"]


def test_long_floodwait_pauses_without_losing_work(tmp_path):
    client = scenario()
    client.flood_once, client.flood_seconds = True, 3600
    res, out = run(client, cfg(["current account kit"]), tmp_path)
    assert "wait 3600s" in res["paused"] and res["keywords_done"] == 0
    assert client.calls.count("SearchRequest") == 1              # no retry; it stopped
    res2, _ = run(scenario(), cfg(["current account kit"]), tmp_path, today="2026-11-26")
    assert res2["finished"] and res2["candidates"] == 3


def test_new_channels_per_keyword_are_capped(tmp_path):
    many = [chan(600 + i, f"kit_shop_{i}") for i in range(10)]
    client = FakeClient({"kit": many}, {c.id: msgs(FRAUD_POSTS) for c in many})
    res, out = run(client, cfg(["kit"]), tmp_path, max_new_per_keyword=4)
    assert res["candidates"] == 4 and client.calls.count("get_messages") == 4
    assert res["keywords"][-1]["capped"] == 6


def test_subscriber_count_only_fetched_for_likely_fraud(tmp_path):
    client = scenario()
    run(client, cfg(["current account kit", "payout account"], ["bank official"]), tmp_path)
    # likely_fraud without a count: kit_seller_one, payout_hub, kit_chat_group
    assert client.calls.count("GetFullChannelRequest") == 3


def test_rajasthan_priority_order():
    kws = [k for _, k in dc.expand_rajasthan({"places": ["jaipur", "tonk", "kota"], "priority_places": ["kota"],
                                              "suffixes": ["kit"], "hindi_places": ["जयपुर"],
                                              "hindi_suffixes": ["खाता"]})]
    assert kws == ["kota kit", "जयपुर खाता", "jaipur kit", "tonk kit"]


def test_only_one_telegram_job_at_a_time(tmp_path):
    lock = str(tmp_path / "t.lock")
    with tp.telegram_lock(lock):
        with pytest.raises(SystemExit):
            with tp.telegram_lock(lock):
                pass
    with tp.telegram_lock(lock):                                # released again
        pass


# ----------------------------------------------------------------------------- names and re-scoring

from collect.rajasthan import username_places  # noqa: E402


@pytest.mark.parametrize("name,expected", [
    ("USDT_BUYER_JAIPUR", {"jaipur"}), ("Delhi_jaipur_usdt_exchange", {"jaipur"}),
    ("Usdtsellerrajasthan", {"rajasthan"}), ("kota_kit_99", {"kota"}), ("KotaKit", {"kota"}),
    ("sriganganagarusdt", {"sri_ganganagar"}), ("kotakbank", set()), ("napali_x", set()), ("Geofreyy", set()),
])
def test_username_places(name, expected):
    assert username_places(name) == expected


def test_place_in_username_sets_rajasthan_focus():
    c = dc.Candidate(id=1, username="USDT_BUYER_JAIPUR", title="USDT buyer", kind="broadcast")
    dc.score_candidate(c, USDT_POSTS, [NOW], cfg()["settings"])
    assert c.geo_score == round(1 / 3, 3)                         # one post names Jaipur
    c2 = dc.Candidate(id=2, username="USDT_BUYER_JAIPUR", title="USDT buyer", kind="broadcast")
    dc.score_candidate(c2, USDT_POSTS[:2], [NOW], cfg()["settings"])
    assert c2.geo_score == 0 and c2.rajasthan_focus and c2.top_district == "jaipur" and c2.name_places == ["jaipur"]


def test_pay_username_counts_for_payout():
    c = dc.Candidate(id=1, username="dukepay2026", title="Duke", kind="broadcast")
    dc.score_candidate(c, ["Deposit and withdrawal agents needed, commission per transaction, DM @duke_x",
                           "Agent recruitment, INR deposit daily, WhatsApp 9829041736"], [NOW], cfg()["settings"])
    assert c.category == "payout_mule" and c.category_hits["payout_mule"] >= 3


def _old_state(tmp_path, cands):
    import json
    out = tmp_path / "channels.discovered.yaml"
    st = {"version": 1, "keywords_done": [], "rows": [], "seeds_done": [], "seeds_failed": [], "candidates": cands}
    out.with_name(out.stem + ".state.json").write_text(json.dumps(st))
    return out


def test_earlier_channels_get_name_signals_and_unclear_ones_are_reread(tmp_path):
    base = dict(kind="broadcast", found_by=["keyword 'x'"], role="fraud", posts_sampled=20, label="likely_fraud",
                score=9.0, inspected=True)
    old = [dict(base, id=1, username="USDT_BUYER_JAIPUR", title="USDT buyer", category="usdt_p2p"),
           dict(base, id=2, username="dukepay2026", title="Duke", category="unclear"),
           dict(base, id=3, username="gone_channel", title="Gone", category="unclear")]
    for c in old:
        c.pop("category_hits", None)
    _old_state(tmp_path, old)
    client = FakeClient({}, {2: msgs(["Deposit and withdrawal agents needed, commission per transaction",
                                      "Agent recruitment, payout daily, WhatsApp 9829041736"])},
                        cached={"dukepay2026": 2})
    res, out = run(client, cfg(), tmp_path)
    by = {c["username"]: c for c in yaml.safe_load(out.read_text())["channels"]}
    assert by["USDT_BUYER_JAIPUR"]["rajasthan_focus"] and by["USDT_BUYER_JAIPUR"]["top_district"] == "jaipur"
    assert by["USDT_BUYER_JAIPUR"]["category"] == "usdt_p2p"       # had a clear category: not re-read
    assert by["dukepay2026"]["category"] == "payout_mule"           # re-read once
    assert by["gone_channel"]["category"] == "unclear"              # not in the cache: no username lookup
    assert client.calls.count("get_messages") == 1 and "resolve_username" not in client.calls
    res2, _ = run(client, cfg(), tmp_path)                          # nothing is re-read a second time
    assert client.calls.count("get_messages") == 1
