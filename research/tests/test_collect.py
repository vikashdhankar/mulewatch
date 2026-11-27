import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

telethon = pytest.importorskip("telethon")
from collect import telegram_public as tp  # noqa: E402


@pytest.mark.parametrize("entry,expected", [
    ("@SomeChannel", "SomeChannel"), ("https://t.me/s/some_chan", "some_chan"),
    ("t.me/some_chan/123", "some_chan"), ("some_chan", "some_chan"),
])
def test_username_normalised(entry, expected):
    assert tp.normalize_username(entry) == expected


@pytest.mark.parametrize("entry", ["https://t.me/+AbCdEf123", "t.me/joinchat/AAAAAE", "+AbCdEf", "ab", "1abc"])
def test_invite_links_and_bad_names_rejected(entry):
    with pytest.raises(tp.ConfigError):
        tp.normalize_username(entry)


def test_config_dedupes_and_parses_since(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("channels:\n  - username: '@abcd_e'\n    since: 2025-03-01\n  - abcd_E\nsettings:\n  requests_per_minute: 10\n")
    cfg = tp.load_config(p)
    assert [c["username"] for c in cfg["channels"]] == ["abcd_e"]
    assert cfg["channels"][0]["since"].isoformat() == "2025-03-01"
    assert cfg["settings"]["requests_per_minute"] == 10


def test_config_rejects_aggressive_rate(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("channels: []\nsettings:\n  requests_per_minute: 500\n")
    with pytest.raises(tp.ConfigError):
        tp.load_config(p)


def test_rate_limiter_spaces_calls():
    t = [0.0]
    slept = []

    async def fake_sleep(s):
        slept.append(s)
        t[0] += s

    lim = tp.RateLimiter(30, clock=lambda: t[0], sleep=fake_sleep)

    async def go():
        for _ in range(3):
            await lim.wait()
    asyncio.run(go())
    assert slept == [2.0, 2.0]


@pytest.mark.parametrize("cls", ["JoinChannelRequest", "ImportChatInviteRequest", "SendMessageRequest"])
def test_client_blocks_join_and_send(tmp_path, cls):
    from telethon.tl.functions import channels, messages
    mod = channels if hasattr(channels, cls) else messages
    req_cls = getattr(mod, cls)
    req = req_cls.__new__(req_cls)          # contents don't matter; the type is checked first
    client = tp.make_client(str(tmp_path / "s"), 1, "x")
    with pytest.raises(tp.ReadOnlyViolation):
        asyncio.run(client(req))


def test_only_public_broadcast_channels():
    from telethon.tl.types import Channel, Chat
    ch = Channel.__new__(Channel)
    ch.username, ch.broadcast, ch.megagroup = "pub", True, False
    assert tp.is_public_channel(ch)
    ch.megagroup, ch.broadcast = True, False
    assert not tp.is_public_channel(ch)
    ch.megagroup, ch.broadcast, ch.username = False, True, None
    assert not tp.is_public_channel(ch)
    assert not tp.is_public_channel(Chat.__new__(Chat))


def test_record_fields():
    msg = SimpleNamespace(id=42, date=datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc), message="hello",
                          photo=object(), media=object(), views=120, forwards=3, edit_date=None)
    r = tp.to_record(msg, "SomeChan", "ocr words")
    assert r["post_id"] == "tg:somechan:42"
    assert r["channel"] == "somechan" and r["media_type"] == "photo"
    assert r["views"] == 120 and r["ocr_text"] == "ocr words"
    assert r["date"].startswith("2026-01-02T03:04")


class HistoryClient:
    """iter_messages like Telethon: newest first, or oldest first with reverse=True; min_id excludes older."""

    def __init__(self, ids):
        from telethon.tl.types import Channel
        self.ch = Channel.__new__(Channel)
        self.ch.username, self.ch.broadcast, self.ch.megagroup = "pubchan", True, False
        self.ids, self.calls = ids, []

    async def get_entity(self, name):
        return self.ch

    async def iter_messages(self, entity, limit=None, min_id=0, reverse=False, wait_time=None, offset_date=None):
        self.calls.append({"limit": limit, "min_id": min_id, "reverse": reverse})
        ids = [i for i in sorted(self.ids, reverse=not reverse) if i > min_id][:limit]
        for i in ids:
            yield SimpleNamespace(id=i, date=datetime(2026, 11, 1, tzinfo=timezone.utc), message=f"post {i}",
                                  photo=None, media=None, document=None, views=1, forwards=0, edit_date=None,
                                  action=None)


def _collect(client, last_id, out, max_posts):
    settings = {"max_posts_per_channel": max_posts, "requests_per_minute": 600, "ocr_images": False,
                "ocr_lang": "hin+eng", "max_image_bytes": 1}
    lim = tp.RateLimiter(6000)
    return asyncio.run(tp.collect_channel(client, {"username": "pubchan"}, settings, lim, last_id, out))


def test_first_pass_takes_the_newest_posts_then_continues(tmp_path):
    import json
    out = tmp_path / "raw.jsonl"
    client = HistoryClient(range(1, 21))
    last = _collect(client, 0, out, 5)
    ids = [json.loads(x)["message_id"] for x in out.read_text().splitlines()]
    assert ids == [16, 17, 18, 19, 20] and last == 20                 # newest five, written oldest first
    client.ids = range(1, 24)
    last = _collect(client, last, out, 5)
    ids = [json.loads(x)["message_id"] for x in out.read_text().splitlines()]
    assert ids[5:] == [21, 22, 23] and last == 23 and client.calls[-1]["reverse"]


def test_approved_only(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("channels:\n- hand_picked_one\n- {username: appr_one, approved: true, label: likely_fraud}\n"
                 "- {username: not_appr, approved: false, label: likely_fraud}\n")
    assert [c["username"] for c in tp.load_config(p)["channels"]] == ["hand_picked_one", "appr_one"]
    assert [c["username"] for c in tp.load_config(p, approved_only=True)["channels"]] == ["appr_one"]
