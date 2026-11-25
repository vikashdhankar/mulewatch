import json
import math

import pytest

from common.labels import CLASSES
from models.metrics import cost_per_1k, macro_f1, per_language_f1, score, suspicious_f1, timed_predict


def test_macro_f1_ignores_absent_classes():
    y = ["card_sale", "benign", "benign"]
    assert macro_f1(y, y) == 1.0
    assert math.isclose(macro_f1(["card_sale", "benign"], ["benign", "benign"]), (0 + 2 / 3) / 2)


def test_per_language_and_suspicious():
    y = ["card_sale", "benign", "awareness", "mule_account_sale"]
    p = ["card_sale", "benign", "mule_account_sale", "mule_account_sale"]
    pl = per_language_f1(y, p, ["en", "en", "hi", "hi"])
    assert pl["en"] == {"n": 2, "macro_f1": 1.0}
    assert pl["hi"]["n"] == 2 and pl["hi"]["macro_f1"] < 1
    assert math.isclose(suspicious_f1(y, p), 0.8)
    s = score(y, p, ["en"] * 4)
    assert set(s["per_class_f1"]) == set(CLASSES) and s["per_class_f1"]["kyc_fraud"] is None


def test_cost():
    c = cost_per_1k({"ms_per_post": 36.0}, 100, {"usd_per_hour": 1.0},
                    {"prompt_tokens": 200_000, "completion_tokens": 1000})
    assert math.isclose(c["compute_usd_per_1k"], 0.01)          # 36 s per 1k posts at $1/h
    assert c["api_usd_per_1k"] == 0.0
    c = cost_per_1k({"ms_per_post": 0.0}, 1000, {"usd_per_1m_input_tokens": 1.0, "usd_per_1m_output_tokens": 2.0},
                    {"prompt_tokens": 1_000_000, "completion_tokens": 500_000})
    assert math.isclose(c["usd_per_1k"], 2.0)


def test_tfidf_learns_toy_task():
    from models.tfidf_lr import TfidfLR
    texts = ["current account kit for sale [PHONE]", "atm card available buy now", "beware of mule accounts",
             "nice weather today in jaipur"] * 10
    labels = ["mule_account_sale", "card_sale", "awareness", "benign"] * 10
    m = TfidfLR({"min_df": 1}).fit(texts, labels)
    preds, timing = timed_predict(m, ["kit for sale current account", "atm card buy"])
    assert preds == ["mule_account_sale", "card_sale"]
    assert timing["ms_per_post"] >= 0 and timing["single_p50_ms"] is not None


def test_llm_parse_label():
    from models.llm_prompt import parse_label
    assert parse_label('{"label": "card_sale"}') == "card_sale"
    assert parse_label('Sure! {"label":"Awareness"}') == "awareness"
    assert parse_label("The answer is kyc_fraud.") == "kyc_fraud"
    assert parse_label("benign or awareness") is None
    assert parse_label("") is None


def test_llm_refuses_remote_endpoint():
    from common.llm_client import LLMClient
    with pytest.raises(PermissionError):
        LLMClient("m", base_url="https://api.example.com/v1")
    LLMClient("m", base_url="https://api.example.com/v1", allow_remote=True)
    LLMClient("m", base_url="http://localhost:8000/v1")


def test_llm_fewshot_classifier_with_fake_server(monkeypatch):
    from models.llm_prompt import LLMClassifier

    seen = []

    class FakeResp:
        status_code = 200

        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self.body

    def fake_post(self, url, json=None, timeout=None):
        seen.append(json)
        last = json["messages"][-1]["content"]
        label = "card_sale" if "card" in last else "nonsense"
        return FakeResp({"choices": [{"message": {"content": '{"label": "%s"}' % label}}],
                         "usage": {"prompt_tokens": 100, "completion_tokens": 5}})

    import requests
    monkeypatch.setattr(requests.Session, "post", fake_post)
    m = LLMClassifier({"model": "x", "base_url": "http://localhost:1/v1", "shots_per_class": 1, "workers": 2})
    m.fit(["atm card for sale, dm", "be careful of fake account sellers"], ["card_sale", "awareness"])
    assert len(m.shots) == 2
    assert m.predict(["card here", "something else"]) == ["card_sale", "benign"]
    assert m.invalid == 1 and m.usage == {"prompt_tokens": 200, "completion_tokens": 10}
    assert len(seen[0]["messages"]) == 1 + 2 * 2 + 1          # system + 2 shots + post
    assert json.loads(seen[0]["messages"][2]["content"])["label"] in CLASSES


def test_configs_load():
    from pathlib import Path

    from models.registry import load_config
    names = set()
    for p in sorted(Path(__file__).parent.parent.glob("models/configs/*.yaml")):
        cfg = load_config(p)
        assert cfg["type"] in ("tfidf_lr", "hf", "llm")
        names.add(cfg["name"])
    assert names == {"tfidf_lr", "muril", "indicbert", "xlmr", "llm_zeroshot", "llm_fewshot"}
