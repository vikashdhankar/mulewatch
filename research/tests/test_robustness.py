import random

import pytest

from robustness.attacks import (Paraphraser, attack_examples, char_substitution, devanagari_to_roman, emoji_swap,
                                transliterate)

POSTS = ["Current account kit ready, call [PHONE] or pay [UPI]",
         "Apna khata do aur roz 2000 kamao, WhatsApp [PHONE]",
         "खाता किराये पर दें, संपर्क करें [PHONE]"]


@pytest.mark.parametrize("fn", [char_substitution, transliterate, emoji_swap])
@pytest.mark.parametrize("text", POSTS)
def test_attacks_change_text_but_keep_placeholders(fn, text):
    out = fn(text, random.Random(1)) if fn is not transliterate else fn(text)
    assert out.count("[PHONE]") == text.count("[PHONE]") and out.count("[UPI]") == text.count("[UPI]")
    if fn is not emoji_swap or "account" in text or "khata" in text:
        assert out != text


def test_char_substitution_is_seeded():
    assert char_substitution(POSTS[0], random.Random(5)) == char_substitution(POSTS[0], random.Random(5))


def test_devanagari_to_roman():
    assert devanagari_to_roman("खाता") == "khata"
    assert devanagari_to_roman("पैसे चाहिए") == "paise chahie"
    assert devanagari_to_roman("संपर्क ९८") == "sanpark 98"


def test_roman_words_to_devanagari():
    assert transliterate("bank account chahiye") == "बैंक अकाउंट चाहिए"


def test_emoji_swap():
    assert emoji_swap("bank card 🔥", random.Random(0), rate=1.0) == "🏦 💳 💯"


def test_only_suspicious_leaves_other_posts():
    ex = [{"text": "atm card for sale", "ocr_text": "", "label": "card_sale"},
          {"text": "bank holiday tomorrow", "ocr_text": "", "label": "benign"}]
    out, share = attack_examples(ex, lambda t, r: t.upper(), 1, only_suspicious=True)
    assert out[0]["text"] == "ATM CARD FOR SALE" and out[1] == ex[1] and share == 0.5


def test_paraphraser_keeps_original_when_placeholder_lost(tmp_path, monkeypatch):
    p = Paraphraser({"model": "x", "base_url": "http://localhost:1/v1"}, cache_path=str(tmp_path / "c.jsonl"))
    answers = iter(["Kit is ready, ring me", "Kit is ready, ring [PHONE]"])
    calls = []

    def fake_chat(messages, temperature=0.0, max_tokens=64):
        calls.append(messages)
        return next(answers), {}, 0.01
    monkeypatch.setattr(p.client, "chat", fake_chat)
    assert p("Kit ready, call [PHONE]") == "Kit ready, call [PHONE]" and p.failed == 1
    assert p("Kit ready now, call [PHONE]") == "Kit is ready, ring [PHONE]"
    assert p("Kit ready now, call [PHONE]") == "Kit is ready, ring [PHONE]" and len(calls) == 2   # cached
    again = Paraphraser({"model": "x", "base_url": "http://localhost:1/v1"}, cache_path=str(tmp_path / "c.jsonl"))
    assert again("Kit ready now, call [PHONE]") == "Kit is ready, ring [PHONE]"
