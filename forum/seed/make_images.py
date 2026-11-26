"""Generate the synthetic images used by the seeded forum posts (scam posters, card/passbook
photos, and normal community images). All bank names / numbers are fictional."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).parent / "images"
OUT.mkdir(exist_ok=True)
FONT_DIRS = ["/usr/share/fonts/truetype/dejavu/", "C:/Windows/Fonts/", "/Library/Fonts/"]


def font(size, bold=True):
    for d in FONT_DIRS:
        for n in (["DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"] if bold else ["DejaVuSans.ttf", "arial.ttf", "Arial.ttf"]):
            p = Path(d) / n
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def center(d, y, text, f, fill, W):
    w = d.textlength(text, font=f)
    d.text(((W - w) / 2, y), text, font=f, fill=fill)


def poster(name, lines, bg, fg, accent, size=(900, 1100), stripe=True):
    W, H = size
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    if stripe:
        for i in range(-H, W, 60):
            d.line([(i, 0), (i + H, H)], fill=tuple(max(0, c - 18) for c in bg), width=22)
    y = 70
    for text, sz, col in lines:
        f = font(sz)
        col = {"fg": fg, "accent": accent}.get(col, col)
        center(d, y, text, f, col, W)
        y += int(sz * 1.35)
    im.save(OUT / name)
    return im


def card(name, overlay=None, alt=False):
    W, H = 900, 640
    bg = (58, 64, 72) if alt else (236, 232, 225)
    im = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(im)
    if alt:   # wooden desk look for the personal photo
        for y in range(0, H, 14):
            d.line([(0, y), (W, y + 30)], fill=(150, 98, 52) if (y // 14) % 2 else (138, 88, 46), width=14)
    # card body
    cx, cy, cw, ch = (150, 150, 640, 400) if alt else (110, 90, 680, 420)
    body = (150, 28, 48) if alt else (22, 52, 96)
    d.rounded_rectangle([cx + 8, cy + 10, cx + cw + 8, cy + ch + 10], 28, fill=(60, 40, 30) if alt else (190, 182, 170))
    d.rounded_rectangle([cx, cy, cx + cw, cy + ch], 28, fill=body)
    for i in range(0, cw, 6):
        d.line([(cx + i, cy), (cx + i + 200, cy + ch)], fill=tuple(min(255, c + 6) for c in body), width=2)
    d.rounded_rectangle([cx, cy, cx + cw, cy + ch], 28, outline=(80, 120, 170), width=3)
    d.text((cx + 40, cy + 34), "NAGAR SAHAKARI BANK", font=font(30), fill="white")
    d.text((cx + cw - 190, cy + 38), "PLATINUM", font=font(24), fill=(230, 200, 120))
    d.rounded_rectangle([cx + 50, cy + 120, cx + 140, cy + 190], 10, fill=(212, 175, 95))
    d.text((cx + 50, cy + 230), "4718  XXXX  XXXX  2041", font=font(42), fill="white")
    d.text((cx + 50, cy + 300), "VALID THRU  08/29", font=font(22, False), fill=(220, 225, 235))
    d.text((cx + 50, cy + 340), "DEBIT", font=font(26), fill="white")
    d.text((cx + cw - 170, cy + 340), "RuPay", font=font(34), fill=(240, 240, 240))
    if overlay:
        d.rectangle([0, H - 96, W, H], fill=(200, 20, 20))
        center(d, H - 80, overlay, font(40), "white", W)
    im = im.rotate(6 if alt else -3, expand=False, fillcolor=bg)
    im.save(OUT / name)


def passbook(name, overlay):
    W, H = 900, 680
    im = Image.new("RGB", (W, H), (214, 205, 190))
    d = ImageDraw.Draw(im)
    d.rectangle([90, 60, 810, 600], fill=(250, 248, 240), outline=(120, 110, 95), width=3)
    d.rectangle([90, 60, 810, 130], fill=(30, 90, 70))
    center(d, 78, "SAVINGS ACCOUNT PASSBOOK", font(34), "white", W)
    rows = [("Name", "XXXXXXX KUMAR"), ("A/C No", "3407 XXXX XXXX 1182"), ("IFSC", "NSBK0004127"),
            ("Branch", "Station Road"), ("Customer ID", "XXXXX8813")]
    y = 170
    for k, v in rows:
        d.text((140, y), k, font=font(26, False), fill=(90, 80, 70))
        d.text((380, y), v, font=font(28), fill=(30, 30, 30))
        y += 62
    d.text((140, 500), "cheque book + ATM + net banking", font=font(24, False), fill=(60, 60, 60))
    d.rectangle([0, H - 80, W, H], fill=(20, 20, 20))
    center(d, H - 66, overlay, font(40), (255, 210, 0), W)
    im.filter(ImageFilter.SMOOTH).save(OUT / name)


def main():
    # --- scam posters ------------------------------------------------------------
    p = poster("kit_poster.png", [
        ("ALL BANK", 64, "fg"), ("CURRENT ACCOUNT", 76, "accent"), ("FULL KIT AVAILABLE", 64, "fg"),
        ("", 30, "fg"),
        ("ATM + PASSBOOK + CHEQUE BOOK", 40, "fg"), ("NET BANKING + SIM", 40, "fg"),
        ("KYC DONE  ·  HIGH LIMIT", 40, "accent"), ("", 30, "fg"),
        ("Gaming / P2P / Trading OK", 38, "fg"), ("", 30, "fg"),
        ("Telegram: t.me/kitwala_jpr", 42, "accent"), ("Call +91 01290 41736", 42, "fg"),
    ], bg=(12, 12, 14), fg=(245, 245, 245), accent=(255, 204, 0))
    # edited repost of the same poster (cropped + tinted) -> perceptual-hash match
    p2 = p.crop((20, 20, 880, 1080)).resize((900, 1100))
    tint = Image.new("RGB", p2.size, (40, 0, 0))
    Image.blend(p2, tint, 0.12).save(OUT / "kit_poster_repost.jpg", quality=80)

    poster("earn_poster.png", [
        ("EARN ₹30,000 / MONTH", 66, "accent"), ("", 20, "fg"),
        ("Bas apna bank account", 52, "fg"), ("kiraye pe do!", 60, "fg"), ("", 30, "fg"),
        ("✓ Ghar baithe income", 40, "fg"), ("✓ Students & housewives welcome", 36, "fg"),
        ("✓ 100% safe, no risk", 40, "fg"), ("", 30, "fg"),
        ("WhatsApp +91 01148 25519", 48, "accent"),
    ], bg=(0, 92, 64), fg=(255, 255, 255), accent=(255, 230, 90))

    poster("usdt_poster.png", [
        ("USDT P2P", 80, "accent"), ("CORPORATE ACCOUNTS", 56, "fg"), ("FOR SALE", 70, "fg"), ("", 30, "fg"),
        ("Fresh current a/c · Unlimited limit", 36, "fg"), ("Cash out account ready", 40, "fg"), ("", 30, "fg"),
        ("TG: t.me/cardzone_x", 46, "accent"),
    ], bg=(20, 24, 48), fg=(235, 238, 255), accent=(0, 210, 160), size=(900, 900))

    card("atm_card_sale.png", overlay="ATM CARD WITH PIN AVAILABLE")
    card("my_new_card.png", alt=True)          # benign: someone showing their new card (no overlay)
    passbook("passbook_kit.png", "KIT READY - DM NOW")

    # --- benign community images ---------------------------------------------------
    poster("awareness.png", [
        ("CYBER SAFETY ALERT", 60, "accent"), ("", 20, "fg"),
        ("NEVER SELL OR RENT", 56, "fg"), ("YOUR BANK ACCOUNT", 56, "fg"), ("", 20, "fg"),
        ("It makes you a MONEY MULE", 42, "fg"), ("and it is a punishable crime.", 38, "fg"), ("", 30, "fg"),
        ("Report fraud: cybercrime.gov.in", 38, "accent"), ("Helpline 1930", 52, "accent"),
    ], bg=(16, 42, 92), fg=(255, 255, 255), accent=(255, 196, 0), stripe=False)
    poster("hackathon.png", [
        ("SKIT TECH FEST 2026", 64, "accent"), ("", 20, "fg"), ("24-HOUR HACKATHON", 58, "fg"),
        ("AI · Web · Cyber Security", 42, "fg"), ("", 30, "fg"), ("Prizes worth ₹1,00,000", 46, "accent"),
        ("Register: pravah.skit.ac.in", 38, "fg"),
    ], bg=(74, 20, 140), fg=(255, 255, 255), accent=(255, 214, 102), size=(900, 900))
    poster("tiffin.png", [
        ("MAA KI RASOI", 70, "accent"), ("Home-style Tiffin Service", 44, "fg"), ("", 30, "fg"),
        ("Dal · Sabzi · 4 Roti · Rice", 40, "fg"), ("₹2,500 / month", 56, "accent"), ("", 30, "fg"),
        ("Mansarovar & Pratap Nagar", 38, "fg"),
    ], bg=(140, 56, 10), fg=(255, 245, 230), accent=(255, 214, 102), size=(900, 800))
    poster("room_rent.png", [
        ("ROOM FOR RENT", 72, "accent"), ("Malviya Nagar, Sector 6", 42, "fg"), ("", 30, "fg"),
        ("1 BHK · Furnished · Wi-Fi", 42, "fg"), ("₹8,000 / month", 54, "accent"),
        ("Students & working professionals", 34, "fg"),
    ], bg=(240, 236, 228), fg=(40, 40, 40), accent=(15, 118, 110), size=(900, 760), stripe=False)
    poster("cricket.png", [
        ("SUNDAY CRICKET", 70, "accent"), ("Central Park Ground", 44, "fg"), ("7:00 AM · Tennis ball", 42, "fg"),
        ("Need 4 more players!", 50, "accent"),
    ], bg=(22, 101, 52), fg=(255, 255, 255), accent=(255, 235, 59), size=(900, 640))
    # simple "laptop for sale" photo-ish graphic
    W, H = 900, 640
    im = Image.new("RGB", (W, H), (226, 220, 210))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([200, 120, 700, 440], 18, fill=(40, 40, 46))
    d.rectangle([224, 142, 676, 418], fill=(70, 130, 200))
    d.polygon([(150, 450), (750, 450), (800, 500), (100, 500)], fill=(160, 160, 168))
    center(d, 540, "Dell Inspiron · i5 · 8GB · ₹26,000", font(34), (40, 40, 40), W)
    im.save(OUT / "laptop.png")
    print("images ->", OUT)


if __name__ == "__main__":
    main()
