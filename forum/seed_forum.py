"""Seed the Charcha forum with 62 synthetic posts: ordinary community posts, tricky look-alikes
(awareness posts, bank questions, someone showing their new card, police news, toy guns, a pharmacy),
mule / card-sale ads — some posted by different accounts of the same seller network — and ads for
drugs, illegal arms and fake documents. Four sellers also hide their ads in the comments of ordinary posts.

    python seed_forum.py                # creates data/charcha.db (wipes the old one)
    python seed_forum.py --add-missing  # only adds seed posts not on the forum yet (keeps everything else)

All people, numbers, handles and banks are fictional."""
import random
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import forum_app as F  # noqa: E402

random.seed(42)
IMG = Path(__file__).parent / "seed" / "images"

# (user, community, hours_ago, title, body, link, image, score, [comments (user, text)])
POSTS = [
    # ---------------------------------------------------------------- mule / card-sale network A ("kitwala")
    ("rohit_traders", "JaipurBazaar", 50, "All bank current account full kit available 🔥",
     "Current account + savings account available. Full kit — ATM, passbook, cheque book, net banking, SIM.\n"
     "KYC done, high limit. Gaming / P2P work ke liye best.\nRate 18k per account. Telegram only: t.me/kitwala_jpr",
     "", "kit_poster_v2.png", 3, [("ankit_sharma", "Reported. This is literally money mule activity."), ("sonu_bhai_deals", "dm kiya bhai")]),
    ("quickdeals_jpr", "GamingAdda", 30, "Gaming payout account chahiye? DM",
     "Bhai log jinko gaming / betting ke liye withdrawal account chahiye, ready account hai.\n"
     "HDFC / ICICI / Kotak sab milega. Call or WA +91 01290 41736", "", "kit_poster_repost_v2.jpg", 2, []),
    ("sharma_enterprises", "PaisaTalk", 20, "Corporate account available for business use",
     "Firm current a/c available with net banking + ATM. 2 year old account, no questions asked.\n"
     "Bulk available for agents. Contact t.me/kitwala_jpr or +91 0129041736", "", "", 1, []),
    ("sonu_bhai_deals", "GamingAdda", 15, "BGMI tournament withdrawal ke liye khata chahiye?",
     "SBI, PNB, BOB ka khata kiraye pe milega, full kit with sim. Aadhaar linked, pre-activated.\n12k only. Call +91 01290 41736",
     "", "", 4, []),
    ("rohit_traders", "CampusCorner", 2, "Students — earn 15k by lending your account for 1 month",
     "Need savings account holders. Rent your account for 1 month, paisa turant.\nATM + net banking chahiye. Join t.me/kitwala_jpr",
     "", "", 1, []),

    # ---------------------------------------------------------------- network B (rent-your-account recruiters)
    ("earnfromhome_21", "NaukriAlerts", 40, "Work from home — earn ₹30,000/month, no investment",
     "Students, housewives sab apply karo. Kaam simple hai — bas apna bank account kiraye pe do, hum gaming "
     "transactions ke liye use karenge. Har mahine 30k guaranteed.\nPayment UPI se: earnfast21@ybl\nWhatsApp +91 01148 25519",
     "", "earn_poster_v2.png", 6, [("meena_r", "Isme fas mat jana koi, account freeze ho jata hai.")]),
    ("priya_jobs", "CampusCorner", 18, "Part time income for college students 💸",
     "Rent your bank account for 3 months and earn 25k. Only need ATM card + net banking details.\n"
     "Safe and genuine, 200+ students already earning. DM on WhatsApp", "https://wa.me/910114825519", "", 5, []),
    ("naukri_guru_jpr", "NaukriAlerts", 6, "घर बैठे कमाई का मौका",
     "अपना खाता किराये पर दो और हर महीने ₹20,000 पाओ। बस एटीएम कार्ड और पासबुक देना है।\nसंपर्क: +91 0114825519 — UPI earnfast21@ybl",
     "", "", 2, []),

    # ---------------------------------------------------------------- network C (cards / USDT)
    ("cardzone_official", "CryptoDesi", 34, "USDT P2P — corporate accounts for sale",
     "Fresh corporate & current accounts, unlimited limit, cash out account ready.\n"
     "Pay in USDT TRC20: TQ7Xk2YpZ6bM1rJ9aV8fW3eN4cL5hG2sD1\nTG t.me/cardzone_x", "", "usdt_poster.png", 3, []),
    ("cc_dealer_x", "CryptoDesi", 12, "Cards with PIN available | bulk",
     "Debit cards with PIN, ATM card for sale, all banks. Replacement guarantee. Escrow accepted.\nContact t.me/cardzone_x",
     "", "atm_card_sale.png", 2, []),
    ("vikram_p2p", "CryptoDesi", 26, "Need current accounts for P2P trading, paying 20k per account",
     "Looking for people who can give their current account or savings account for USDT P2P. Will pay 20k per account "
     "monthly. Account do paisa kamao.\nDM t.me/vikram_p2p_desk  ·  USDT accepted at TQ7Xk2YpZ6bM1rJ9aV8fW3eN4cL5hG2sD1",
     "", "", 1, []),

    # ---------------------------------------------------------------- network D (no-KYC + SIM combos)
    ("fastmoney_hub", "PaisaTalk", 22, "Account opening without KYC — ATM card in 2 days",
     "No KYC savings account available, get ATM card in 2 days. Limit increased accounts available.\n"
     "Contact +91 0175 93 6612", "https://bit.ly/fastacc-demo", "", 1, []),
    ("sim_store_jpr", "JaipurBazaar", 44, "Pre-activated SIM + savings account combo",
     "Pre-activated SIMs with linked savings account available, KYC done. Bulk available. WA +91 0175936612",
     "", "", 0, []),

    # ---------------------------------------------------------------- lone actors
    ("anon_seller77", "JaipurBazaar", 9, "s@vings acc0unt + a.t.m r3ady",
     "fr3sh acc0unt kit r3ady, n0 kyc, ib + atm + sim. price 15k. inbox only.\npay: kitdeal77@okaxis", "", "", 0, []),
    ("kit_wala_rajesh", "JaipurBazaar", 3, "DM for details 🔥🔥", "", "", "passbook_kit.png", 1, []),
    ("deepak_kumar_88", "PaisaTalk", 1.5, "Selling my old bank account kit, not using anymore",
     "Mera ICICI savings account hai, passbook ATM cheque book sab hai. Koi lena chahe toh 10k me de dunga.\nMessage me +91 0161 22 7730",
     "", "", 0, [("pooja_m", "Bhai mat karo ye, account pe case lag jayega")]),

    # ---------------------------------------------------------------- tricky but benign
    ("skit_cyber_club", "PaisaTalk", 60, "PSA: Never sell or rent your bank account",
     "Lots of 'earn 30k/month by renting your account' posts are going around. Your account gets used to move cyber-fraud "
     "money and YOU become the accused as a money mule.\nNever share your ATM card, passbook or net banking. "
     "Report such ads at cybercrime.gov.in or call 1930.", "", "awareness.png", 64,
     [("rahul_cse", "Thanks, sharing this in our class group."), ("nisha_t", "Very important. My cousin's account got frozen like this."),
      ("kitwala_support", "Bhai full kit available hai, current account + ATM + net banking. DM t.me/kitwala_jpr")]),
    ("ankit_sharma", "PaisaTalk", 28, "Lost my SBI ATM card yesterday, how to block it quickly?",
     "Tried customer care but the call keeps disconnecting. Is there an SMS method?", "", "", 11,
     [("kunal_g", "Use YONO or SMS BLOCK XXXX to 567676 from registered number.")]),
    ("meena_r", "PaisaTalk", 16, "Which bank is best for a current account for my boutique?",
     "Starting a small boutique in Vaishali Nagar. Need a current account with UPI QR and low charges. Suggestions?", "", "", 9, []),
    ("rahul_cse", "CampusCorner", 8, "Finally got my first debit card 😄",
     "Opened a savings account at the campus branch and they gave me a platinum debit card. Any tips on using it safely?",
     "", "my_new_card.png", 23, [("harsh_v", "Never share the CVV or OTP with anyone, and hide the card number before posting pics!")]),
    ("harsh_v", "JaipurBazaar", 12, "Selling Dell Inspiron laptop, i5 8GB, ₹26,000",
     "2 years old, good battery. Bill & box available. Call +91 0114 55 2093.", "", "laptop.png", 7, []),
    ("kunal_g", "PaisaTalk", 31, "Zero balance savings account — open via official app?",
     "Our bank now lets you open a zero balance savings account fully online through the official app with video KYC. "
     "Anyone tried it? Is the debit card free?", "", "", 6, []),
    ("pooja_m", "PaisaTalk", 5, "My account got frozen after I received money from an unknown person",
     "Someone sent me 9,800 'by mistake' and asked me to return it via UPI. Next day my account was frozen. "
     "Branch says there is a cyber cell complaint. What should I do?", "", "", 18,
     [("skit_cyber_club", "Write to the cyber cell with your statement — and never return money to a different account.")]),
    ("aditya_k", "CryptoDesi", 20, "Is P2P USDT trading safe? Worried about frozen accounts",
     "Heard many P2P traders get their bank accounts frozen because buyers pay with fraud money. How do you stay safe?", "", "", 14, []),
    ("nisha_t", "NaukriAlerts", 10, "Hiring: Accounts executive (Tally, GST) — Sitapura",
     "2+ years experience. Salary 22–28k. Send CV to careers@shreeramtextiles.example", "", "", 8, []),
    ("kunal_g", "PaisaTalk", 37, "Credit card limit increased after 1 year — worth using?",
     "Got my credit card limit doubled. Should I use more of it or keep utilisation low for CIBIL?", "", "", 5, []),

    # ---------------------------------------------------------------- normal community posts
    ("pravah_team", "CampusCorner", 46, "SKIT Tech Fest 2026 — 24 hour hackathon registrations open!",
     "AI, Web and Cyber Security tracks. Prizes worth ₹1,00,000. Teams of 2–4.", "https://pravah.skit.ac.in", "hackathon.png", 88, []),
    ("maa_ki_rasoi", "JaipurBazaar", 52, "Home-style tiffin service in Mansarovar — ₹2,500/month",
     "Dal, sabzi, 4 roti, rice. Lunch & dinner. Call +91 0101 23 4417", "", "tiffin.png", 15, []),
    ("ritu_homes", "JaipurBazaar", 41, "1 BHK furnished room for rent, Malviya Nagar",
     "₹8,000/month, Wi-Fi included, 5 min from GT. Students & working professionals welcome.", "", "room_rent.png", 12, []),
    ("cricket_jpr", "CampusCorner", 23, "Sunday cricket at Central Park — need 4 players",
     "7 AM, tennis ball. Everyone welcome, just bring water.", "", "cricket.png", 19, []),
    ("gate_aspirant", "CampusCorner", 36, "GATE CSE 2027 study group — weekends at central library",
     "Planning to cover OS, DBMS, CN and Algo with weekly mock tests. Comment if interested.", "", "", 27,
     [("rahul_cse", "Interested!"), ("aditya_k", "Count me in for OS and CN"),
      ("easy_paisa_jpr", "Students! Earn 2000 daily from home, no investment. WhatsApp +91 01870 01122")]),
    ("foodie_jaipur", "JaipurBazaar", 14, "Best momos near WTP?", "Tried 3 stalls, all average. Recommendations?", "", "", 21,
     [("harsh_v", "Try the one opposite gate 2, fried paneer momos are 🔥")]),
    ("bgmi_squad", "GamingAdda", 19, "Looking for 2 players for BGMI scrims (Ace+)",
     "We play 9–11 PM daily. Need an IGL and a support. Discord in comments.", "", "", 13, []),
    ("valorant_club", "GamingAdda", 48, "Inter-college Valorant tournament on 25 Oct",
     "Free entry, 16 teams, LAN at the college auditorium.", "", "", 34, []),
    ("bike_seller_raj", "JaipurBazaar", 27, "Selling Honda Activa 2019, single owner, ₹42,000",
     "18,000 km, insurance valid till 2027. WhatsApp +91 0187 61 2235", "", "", 4, []),
    ("rpsc_prep", "NaukriAlerts", 33, "RPSC Programmer exam date announced?",
     "Anyone saw the official notice? Coaching says December.", "", "", 10, []),
    ("startup_hr", "NaukriAlerts", 13, "Internship: React developer at a Jaipur startup (₹12k stipend)",
     "3 months, hybrid. Send GitHub link.", "https://forms.gle/example", "", 22, []),
    ("lost_found_jpr", "JaipurBazaar", 7, "Found a wallet near SMS hospital with Aadhaar & college ID",
     "Name on ID: Arjun. DM me with details to claim it.", "", "", 30, []),
    ("neha_cs", "CampusCorner", 29, "Which laptop for CSE under 50k?",
     "Mostly coding, some Android Studio. Ryzen 5 or i5?", "", "", 16, []),
    ("metro_watcher", "JaipurBazaar", 55, "Jaipur metro phase 2 — any update on construction?", "", "", "", 9, []),
    ("hodl_bhai", "CryptoDesi", 24, "Bitcoin at a new high again — taking profits or holding?",
     "Not financial advice, just curious what everyone is doing.", "", "", 12, []),
    ("sip_guru", "PaisaTalk", 39, "SIP vs FD for a college student with ₹2,000/month?",
     "Want to start investing small. Index fund SIP or recurring deposit?", "", "", 20,
     [("kunal_g", "Index fund SIP, long term. Keep 3 months expense in FD/RD as emergency."),
      ("quick_earn_99", "Want 25k/month without investing? Rent your savings account, sirf gaming ke liye. WhatsApp +91 01148 25519")]),
    ("os_notes", "CampusCorner", 17, "Operating Systems Unit 3 notes (deadlocks & banker's algorithm)",
     "Handwritten notes, scanned. Hope it helps for the mid-sem.", "https://drive.google.com/example-os-notes", "", 41, []),
    ("bookworm_skit", "JaipurBazaar", 21, "Second-hand engineering books, 3rd sem CSE, half price",
     "DSA, DE, Discrete Maths, OOP. Pickup near campus.", "", "", 6, []),
    ("code_saturday", "CampusCorner", 11, "Free coding bootcamp this Saturday — intro to Python",
     "Beginner friendly, bring your laptop. Room 204, 10 AM.", "", "", 25, []),
    ("music_jpr", "JaipurBazaar", 43, "Selling Yamaha F310 guitar with bag, ₹6,500", "Barely used.", "", "", 3, []),
    ("delivery_jobs", "NaukriAlerts", 4, "Part-time food delivery partners needed — Malviya Nagar",
     "Own bike & DL required. Weekly payout to your bank account.", "", "", 7, []),
    ("traveller_jpr", "CampusCorner", 25, "Anyone going to Pushkar this weekend? Sharing a cab",
     "Leaving Saturday 6 AM, back Sunday evening.", "", "", 8, []),
    ("po_aspirant", "NaukriAlerts", 35, "Best coaching for Bank PO exams in Jaipur?",
     "Preparing for IBPS PO 2027. Offline coaching near Gopalpura or online is better?", "", "", 15,
     [("rpsc_prep", "Online mocks + self study worked for me.")]),
    ("mc_jaipur", "GamingAdda", 57,"Minecraft survival server for Jaipur players",
     "Java + Bedrock, whitelist only. Comment your IGN.", "", "", 11, []),

    # ---------------------------------------------------------------- illegal goods: drugs, arms, fake documents
    # (Rajasthan Police problem statement). Numbers are +91 0... demo numbers; the digit after the 0 is a demo
    # telecom circle (1 Rajasthan, 4 Bihar & Jharkhand, 9 Punjab), so the jurisdiction hint shows something.
    ("party_supply_jpr", "CampusCorner", 14, "Farewell party ke liye saman chahiye? 🍁❄️",
     "Malana cream, OG aur MD powder available hai. Jaipur mein same day home delivery, discreet packing.\n"
     "Students ke liye special rate. Menu ke liye DM karo: t.me/partysupply_jpr", "", "", 2,
     [("rahul_cse", "Reported to the mods, this is not okay on a campus board.")]),
    ("green_leaf_jdh", "JaipurBazaar", 8, "Pure maal 🌿 Jodhpur / Pali delivery",
     "Doda post aur afeem wholesale rate pe. 1 kg ka rate inbox karo. Police ka dar nahi, ghar tak delivery.\n"
     "WhatsApp +91 01450 27719", "", "", 0, []),
    ("ganganagar_supply", "CryptoDesi", 5, "USDT accepted ❄️ chitta maal ready",
     "Chitta maal aur smack, Sri Ganganagar / Hanumangarh supply. Payment USDT ya UPI. Contact +91 09812 40551",
     "", "", 0, []),
    ("desi_hathiyar_sk", "JaipurBazaar", 11, "🔫 Desi katta + kartoos, bina licence",
     "315 bore desi katta ready stock, 12 kartoos saath mein. Fitting ekdum sahi, test karke denge. Rate 18k.\n"
     "Sikar / Jhunjhunu hand delivery. WhatsApp +91 04771 30628", "", "", 1, []),
    ("hathiyar_wala_x", "JaipurBazaar", 3, "Pistol chahiye? 9mm aur 32 bore available",
     "Imported jaisa finish, naya piece. Safe delivery all Rajasthan, no licence needed. Price list inbox.\n"
     "Telegram: t.me/hathiyar_wala", "", "", 0, []),
    ("doc_seva_fast", "NaukriAlerts", 20, "Sarkari naukri ke liye degree / marksheet banwaye",
     "Any university degree available, backdated marksheet, 10th / 12th bhi. Verification mein pass, 2 din mein ready.\n"
     "Price 25k. Contact +91 01290 55180", "", "", 0,
     [("po_aspirant", "Isse naukri nahi jail milegi bhai.")]),
    ("aadhaar_pan_center", "PaisaTalk", 6, "Aadhaar / PAN bina documents, 24 ghante mein",
     "Duplicate aadhaar, PAN card without documents, DOB change without proof. Loan file ke liye bhi chalega.\n"
     "WhatsApp +91 01385 66204", "", "", 0, []),
    # look-alikes that must stay low: news of a seizure, a de-addiction drive, Holi toy guns, a pharmacy, a CSC camp
    ("jaipur_crime_news", "CampusCorner", 18, "Police ne 12 kg ganja aur 2 desi katte ke saath gang pakda",
     "Jaipur commissionerate ki DST team ne Sanganer mein raid ki. 3 aaropi giraftar, NDPS act aur arms act mein case darj. "
     "Mauke se fake marksheet bhi baramad hui.", "", "", 23,
     [("nisha_t", "Good work by the police."),
      ("maal_wala_99", "Bhai party ke liye ganja / MD chahiye toh DM, home delivery 🍁 t.me/maalwala99")]),
    ("nasha_mukti_rj", "CampusCorner", 30, "Nasha mukti campus drive 🍃 — say no to drugs",
     "Hostels mein MD aur chitta ka nasha badh raha hai. Kisi dost ko help chahiye toh Tele-MANAS 14416 par call karein "
     "ya SMS hospital ke de-addiction centre jaayein. Drug free campus!", "", "", 31, []),
    ("holi_toys_jpr", "JaipurBazaar", 16, "Holi special: water guns 🔫 aur pichkari, home delivery",
     "Water pistol, toy gun, gulal combo. Wholesale rate for shops, ready stock. Call +91 01412 33870", "", "", 6, []),
    ("city_pharmacy_jpr", "JaipurBazaar", 22, "Medicines home delivery — Vaishali Nagar",
     "BP, sugar aur thyroid ki dawaiyan same day delivery. Codeine wali cough syrup aur tramadol sirf doctor's prescription "
     "ke saath milegi. Licensed pharmacy.", "", "", 9, []),
    ("csc_sanganer", "NaukriAlerts", 26, "Aadhaar update / PAN card camp at CSC centre",
     "Aadhaar mein DOB aur address update, naya PAN card apply. Original documents saath laayein. Official UIDAI process, "
     "fees as per govt rate.", "", "", 12, []),
]

EXTRA_USERS = ["demo", "judge1", "judge2", "judge3"]


def add_missing():
    """Add seed posts whose title isn't on the forum yet, keeping everything that is there (live server)."""
    F.init_db()
    now = datetime.utcnow()
    added = 0
    with F.db() as c:
        have = {r[0] for r in c.execute("SELECT title FROM posts")}
        users = {r[1]: r[0] for r in c.execute("SELECT id, username FROM users")}

        def uid(name):
            if name not in users:
                users[name] = F.create_user(c, name, "charcha123", (now - timedelta(days=random.randint(3, 400))).isoformat())
            return users[name]
        for user, comm, hrs, title, body, link, image, score, comments in sorted(POSTS, key=lambda p: -p[2]):
            if title in have:
                continue
            created = now - timedelta(hours=hrs, minutes=random.randint(0, 50))
            if image and not (F.UPLOADS / image).exists():
                shutil.copy(IMG / image, F.UPLOADS / image)
            cur = c.execute("INSERT INTO posts(user_id,community,title,body,link,image,created,score) VALUES(?,?,?,?,?,?,?,?)",
                            (uid(user), comm, title, body, link, image, created.isoformat(), score))
            for i, (cu, text) in enumerate(comments):
                c.execute("INSERT INTO comments(post_id,user_id,body,created) VALUES(?,?,?,?)",
                          (cur.lastrowid, uid(cu), text, min(now, created + timedelta(minutes=20 + 35 * i)).isoformat()))
            added += 1
    print(f"Added {added} new posts ({len(POSTS) - added} already there) -> {F.DB_PATH}")


def main():
    if "--add-missing" in sys.argv:
        return add_missing()
    if F.DB_PATH.exists():
        F.DB_PATH.unlink()
    for f in F.UPLOADS.glob("*"):
        f.unlink()
    F.init_db()
    now = datetime.utcnow()
    with F.db() as c:
        users = {}
        names = {p[0] for p in POSTS} | {u for p in POSTS for u, _ in p[8]}
        for name in sorted(names):
            joined = (now - timedelta(days=random.randint(3, 400))).isoformat()
            users[name] = F.create_user(c, name, "charcha123", joined)
        for name in EXTRA_USERS:
            users[name] = F.create_user(c, name, "demo123")
        # oldest first so ids increase with time
        for user, comm, hrs, title, body, link, image, score, comments in sorted(POSTS, key=lambda p: -p[2]):
            created = now - timedelta(hours=hrs, minutes=random.randint(0, 50))
            if image:
                shutil.copy(IMG / image, F.UPLOADS / image)
            cur = c.execute("INSERT INTO posts(user_id,community,title,body,link,image,created,score) VALUES(?,?,?,?,?,?,?,?)",
                            (users[user], comm, title, body, link, image, created.isoformat(), score))
            for i, (cu, text) in enumerate(comments):
                c.execute("INSERT INTO comments(post_id,user_id,body,created) VALUES(?,?,?,?)",
                          (cur.lastrowid, users[cu], text,
                           min(now, created + timedelta(minutes=20 + 35 * i)).isoformat()))
    print(f"Seeded {len(POSTS)} posts, {len(names) + len(EXTRA_USERS)} users -> {F.DB_PATH}")
    print("Logins: demo / demo123, judge1..judge3 / demo123 (seed users: <name> / charcha123)")


if __name__ == "__main__":
    main()
