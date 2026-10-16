"""Analysts see phone and account numbers partly hidden; Investigating Officers and supervisors see them in
full. Masking keeps every string the same length so highlight positions in the text still line up."""
import re

_NUM = re.compile(r"(?<![\w@])\+?\d(?:[\s\-.]?\d){8,17}(?![\w@])")
MASK_KINDS = ("phone", "whatsapp", "bank_account", "phone_like")


def _mask_run(s: str) -> str:
    digits = [i for i, c in enumerate(s) if c.isdigit()]
    if len(digits) < 9:
        return s
    keep = set(digits[:2] + digits[-2:])
    if s.startswith("+91") and len(digits) >= 12:
        keep |= set(digits[:4])                     # +91 and the first two digits of the number
    return "".join("•" if (i in digits and i not in keep) else c for i, c in enumerate(s))


def mask_text(s: str | None) -> str | None:
    if not s:
        return s
    return _NUM.sub(lambda m: _mask_run(m.group(0)), s)


def mask_value(v):
    return _mask_run(v) if isinstance(v, str) else v


def apply(d: dict, viewer) -> dict:
    """Mask a serialised post (summary or detail) for viewers below Investigating Officer."""
    from .auth import can
    if d is None or viewer is None or can(viewer, "IO"):
        return d
    d = dict(d)
    for k in ("text", "ocr_text", "excerpt", "top_reason"):
        if isinstance(d.get(k), str):
            d[k] = mask_text(d[k])
    if isinstance(d.get("entities"), dict):
        d["entities"] = {k: ([mask_value(x) for x in v] if k in MASK_KINDS and isinstance(v, list) else v)
                         for k, v in d["entities"].items()}
        d["masked"] = True
    if isinstance(d.get("reasons"), list):
        d["reasons"] = [mask_text(r) for r in d["reasons"]]
    if isinstance(d.get("related"), list):
        d["related"] = [apply(r, viewer) for r in d["related"]]
    return d
