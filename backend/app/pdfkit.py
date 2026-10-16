"""Shared PDF helpers: Devanagari font with proper shaping, and mixed Hindi/English text.

The bundled Noto Sans Devanagari (SIL Open Font License, see fonts/OFL.txt) has no Latin letters, so Latin runs
inside Hindi text are switched to the bundled Noto Sans. Both are TrueType, which the shaper needs: uharfbuzz does
the Devanagari shaping (conjuncts, matras) word by word, and a word may mix the two scripts."""
import re
from pathlib import Path

from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT_DIR = Path(__file__).parent / "fonts"
_done = {"ok": None}


def hindi_ready() -> bool:
    if _done["ok"] is None:
        try:
            import uharfbuzz  # noqa: F401
            pdfmetrics.registerFont(TTFont("Deva", str(FONT_DIR / "NotoSansDevanagari-Regular.ttf")))
            pdfmetrics.registerFont(TTFont("Deva-Bold", str(FONT_DIR / "NotoSansDevanagari-Bold.ttf")))
            pdfmetrics.registerFontFamily("Deva", normal="Deva", bold="Deva-Bold", italic="Deva", boldItalic="Deva-Bold")
            pdfmetrics.registerFont(TTFont("NotoLatin", str(FONT_DIR / "NotoSans-Regular.ttf")))
            pdfmetrics.registerFont(TTFont("NotoLatin-Bold", str(FONT_DIR / "NotoSans-Bold.ttf")))
            _done["ok"] = True
        except Exception:
            _done["ok"] = False
    return _done["ok"]


def has_devanagari(s: str) -> bool:
    return any("ऀ" <= c <= "ॿ" for c in s or "")


def _deva_chars() -> set:
    if "deva" not in _done:
        from reportlab.pdfbase.ttfonts import TTFontFile
        _done["deva"] = (set(TTFontFile(str(FONT_DIR / "NotoSansDevanagari-Regular.ttf")).charToGlyph)
                         & set(TTFontFile(str(FONT_DIR / "NotoSansDevanagari-Bold.ttf")).charToGlyph))
    return _done["deva"]


def mixed(markup: str, bold_base: bool = False) -> str:
    """Put every run of characters the Devanagari font can't draw (Latin letters, curly quotes, dashes, ₹ ...)
    in Noto Sans (bold inside <b> or in a bold style). Only text outside tags is touched; &entities; stay whole."""
    deva = _deva_chars()
    out, bold = [], int(bold_base)
    for part in re.split(r"(<[^>]+>)", markup):
        if part.startswith("<"):
            t = part.lower()
            if t.startswith("<b>") or t.startswith("<b "):
                bold += 1
            elif t.startswith("</b"):
                bold = max(0, bold - 1)
            out.append(part)
            continue
        face = "NotoLatin-Bold" if bold else "NotoLatin"
        for tok in re.split(r"(&[#a-zA-Z0-9]+;|\s+)", part):
            if not tok:
                continue
            if tok.isspace() or (tok.startswith("&") and tok.endswith(";")):
                out.append(tok)
                continue
            # a word with no Devanagari in it goes wholly into the Latin font: the shaper can't handle a
            # bold word whose letters come from two fonts, e.g. "79(3)(b)"
            if not any("\u0900" <= ch <= "\u097f" for ch in tok):
                if any((ch.isascii() and ch.isalpha()) or ord(ch) not in deva for ch in tok):
                    out.append(f'<font name="{face}">{tok}</font>')
                else:
                    out.append(tok)
                continue
            run, latin = "", None
            for ch in tok:
                is_lat = (ch.isascii() and ch.isalpha()) or ord(ch) not in deva
                if latin is not None and is_lat != latin:
                    out.append(f'<font name="{face}">{run}</font>' if latin else run)
                    run = ""
                run += ch
                latin = is_lat
            if run:
                out.append(f'<font name="{face}">{run}</font>' if latin else run)
    return "".join(out)


def style(name: str, hindi: bool, **kw) -> ParagraphStyle:
    if hindi and hindi_ready():
        kw.setdefault("fontName", "Deva-Bold" if kw.pop("bold", False) else "Deva")
        kw["shaping"] = 1
        kw.setdefault("bulletFontName", "NotoLatin")     # "•" is not in the Devanagari font
        kw.setdefault("leading", kw.get("fontSize", 10) * 1.55)
    else:
        kw.setdefault("fontName", "Helvetica-Bold" if kw.pop("bold", False) else "Helvetica")
        kw.pop("bold", None)
    return ParagraphStyle(name, **kw)


def para_text(markup: str, hindi: bool, bold: bool = False) -> str:
    return mixed(markup, bold) if hindi and hindi_ready() else markup


def safe(text: str) -> str:
    """Drop characters the PDF fonts can't draw (emoji), keep Devanagari, ₹ and punctuation."""
    return "".join(ch if ord(ch) < 0x2000 or 0x0900 <= ord(ch) <= 0x097F or 0x20A0 <= ord(ch) <= 0x20CF
                   or 0x2010 <= ord(ch) <= 0x2027 or ch in "₹✓☐☑" else " " for ch in (text or ""))
