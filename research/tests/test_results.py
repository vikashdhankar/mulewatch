from common.results import to_latex, write_table


def test_latex_escapes_aligns_and_bolds(tmp_path):
    rows = [{"model": "tfidf_lr", "f1": 0.5, "cost": 0.00001}, {"model": "x&y", "f1": 0.75, "cost": None}]
    tex = to_latex(rows, ["model", "f1", "cost"], caption="50% done", bold_max=["f1"])
    assert r"\begin{tabular}{lrr}" in tex
    assert r"tfidf\_lr" in tex and r"x\&y" in tex and r"50\% done" in tex
    assert r"\textbf{0.750}" in tex and "1e-05" in tex and "--" in tex
    csv_path, tex_path = write_table("t", rows, results_dir=tmp_path)
    assert csv_path.read_text().splitlines()[0] == "model,f1,cost"
    assert tex_path.exists()
