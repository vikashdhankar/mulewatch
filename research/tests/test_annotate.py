import math
import xml.dom.minidom

import pytest

from annotate.agreement import agreement, cohen_kappa, span_f1
from annotate.export import make_batches
from annotate.importer import build_gold, parse_export
from annotate.label_config import build
from common.labels import CLASSES, SPAN_LABELS


def test_label_config_has_all_classes_and_spans():
    doc = xml.dom.minidom.parseString(build())
    choices = {c.getAttribute("value") for c in doc.getElementsByTagName("Choice")}
    labels = {lab.getAttribute("value") for lab in doc.getElementsByTagName("Label")}
    assert set(CLASSES) <= choices and len(CLASSES) == 7
    assert labels == set(SPAN_LABELS)


def test_committed_label_config_is_current():
    from pathlib import Path
    assert (Path(__file__).parent.parent / "annotate" / "label_config.xml").read_text() == build()


def test_kappa_known_values():
    sklearn = pytest.importorskip("sklearn.metrics")
    a = ["x", "x", "y", "y", "z", "x", "y", "z", "z", "x"]
    b = ["x", "y", "y", "y", "z", "x", "x", "z", "y", "x"]
    assert math.isclose(cohen_kappa(a, b), sklearn.cohen_kappa_score(a, b))
    assert cohen_kappa(a, a) == 1.0
    assert cohen_kappa(["x"] * 4, ["x"] * 4) == 1.0


def test_kappa_textbook_example():
    # 50 items: both yes 20, a yes/b no 5, a no/b yes 10, both no 15 -> po 0.7, pe 0.5, kappa 0.4
    a = ["y"] * 25 + ["n"] * 25
    b = ["y"] * 20 + ["n"] * 5 + ["y"] * 10 + ["n"] * 15
    assert math.isclose(cohen_kappa(a, b), 0.4)


def test_batches_share_overlap_slice():
    posts = [{"post_id": f"p{i}", "text": "t"} for i in range(100)]
    b = make_batches(posts, ["a1", "a2"], batch_size=40, overlap=0.25)
    assert sorted(b) == [(1, "a1"), (1, "a2"), (2, "a1"), (2, "a2"), (3, "a1"), (3, "a2")]
    ids = {k: {t["data"]["post_id"] for t in v} for k, v in b.items()}
    shared = ids[(1, "a1")] & ids[(1, "a2")]
    assert len(shared) == 10
    assert len(ids[(1, "a1")] | ids[(1, "a2")]) == 40
    assert all(t["data"]["overlap"] == (t["data"]["post_id"] in shared) for t in b[(1, "a1")])


def _ls_task(pid, anns):
    return {"id": hash(pid) % 1000, "data": {"post_id": pid, "overlap": True},
            "annotations": [{"completed_by": who, "result": [
                {"from_name": "label", "to_name": "text", "type": "choices", "value": {"choices": [lab]}},
                *([{"from_name": "spans", "to_name": "text", "type": "labels",
                    "value": {"start": 0, "end": 7, "text": "[PHONE]", "labels": ["contact"]}}] if span else []),
            ]} for who, lab, span in anns]}


def test_import_gold_and_conflicts():
    tasks = [_ls_task("p1", [(1, "card_sale", True), (2, "card_sale", True)]),
             _ls_task("p2", [(1, "benign", False), (2, "awareness", False)]),
             _ls_task("p3", [(1, "mule_account_sale", True)])]
    tasks[2]["annotations"].append({"completed_by": 2, "was_cancelled": True, "result": []})
    rows = parse_export(tasks, {"1": "a1", "2": "a2"})
    assert {r["annotator"] for r in rows} == {"a1", "a2"} and len(rows) == 5
    gold, conflicts = build_gold(rows)
    g = {r["post_id"]: r for r in gold}
    assert g["p1"]["label"] == "card_sale" and g["p1"]["source"] == "agreed"
    assert g["p3"]["source"] == "single"
    assert [c["post_id"] for c in conflicts] == ["p2"]
    gold, conflicts = build_gold(rows, {"p2": "awareness"})
    assert {r["post_id"]: r["label"] for r in gold}["p2"] == "awareness" and not conflicts

    summary, per_class, _ = agreement(rows)
    assert summary[0]["n_items"] == 2 and summary[0]["span_f1"] == 1.0


def test_unknown_class_rejected():
    with pytest.raises(ValueError):
        parse_export([_ls_task("p1", [(1, "not_a_class", False)])])


def test_span_f1():
    s = {"field": "text", "start": 0, "end": 3, "label": "price"}
    assert span_f1([[s]], [[s]]) == 1.0
    assert span_f1([[s]], [[dict(s, end=4)]]) == 0.0
    assert math.isnan(span_f1([[]], [[]]))
