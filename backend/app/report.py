"""Evidence report (PDF) for a flagged post — ready to attach to an NCRP / cyber-cell complaint."""
import io
from datetime import datetime
from html import escape
from xml.sax.saxutils import escape as xesc

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from .config import MEDIA_DIR
from .masking import mask_text
from .pdfkit import has_devanagari, hindi_ready, para_text
from .pdfkit import style as font_style

NAVY = colors.HexColor("#0f1b2d")
RED = colors.HexColor("#c0392b")
LEVEL_COLOR = {"Critical": "#c0392b", "High": "#d35400", "Medium": "#b7950b", "Low": "#27ae60"}


def _pdf_safe(text: str) -> str:
    """Built-in PDF fonts can't draw emoji; drop them (keeps evidence text readable)."""
    return "".join(ch if ord(ch) < 0x2000 or 0x20A0 <= ord(ch) <= 0x20CF or 0x2010 <= ord(ch) <= 0x2027 else " "
                   for ch in (text or ""))


def _highlight(text: str, matches: list[dict]) -> str:
    spans = sorted({(m["start"], m["end"]) for m in matches if m.get("source", "text") == "text"})
    out, pos = [], 0
    for s, e in spans:
        if s < pos:
            continue
        out.append(xesc(text[pos:s]))
        out.append(f'<font backColor="#ffe08a"><b>{xesc(text[s:e])}</b></font>')
        pos = e
    out.append(xesc(text[pos:]))
    return "".join(out).replace("\n", "<br/>")


def build_report(post, related_posts: list, complaint_line: str = "", masked: bool = False) -> bytes:
    """masked: phone and account numbers partly hidden (for viewers below Investigating Officer)."""
    from .workflow import STATUSES
    mt = mask_text if masked else (lambda x: x)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"MuleWatch Case MW-{post.id:05d}", author="MuleWatch")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=NAVY, fontSize=18, alignment=0, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=NAVY, fontSize=12, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("s", parent=body, fontSize=8, textColor=colors.HexColor("#555555"))
    cell = ParagraphStyle("c", parent=body, fontSize=8.5, leading=11)
    hi_body = font_style("hb", True, fontSize=9.5, leading=15) if hindi_ready() else body
    hi_cell = font_style("hc", True, fontSize=8.5, leading=13) if hindi_ready() else cell

    def P(markup, st, raw=""):
        """Use the Devanagari font when the text has Hindi in it."""
        if has_devanagari(raw or markup) and hindi_ready():
            return Paragraph(para_text(markup, True), hi_body if st in (body, small) else hi_cell if st is cell else st)
        return Paragraph(markup, st)

    def table(rows, widths, header=True):
        t = Table([[P(str(c), cell) for c in r] for r in rows], colWidths=widths)
        style = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8ced8")),
                 ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
        if header:
            style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf5"))]
        t.setStyle(TableStyle(style))
        return t

    lvl_col = LEVEL_COLOR.get(post.risk_level, "#333")
    story = [
        Paragraph("MuleWatch — Suspicious Financial Advertisement Evidence Report", h1),
        Paragraph(f"Case ID <b>MW-{post.id:05d}</b> &nbsp;·&nbsp; Generated {datetime.now().strftime('%d %b %Y, %H:%M')} IST",
                  small),
        Spacer(1, 6),
        table([
            ["Risk score", f'<font color="{lvl_col}"><b>{post.risk_score:.0f}/100 — {post.risk_level}</b></font>',
             "Category", escape(post.category)],
            ["Platform", escape(post.platform), "Author / handle", escape(post.author or "—")],
            ["Posted at", post.posted_at.strftime("%d %b %Y %H:%M") if post.posted_at else "—",
             "Captured at", post.ingested_at.strftime("%d %b %Y %H:%M") if post.ingested_at else "—"],
            ["Source URL", escape(post.url or "—"), "Coordinated ring",
             f"{post.cluster_size} linked posts" if post.cluster_size > 1 else "Not linked"],
            ["Investigator verdict", escape(post.label or "Pending review"), "Language", escape(post.language)],
            ["Case status", escape(STATUSES.get(post.status or "NEW", post.status or "")), "FIR number",
             escape(post.fir_number or "—")],
            ["Suggested district", escape((post.jurisdiction or {}).get("district") or "Not identified"),
             "Victim complaints", escape((complaint_line or "No match in imported complaints").replace("₹", "Rs. "))],
        ] + ([["Reappearance", f"Reappeared after takedown of MW-{post.repost_of:05d}", "", ""]] if post.repost_of else []),
            [30 * mm, 60 * mm, 32 * mm, 56 * mm], header=False),
        Paragraph("1. Advertisement content (risk indicators highlighted)", h2),
        P(_highlight(mt(_pdf_safe(post.text)) or "(no text - image post)", post.matches or []), body, post.text),
    ]

    if post.image_path:
        p = MEDIA_DIR / post.image_path
        if p.exists():
            try:
                img = Image(str(p))
                ratio = img.imageHeight / img.imageWidth
                w = min(80 * mm, img.imageWidth, 95 * mm / ratio)
                img.drawWidth, img.drawHeight = w, w * ratio
                story += [Spacer(1, 6), img]
            except Exception:
                pass
        if post.ocr_text:
            story += [P("<b>Text recovered from image (OCR):</b> " + xesc(mt(post.ocr_text[:800])).replace("\n", " "),
                        small, post.ocr_text)]

    story.append(Paragraph("2. Why this was flagged", h2))
    for r in post.reasons or ["No specific indicators."]:
        story.append(P("• " + xesc(mt(_pdf_safe(r))), body))

    s = post.scores or {}
    rows = [["Component", "Score", "Detail"],
            ["Rule engine (keywords + identifiers)", f"{s.get('rule', 0):.0f}", ""],
            ["Multilingual text classifier", f"{s.get('ml', 0):.0f}", ", ".join(s.get("ml_features", [])[:6])],
            ["Image analysis (OCR cues)", f"{s.get('image', 0):.0f}", ", ".join(s.get("image_cues", [])[:6])]]
    if s.get("llm") is not None:
        rows.append(["AI analyst (LLM)", f"{s.get('llm', 0):.0f}", xesc((post.llm or {}).get("rationale", ""))])
    rows.append(["Coordination boost", f"+{s.get('ring_boost', 0):.0f}", f"ring of {post.cluster_size}"])
    if s.get("watchlist"):
        rows.append(["Watchlist match", "floor 88", ", ".join(s["watchlist"])])
    story += [Spacer(1, 4), table(rows, [62 * mm, 18 * mm, 98 * mm])]
    for part in s.get("rule_parts", []):
        pass

    story.append(Paragraph("3. Extracted identifiers", h2))
    ent_rows = [["Type", "Value(s)"]]
    names = {"phone": "Phone", "upi": "UPI ID", "telegram": "Telegram", "whatsapp": "WhatsApp", "url": "URL",
             "email": "E-mail", "ifsc": "IFSC", "card_number": "Card number (masked)", "crypto_wallet": "Crypto wallet",
             "price": "Price quoted", "handle": "Handle", "domains": "Domain", "bank_account": "Bank account number"}
    for k, label in names.items():
        if (post.entities or {}).get(k):
            vals = [mt(str(v)) if k in ("phone", "whatsapp", "bank_account") else str(v) for v in post.entities[k]]
            ent_rows.append([label, xesc(", ".join(vals))])
    if len(ent_rows) == 1:
        ent_rows.append(["—", "No identifiers extracted"])
    story.append(table(ent_rows, [40 * mm, 138 * mm]))

    if related_posts:
        story.append(Paragraph(f"4. Linked / coordinated posts ({len(related_posts)})", h2))
        why = {r["id"]: r["why"] for r in post.related or []}
        rows = [["Case", "Platform", "Score", "Link reason", "Excerpt"]]
        for rp in related_posts[:20]:
            rows.append([f"MW-{rp.id:05d}", escape(rp.platform), f"{rp.risk_score:.0f}",
                         xesc(mt("; ".join(why.get(rp.id, []))[:120])), xesc(mt(_pdf_safe(rp.text or rp.ocr_text or "")[:110]))])
        story.append(table(rows, [20 * mm, 22 * mm, 13 * mm, 50 * mm, 73 * mm]))

    story.append(KeepTogether([
        Paragraph("5. Integrity & chain of custody", h2),
        Paragraph(f"SHA-256 of captured evidence (metadata + text + image bytes):<br/><font name='Courier' size='8'>{post.evidence_hash}</font>", body),
        Paragraph("The hash was computed at capture time. Re-computing it on the stored evidence verifies the record "
                  "has not been altered. This report is machine-generated decision support; findings must be verified by an "
                  "investigating officer before action. Report cyber financial fraud at <b>cybercrime.gov.in</b> or helpline <b>1930</b>.",
                  small),
    ]))

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(16 * mm, 8 * mm, f"MuleWatch · Case MW-{post.id:05d} · Confidential — for law-enforcement use")
        canvas.drawRightString(A4[0] - 16 * mm, 8 * mm, f"Page {d.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
