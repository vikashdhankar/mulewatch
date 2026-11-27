"""collect.apply_review: only Y rows change the channels file, with the label of their suggestion."""
import openpyxl
import yaml

from collect import apply_review as ar


def sheet(path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Review"
    ws.append(["suggestion", "approved (Y/N)", "reason", "username", "title"])
    for r in rows:
        ws.append(r)
    wb.create_sheet("How to review").append(["Step", "What to do"])
    wb.save(path)


def channels(path, names):
    doc = {"generated": "2026-11-26", "channels": [
        {"username": n, "approved": False, "label": "unclear", "category": "usdt_p2p", "rajasthan_focus": i == 0,
         "top_district": "jaipur" if i == 0 else None} for i, n in enumerate(names)],
        "settings": {"requests_per_minute": 20}}
    path.write_text(yaml.safe_dump(doc, sort_keys=False))


def test_only_y_rows_are_applied(tmp_path, capsys):
    x, ch = tmp_path / "review.xlsx", tmp_path / "channels.discovered.yaml"
    names = ["fraud_one", "legit_one", "no_mark", "said_no", "still_review", "Upper_Case", "gone"]
    channels(ch, names[:-1] + ["approved_before"])
    doc = yaml.safe_load(ch.read_text())
    doc["channels"][-1].update(approved=True, label="likely_fraud")            # approved earlier, no Y now
    ch.write_text(yaml.safe_dump(doc, sort_keys=False))
    sheet(x, [["approve_fraud", "Y", "", "fraud_one"], ["approve_legit", " y ", "", "@legit_one"],
              ["approve_fraud", None, "", "no_mark"], ["approve_fraud", "N", "", "said_no"],
              ["review", "Y", "", "still_review"], ["approve_fraud", "Y", "", "upper_case"],
              ["approve_fraud", "Y", "", "gone"], ["approve_fraud", "N", "", "approved_before"]])
    ar.main(["--xlsx", str(x), "--channels", str(ch)])
    by = {e["username"]: e for e in yaml.safe_load(ch.read_text())["channels"]}
    assert by["fraud_one"]["approved"] is True and by["fraud_one"]["label"] == "likely_fraud"
    assert by["legit_one"]["approved"] is True and by["legit_one"]["label"] == "likely_legit"
    assert by["Upper_Case"]["approved"] is True
    assert by["fraud_one"]["review"] == {"source": "review.xlsx", "row": 2, "suggestion": "approve_fraud",
                                         "applied": by["fraud_one"]["review"]["applied"]}
    for n in ("no_mark", "said_no", "still_review"):                        # untouched
        assert by[n]["approved"] is False and by[n]["label"] == "unclear" and "review" not in by[n]
    assert by["approved_before"]["approved"] is True                       # N does not un-approve
    assert yaml.safe_load(ch.read_text())["settings"] == {"requests_per_minute": 20}
    out = capsys.readouterr().out
    assert "collection set: 3 likely_fraud : 1 likely_legit (ratio 3.0:1)" in out


def test_counts_and_dry_run(tmp_path):
    x, ch = tmp_path / "review.xlsx", tmp_path / "c.yaml"
    channels(ch, ["a_chan", "b_chan"])
    sheet(x, [["approve_fraud", "Y", "", "a_chan"], ["reject", "Y", "", "b_chan"], ["approve_fraud", "Y", "", "zz_x"]])
    before = ch.read_text()
    ar.main(["--xlsx", str(x), "--channels", str(ch), "--dry-run"])
    assert ch.read_text() == before
    doc = yaml.safe_load(before)
    n = ar.apply(doc, ar.read_review(x), "review.xlsx")
    assert n["marked_y"] == 3 and n["approved_now"] == 1 and n["skipped_suggestion_reject"] == 1
    assert n["skipped_not_in_channels_file"] == 1
    assert ar.apply(doc, ar.read_review(x), "review.xlsx")["already_approved"] == 1
