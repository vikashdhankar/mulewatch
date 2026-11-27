"""Write result tables as CSV plus a booktabs LaTeX table, side by side in research/results/."""
import csv
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

_LATEX_ESCAPES = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
                  "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def latex_escape(value) -> str:
    return "".join(_LATEX_ESCAPES.get(ch, ch) for ch in str(value))


def _fmt(value, digits: int) -> str:
    if value is None or value == "" or (isinstance(value, float) and value != value):
        return "--"
    if isinstance(value, float):
        if value and abs(value) < 10 ** -digits:          # tiny costs: keep 2 significant digits
            return f"{value:.2g}"
        return f"{value:.{digits}f}"
    return str(value)


def _numeric(rows, col) -> bool:
    vals = [r.get(col) for r in rows if r.get(col) not in (None, "")]
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals)   # empty -> numeric


def to_latex(rows: list[dict], columns: list[str], caption: str = "", label: str = "",
             digits: int = 3, bold_max: list[str] | None = None, col_digits: dict | None = None) -> str:
    """booktabs table; columns in bold_max get their best (highest) value in bold."""
    best = {}
    for col in bold_max or []:
        vals = [r.get(col) for r in rows if isinstance(r.get(col), (int, float))]
        if vals:
            best[col] = max(vals)
    col_digits = col_digits or {}
    align = "".join("r" if _numeric(rows, c) else "l" for c in columns)
    lines = [r"\begin{table}[t]", r"\centering", r"\small", rf"\begin{{tabular}}{{{align}}}", r"\toprule",
             " & ".join(latex_escape(c) for c in columns) + r" \\", r"\midrule"]
    for r in rows:
        cells = []
        for c in columns:
            cell = latex_escape(_fmt(r.get(c), col_digits.get(c, digits)))
            if c in best and r.get(c) == best[c]:
                cell = rf"\textbf{{{cell}}}"
            cells.append(cell)
        lines.append(" & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    if caption:
        lines.append(rf"\caption{{{latex_escape(caption)}}}")
    if label:
        lines.append(rf"\label{{{label}}}")
    lines.append(r"\end{table}")
    return "\n".join(lines) + "\n"


def write_table(name: str, rows: list[dict], columns: list[str] | None = None, caption: str = "",
                results_dir=None, digits: int = 3, bold_max: list[str] | None = None,
                col_digits: dict | None = None) -> tuple[Path, Path]:
    out = Path(results_dir or RESULTS_DIR)
    out.mkdir(parents=True, exist_ok=True)
    columns = columns or (list(rows[0].keys()) if rows else [])
    csv_path, tex_path = out / f"{name}.csv", out / f"{name}.tex"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: (round(r[c], 6) if isinstance(r.get(c), float) else r.get(c)) for c in columns})
    tex_path.write_text(to_latex(rows, columns, caption=caption, label=f"tab:{name}", digits=digits,
                                 bold_max=bold_max, col_digits=col_digits), encoding="utf-8")
    return csv_path, tex_path
