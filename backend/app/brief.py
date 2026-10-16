"""Daily brief for senior officers: one page, English or Hindi, PDF.

Generated on demand from the command center, and every morning at DAILY_BRIEF_TIME (IST) it is sent through
the Telegram bot to every supervisor who has linked Telegram (/officer <code>)."""
import io
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from . import audit, workflow
from .config import LEVEL_RANK
from .coordination import entity_keys
from .db import Post, SessionLocal, User, get_setting, set_setting
from .pdfkit import hindi_ready, para_text, safe, style

BRIEF_TIME = os.getenv("DAILY_BRIEF_TIME", "09:00")
BRIEF_LANG = os.getenv("DAILY_BRIEF_LANG", "en")
BRIEF_ON = os.getenv("DAILY_BRIEF_TELEGRAM", "1") != "0"

T = {
    "en": {
        "title": "MuleWatch daily brief", "period": "Period", "to": "to",
        "k_new": "New cases", "k_flag": "High / Critical", "k_crit": "Critical", "k_comp": "Linked to complaints",
        "k_rings": "Active rings", "k_sent": "Notices sent", "k_removed": "Content removed", "k_overdue": "Overdue takedowns",
        "k_back": "Reappeared after takedown",
        "platforms": "Platform response to takedown notices (all open and closed notices)",
        "p_platform": "Platform", "p_sent": "Notices", "p_removed": "Removed", "p_avg": "Avg. time to removal",
        "p_within": "Within window", "p_pending": "Pending",
        "priority": "Top open cases by recruiter priority", "c_case": "Case", "c_score": "Priority",
        "c_cat": "Category", "c_dist": "District", "c_status": "Status", "c_officer": "Officer",
        "ids": "Identifiers seen most in flagged posts", "i_id": "Identifier", "i_n": "Posts",
        "districts": "Cases by suggested district (High / Critical)", "d_dist": "District", "d_n": "Cases",
        "none": "None", "unassigned": "Unassigned", "unknown": "Not identified",
        "foot": "Machine-generated decision support. Findings must be verified by an investigating officer.",
        "rupees": "Amount in linked complaints",
    },
    "hi": {
        "title": "MuleWatch दैनिक सारांश", "period": "अवधि", "to": "से",
        "k_new": "नए प्रकरण", "k_flag": "उच्च / गंभीर", "k_crit": "गंभीर", "k_comp": "शिकायतों से जुड़े",
        "k_rings": "सक्रिय गिरोह", "k_sent": "भेजी गई सूचनाएँ", "k_removed": "हटाई गई सामग्री", "k_overdue": "समय-सीमा पार",
        "k_back": "हटाने के बाद फिर दिखे",
        "platforms": "टेकडाउन सूचनाओं पर प्लेटफ़ॉर्म की प्रतिक्रिया (सभी सूचनाएँ)",
        "p_platform": "प्लेटफ़ॉर्म", "p_sent": "सूचनाएँ", "p_removed": "हटाई गईं", "p_avg": "हटाने में औसत समय",
        "p_within": "समय-सीमा में", "p_pending": "लंबित",
        "priority": "भर्तीकर्ता प्राथमिकता के अनुसार शीर्ष खुले प्रकरण", "c_case": "प्रकरण", "c_score": "प्राथमिकता",
        "c_cat": "श्रेणी", "c_dist": "ज़िला", "c_status": "स्थिति", "c_officer": "अधिकारी",
        "ids": "संदिग्ध पोस्ट में सबसे अधिक दिखे पहचान विवरण", "i_id": "पहचान विवरण", "i_n": "पोस्ट",
        "districts": "संभावित ज़िले अनुसार प्रकरण (उच्च / गंभीर)", "d_dist": "ज़िला", "d_n": "प्रकरण",
        "none": "कोई नहीं", "unassigned": "आवंटित नहीं", "unknown": "पहचान नहीं",
        "foot": "मशीन द्वारा तैयार निर्णय-सहायक सारांश। निष्कर्षों का सत्यापन अन्वेषण अधिकारी द्वारा आवश्यक है।",
        "rupees": "जुड़ी शिकायतों में राशि",
    },
}
STATUS_HI = {"NEW": "नया", "VERIFIED": "सत्यापित", "NOTICE_DRAFTED": "सूचना प्रारूप", "NOTICE_SENT": "सूचना भेजी",
             "CONTENT_REMOVED": "सामग्री हटी", "FIR_LINKED": "एफ.आई.आर. से जुड़ा", "CLOSED_NO_ACTION": "बंद"}


def _ist(dt):
    return dt + timedelta(hours=5, minutes=30)


def collect(session, start: datetime, end: datetime, district: str | None = None) -> dict:
    posts = session.query(Post).filter(Post.source != "preview").all()
    if district:              # one district's brief: cases whose suggested district is this one
        posts = [p for p in posts if (p.jurisdiction or {}).get("district") == district]
    period = [p for p in posts if p.ingested_at and start <= p.ingested_at < end]
    flagged = [p for p in period if LEVEL_RANK.get(p.risk_level, 0) >= 2]
    rings = {p.cluster_id for p in period if p.cluster_id is not None and LEVEL_RANK.get(p.risk_level, 0) >= 2}
    now = datetime.utcnow()
    plat = defaultdict(lambda: {"sent": 0, "removed": 0, "within": 0, "minutes": [], "pending": 0})
    for p in posts:
        if not p.notice_sent_at:
            continue
        k = plat[(p.platform or "").split(" · ")[0]]
        k["sent"] += 1
        c = workflow.clock(p, now)
        if p.removed_at:
            k["removed"] += 1
            k["minutes"].append(c["took_minutes"])
            k["within"] += c["state"] == "met"
        else:
            k["pending"] += 1
    ids = Counter(k for p in flagged for k in entity_keys(p.entities or {}))
    dists = Counter((p.jurisdiction or {}).get("district") or "" for p in flagged)
    users = {u.id: u.name for u in session.query(User).all()}
    open_cases = sorted((p for p in posts if (p.status or "NEW") in workflow.OPEN and LEVEL_RANK.get(p.risk_level, 0) >= 2),
                        key=workflow.priority_key)[:6]
    return {
        "start": start, "end": end,
        "kpi": {"k_new": len(period), "k_flag": len(flagged), "k_crit": sum(p.risk_level == "Critical" for p in period),
                "k_comp": sum(1 for p in period if p.complaint_count),
                "k_rings": len(rings),
                "k_sent": sum(1 for p in posts if p.notice_sent_at and start <= p.notice_sent_at < end),
                "k_removed": sum(1 for p in posts if p.removed_at and start <= p.removed_at < end),
                "k_overdue": sum(1 for p in posts if p.status == "NOTICE_SENT" and workflow.clock(p, now)["state"] == "overdue"),
                "k_back": sum(1 for p in period if p.repost_of)},
        "complaint_amount": sum(p.complaint_amount or 0 for p in period),
        "platforms": [{"platform": k, **v, "avg": round(sum(v["minutes"]) / len(v["minutes"])) if v["minutes"] else None}
                      for k, v in sorted(plat.items(), key=lambda kv: -kv[1]["sent"])],
        "identifiers": ids.most_common(8),
        "districts": sorted(dists.items(), key=lambda kv: (kv[0] == "", -kv[1]))[:10],
        "priority": [{"case": f"MW-{p.id:05d}", "score": p.recruiter_score or 0, "category": p.category,
                      "district": (p.jurisdiction or {}).get("district", ""), "status": p.status or "NEW",
                      "officer": users.get(p.assigned_to, "")} for p in open_cases],
    }


def _mins(m) -> str:
    if m is None:
        return "—"
    return f"{m} min" if m < 120 else f"{m / 60:.1f} h"


def build_pdf(session, lang: str = "en", end: datetime | None = None, hours: int = 24,
              district: str | None = None) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    lang = "hi" if lang == "hi" and hindi_ready() else "en"
    L, hi = T[lang], lang == "hi"
    end = end or datetime.utcnow()
    d = collect(session, end - timedelta(hours=hours), end, district)
    s_title = style("t", hi, fontSize=15, leading=20, bold=True, textColor=colors.HexColor("#14213d"))
    s_sub = style("s", hi, fontSize=9, leading=13, textColor=colors.HexColor("#555555"))
    s_h = style("h", hi, fontSize=10.5, leading=15, bold=True, spaceBefore=7, spaceAfter=3, textColor=colors.HexColor("#14213d"))
    s_c = style("c", hi, fontSize=8.5, leading=12)
    s_cb = style("cb", hi, fontSize=8.5, leading=12, bold=True)
    s_k = style("k", hi, fontSize=8, leading=11, textColor=colors.HexColor("#555555"))
    s_kn = style("kn", False, fontSize=17, leading=20, fontName="Helvetica-Bold")

    def P(text, st):
        from html import escape
        return Paragraph(para_text(escape(safe(str(text)), quote=False), hi, st.fontName.endswith("Bold")), st)

    def table(rows, widths, header=True):
        t = Table([[P(c, s_cb if header and i == 0 else s_c) for c in r] for i, r in enumerate(rows)], colWidths=widths)
        ts = [("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#d5dae3")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
              ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
        if header:
            ts.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f6")))
        t.setStyle(TableStyle(ts))
        return t

    a, b = _ist(d["start"]), _ist(d["end"])
    title = L["title"]
    if district:
        from .jurisdiction import DISTRICTS
        title += f" — {DISTRICTS[district]['hi'] if hi and district in DISTRICTS else district}"
    story = [P(title, s_title),
             P(f"{L['period']}: {a.strftime('%d %b %Y %H:%M')} {L['to']} {b.strftime('%d %b %Y %H:%M')} IST"
               + (" तक" if hi else ""), s_sub),
             Spacer(1, 6)]
    keys = list(d["kpi"])
    cells = [[Paragraph(str(d["kpi"][k]), s_kn) for k in keys[i:i + 5]] for i in range(0, len(keys), 5)]
    labels = [[P(L[k], s_k) for k in keys[i:i + 5]] for i in range(0, len(keys), 5)]
    W = A4[0] - 32 * mm
    grid = []
    for r1, r2 in zip(cells, labels):
        grid += [r1 + [""] * (5 - len(r1)), r2 + [""] * (5 - len(r2))]
    kt = Table(grid, colWidths=[W / 5] * 5)
    kt.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#d5dae3")),
                            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7f8fb")),
                            ("TEXTCOLOR", (2, 0), (2, 0), colors.HexColor("#c0392b"))]))
    story.append(kt)
    if d["complaint_amount"]:
        from .complaints import inr
        amt = f"{'₹' if hi else 'Rs. '}{inr(d['complaint_amount'])}"
        story.append(P(f"{L['rupees']}: {amt}", s_sub))

    story.append(P(L["priority"], s_h))
    rows = [[L["c_case"], L["c_score"], L["c_cat"], L["c_dist"], L["c_status"], L["c_officer"]]]
    for c in d["priority"]:
        rows.append([c["case"], f"{c['score']:.0f}", c["category"], c["district"] or L["unknown"],
                     STATUS_HI.get(c["status"], c["status"]) if hi else workflow.STATUSES.get(c["status"], c["status"]),
                     c["officer"] or L["unassigned"]])
    story.append(table(rows, [22 * mm, 18 * mm, 46 * mm, 30 * mm, 30 * mm, W - 146 * mm]) if len(rows) > 1 else P(L["none"], s_c))

    story.append(P(L["platforms"], s_h))
    rows = [[L["p_platform"], L["p_sent"], L["p_removed"], L["p_avg"], L["p_within"], L["p_pending"]]]
    for p in d["platforms"]:
        rows.append([p["platform"], p["sent"], p["removed"], _mins(p["avg"]),
                     f"{p['within']}/{p['removed']}" if p["removed"] else "—", p["pending"]])
    story.append(table(rows, [52 * mm, 20 * mm, 22 * mm, 34 * mm, 26 * mm, W - 154 * mm]) if len(rows) > 1 else P(L["none"], s_c))

    half = (W - 8 * mm) / 2
    ids = [[L["i_id"], L["i_n"]]] + [[k.split(":", 1)[1], n] for k, n in d["identifiers"]]
    ds = [[L["d_dist"], L["d_n"]]] + [[k or L["unknown"], n] for k, n in d["districts"]]
    side = Table([[P(L["ids"], s_h), P(L["districts"], s_h)],
                  [table(ids, [half - 16 * mm, 16 * mm]) if len(ids) > 1 else P(L["none"], s_c),
                   table(ds, [half - 16 * mm, 16 * mm]) if len(ds) > 1 else P(L["none"], s_c)]],
                 colWidths=[half + 4 * mm, half + 4 * mm])
    side.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [side, Spacer(1, 8), P(L["foot"], s_sub)]

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=13 * mm,
                      bottomMargin=12 * mm, title=L["title"], author="MuleWatch").build(story)
    return buf.getvalue()


def send(lang: str = BRIEF_LANG, actor=None) -> dict:
    """Send the brief to every supervisor with Telegram linked (or the alert chat if none is linked)."""
    from .alerts import alert_chat_id, alert_token, officer_chats, send_document
    if not alert_token():
        return {"ok": False, "sent": 0, "message": "No Telegram bot configured (TELEGRAM_BOT_TOKEN in .env)"}
    with SessionLocal() as s:
        chats = officer_chats(s, roles=("SUPERVISOR",)) or ([alert_chat_id()] if alert_chat_id() else [])
        if not chats:
            return {"ok": False, "sent": 0, "message": "No supervisor has linked Telegram yet (Officers page)"}
        pdf = build_pdf(s, lang)
    day = _ist(datetime.utcnow()).strftime("%d %b %Y")
    name = f"MuleWatch-brief-{_ist(datetime.utcnow()).strftime('%Y-%m-%d')}-{lang}.pdf"
    ok = sum(send_document(c, name, pdf, f"MuleWatch daily brief — {day}") for c in chats)
    audit.log(actor, "brief.sent", detail={"chats": len(chats), "delivered": ok, "lang": lang})
    return {"ok": ok == len(chats), "sent": ok, "message": f"Sent to {ok} of {len(chats)} chat(s)"}


def maybe_send_scheduled():
    if not BRIEF_ON:
        return
    now = _ist(datetime.utcnow())
    try:
        hh, mm_ = (int(x) for x in BRIEF_TIME.split(":"))
    except ValueError:
        return
    today = now.strftime("%Y-%m-%d")
    if (now.hour, now.minute) < (hh, mm_) or get_setting("brief_last_sent") == today:
        return
    set_setting("brief_last_sent", today)          # once a day, even if delivery fails
    send(BRIEF_LANG)
