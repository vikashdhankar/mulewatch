"""Hindi interface text. Edit here, then run:  python3 scripts/hi_source.py   (writes src/hi.json)
Keys are the English text exactly as written in the code; {name} placeholders must stay as they are."""
import json
from pathlib import Path

HI = {
    # ---- navigation and shell
    "Command center": "कमांड सेंटर", "Cases": "प्रकरण", "Seller network": "विक्रेता नेटवर्क",
    "District map": "ज़िला मानचित्र", "Victim complaints": "पीड़ित शिकायतें", "Check a post": "पोस्ट जाँचें",
    "Bulk link check": "कई लिंक जाँचें", "Watchlist": "निगरानी सूची", "Monitored sources": "निगरानी स्रोत",
    "Daily brief": "दैनिक सारांश", "Officers": "अधिकारी", "Audit log": "ऑडिट लॉग",
    "Detecting sale and rental of bank accounts, ATM cards and banking kits on public platforms.":
        "सार्वजनिक प्लेटफ़ॉर्म पर बैंक खाते, एटीएम कार्ड और बैंकिंग किट की बिक्री व किराये का पता लगाना।",
    "Menu": "मेनू", "Alert sound": "अलर्ट ध्वनि", "Sound on": "ध्वनि चालू", "Sound off": "ध्वनि बंद",
    "Source unreachable": "स्रोत तक पहुँच नहीं", "Comments not readable: update the forum": "टिप्पणियाँ पढ़ी नहीं जा सकीं: फ़ोरम अपडेट करें",
    "Monitoring {n} source": "{n} स्रोत की निगरानी", "Monitoring {n} sources": "{n} स्रोतों की निगरानी",
    "Reconnecting…": "फिर से जुड़ रहा है…", "last crawl {ago}": "अंतिम जाँच {ago}",
    "{level} alert": "{level} अलर्ट", "Dismiss": "हटाएँ", "Open case": "प्रकरण खोलें",
    "My account and Telegram": "मेरा खाता और टेलीग्राम", "Sign out": "साइन आउट",
    "Your password was set by a supervisor. {link} before you continue.": "आपका पासवर्ड पर्यवेक्षक ने सेट किया है। आगे बढ़ने से पहले {link}।",
    "Choose your own password": "अपना पासवर्ड चुनें",
    "Demo accounts with the shared password are still active. Disable them or change their passwords on the Officers page before real use.":
        "साझा पासवर्ड वाले डेमो खाते अभी सक्रिय हैं। वास्तविक उपयोग से पहले इन्हें बंद करें या अधिकारी पृष्ठ पर इनके पासवर्ड बदलें।",
    "Page not found.": "पृष्ठ नहीं मिला।", "Back to the command center": "कमांड सेंटर पर लौटें",
    "just now": "अभी", "{n} min ago": "{n} मिनट पहले", "{n} h ago": "{n} घंटे पहले", "{n} d ago": "{n} दिन पहले",
    "Loading…": "लोड हो रहा है…", "Close": "बंद करें", "Back": "पीछे", "…": "…",

    # ---- roles, levels, statuses, categories
    "Analyst": "विश्लेषक", "Investigating Officer": "अनुसंधान अधिकारी", "Supervisor": "पर्यवेक्षक",
    "Critical": "गंभीर", "High": "उच्च", "Medium": "मध्यम", "Low": "निम्न",
    "New": "नया", "Verified": "सत्यापित", "Notice drafted": "सूचना का प्रारूप तैयार", "Notice sent": "सूचना भेजी गई",
    "Content removed": "सामग्री हटाई गई", "Linked to FIR": "एफ.आई.आर. से जुड़ा", "Closed – no action": "बंद – कार्यवाही नहीं",
    "Mule Account Sale": "म्यूल खाता बिक्री", "Account-Holder Recruitment": "खाताधारकों की भर्ती", "Card Sale": "कार्ड बिक्री",
    "KYC Fraud": "केवाईसी धोखाधड़ी", "Easy-Money Lure": "आसान कमाई का लालच", "Reported Fraud Attempt": "धोखाधड़ी के प्रयास की रिपोर्ट",
    "Suspicious Financial Ad": "संदिग्ध वित्तीय विज्ञापन", "Benign": "सामान्य",
    "Mule-account sale language": "म्यूल खाता बिक्री की भाषा", "Card sale": "कार्ड बिक्री",
    "Recruiting account holders": "खाताधारकों की भर्ती", "KYC evasion / trust cue": "केवाईसी से बचाव / भरोसे का संकेत",
    "Financial instrument": "वित्तीय साधन", "Sale / rent intent": "बिक्री / किराये का इरादा",
    "Awareness context (lowers risk)": "जागरूकता संदर्भ (जोखिम घटाता है)",

    # ---- identifiers
    "Phone": "फ़ोन", "UPI ID": "यूपीआई आईडी", "Telegram": "टेलीग्राम", "WhatsApp": "व्हाट्सऐप", "Handle": "हैंडल",
    "Link": "लिंक", "Email": "ई-मेल", "IFSC": "आई.एफ.एस.सी.", "Card no.": "कार्ड नं.", "Crypto wallet": "क्रिप्टो वॉलेट",
    "Price": "मूल्य", "Domain": "डोमेन", "Account no.": "खाता नं.", "Telegram link": "टेलीग्राम लिंक",
    "Website / domain": "वेबसाइट / डोमेन", "Keyword": "कीवर्ड", "Phone number": "फ़ोन नंबर", "UPI": "यूपीआई",
    "Wallet": "वॉलेट", "Card": "कार्ड", "Account": "खाता", "ifsc": "आई.एफ.एस.सी.", "account": "खाता", "upi": "यूपीआई",
    "text": "पाठ", "html": "पेज", "image": "चित्र", "screenshot": "स्क्रीनशॉट",

    # ---- login
    "Cyber crime command center": "साइबर अपराध कमांड सेंटर",
    "Finds online ads selling or renting bank accounts, ATM cards and banking kits, links them to victim complaints, and prepares the notices, bank requests and evidence to act on them.":
        "बैंक खाते, एटीएम कार्ड और बैंकिंग किट बेचने या किराये पर देने वाले ऑनलाइन विज्ञापन खोजता है, उन्हें पीड़ितों की शिकायतों से जोड़ता है, और कार्यवाही के लिए सूचना पत्र, बैंक अनुरोध और साक्ष्य तैयार करता है।",
    "Every action is recorded in a tamper-evident audit log.": "हर कार्यवाही छेड़छाड़-प्रमाणित ऑडिट लॉग में दर्ज होती है।",
    "Complaint data stays encrypted on this computer.": "शिकायतों का डेटा इसी कंप्यूटर पर एन्क्रिप्टेड रहता है।",
    "Every flag is a lead for an officer to verify, never an automatic action.": "हर चेतावनी अधिकारी द्वारा जाँच हेतु एक सुराग है, स्वचालित कार्यवाही नहीं।",
    "Sign in": "साइन इन", "Signing in…": "साइन इन हो रहा है…", "Username": "उपयोगकर्ता नाम", "Password": "पासवर्ड",
    "Demo accounts: {a}, {i} (Investigating Officer) and {s} (supervisor), password {p}.":
        "डेमो खाते: {a}, {i} (अनुसंधान अधिकारी) और {s} (पर्यवेक्षक), पासवर्ड {p}।",

    # ---- dashboard
    "Every new public post is scanned for the sale or rental of bank accounts, cards and banking kits.":
        "हर नई सार्वजनिक पोस्ट में बैंक खाते, कार्ड और बैंकिंग किट की बिक्री या किराये की जाँच होती है।",
    "posts and comments scanned": "पोस्ट और टिप्पणियाँ जाँची गईं", "flagged high or critical": "उच्च या गंभीर चिह्नित",
    "critical": "गंभीर", "linked to complaints · {amount}": "शिकायतों से जुड़े · {amount}", "linked to victim complaints": "पीड़ित शिकायतों से जुड़े",
    "seller rings found": "विक्रेता गिरोह मिले", "open cases · {n} assigned to you": "खुले प्रकरण · {n} आपको आवंटित",
    "open cases to act on": "कार्यवाही हेतु खुले प्रकरण", "Live intercepts": "लाइव पकड़", "Hide low risk": "निम्न जोखिम छिपाएँ",
    "Waiting for posts": "पोस्ट की प्रतीक्षा", "New posts on monitored sources appear here within seconds.": "निगरानी स्रोतों की नई पोस्ट कुछ ही सेकंड में यहाँ दिखती हैं।",
    "Takedown clocks": "टेकडाउन घड़ियाँ", "{n} notices pending": "{n} सूचनाएँ लंबित", "Seller rings": "विक्रेता गिरोह",
    "Open network": "नेटवर्क खोलें", "No coordinated activity yet.": "अभी कोई समन्वित गतिविधि नहीं।", "Risk mix": "जोखिम वितरण",
    "Posts over time": "समय के साथ पोस्ट", "Flagged": "चिह्नित", "Other": "अन्य",
    "Words that gave sellers away": "विक्रेताओं को पकड़वाने वाले शब्द", "Identifiers reused across posts": "कई पोस्ट में दोहराए गए पहचान विवरण",
    "None yet.": "अभी कोई नहीं।", "{n} posts": "{n} पोस्ट", "Can't reach the MuleWatch API": "MuleWatch API से संपर्क नहीं हो पा रहा",
    "Citizen reports": "नागरिक रिपोर्ट", "Details": "विवरण", "Scan to report a suspicious ad on Telegram": "टेलीग्राम पर संदिग्ध विज्ञापन की रिपोर्ट हेतु स्कैन करें",
    "{a} reports from {b} people": "{b} लोगों से {a} रिपोर्ट", "Connecting to Telegram…": "टेलीग्राम से जुड़ रहा है…",

    # ---- post rows and chips
    "comment": "टिप्पणी", "reported by {n} citizen": "{n} नागरिक द्वारा रिपोर्ट", "reported by {n} citizens": "{n} नागरिकों द्वारा रिपोर्ट",
    "ring of {n}": "{n} का गिरोह", "confirmed": "पुष्टि", "false positive": "गलत चेतावनी",
    "{amount} reported lost": "{amount} की हानि दर्ज", "{n} complaint": "{n} शिकायत", "{n} complaints": "{n} शिकायतें",
    "back after takedown": "हटाने के बाद फिर आया", "Recruiter priority": "भर्तीकर्ता प्राथमिकता", "recruiter {n}": "भर्तीकर्ता {n}",
    "(image only)": "(केवल चित्र)", "takedown requested": "हटाने का अनुरोध",

    # ---- cases list
    "All categories": "सभी श्रेणियाँ", "Category": "श्रेणी", "Verdict": "निर्णय", "Any verdict": "कोई भी निर्णय", "Not reviewed": "समीक्षा नहीं हुई",
    "Confirmed": "पुष्ट", "False positive": "गलत चेतावनी", "Source": "स्रोत", "Any source": "कोई भी स्रोत",
    "Forum posts and comments": "फ़ोरम पोस्ट और टिप्पणियाँ", "Citizen reports ({n})": "नागरिक रिपोर्ट ({n})",
    "Checked links": "जाँचे गए लिंक", "Monitored pages": "निगरानी वाले पेज", "Manual checks": "हाथ से जाँच",
    "Chrome extension": "क्रोम एक्सटेंशन", "Telegram channels": "टेलीग्राम चैनल", "Bulk link checks": "एक साथ जाँचे गए लिंक",
    "Case status": "प्रकरण की स्थिति", "Any status": "कोई भी स्थिति", "Open cases": "खुले प्रकरण", "Assigned": "आवंटन",
    "Anyone's": "किसी का भी", "Assigned to me": "मुझे आवंटित", "Not assigned": "आवंटित नहीं",
    "Linked to complaints": "शिकायतों से जुड़े", "Sort": "क्रम", "Highest risk first": "सबसे अधिक जोखिम पहले",
    "Recruiters first": "भर्तीकर्ता पहले", "Newest first": "नवीनतम पहले",
    "Search text, phone, UPI, account, author": "पाठ, फ़ोन, यूपीआई, खाता, लेखक खोजें",
    "No cases match these filters": "इन फ़िल्टर से कोई प्रकरण नहीं मिला", "Clear a filter or wait for new posts.": "कोई फ़िल्टर हटाएँ या नई पोस्ट की प्रतीक्षा करें।",
    "{n} cases": "{n} प्रकरण", "{n} linked posts": "{n} जुड़ी पोस्ट", "by {n} account": "{n} खाते से", "by {n} accounts": "{n} खातों से",
    "{n} post matches. Open one to see the evidence and record a verdict.": "{n} पोस्ट मिली। साक्ष्य देखने और निर्णय दर्ज करने हेतु उसे खोलें।",
    "{n} posts match. Open one to see the evidence and record a verdict.": "{n} पोस्ट मिलीं। साक्ष्य देखने और निर्णय दर्ज करने हेतु किसी को खोलें।", "Status": "स्थिति",

    # ---- case page
    "Post content": "पोस्ट की सामग्री", "sale language": "बिक्री की भाषा", "evasion cue": "बचाव का संकेत", "identifier": "पहचान विवरण",
    "context word": "संदर्भ शब्द", "awareness": "जागरूकता", "No text — image-only post.": "पाठ नहीं — केवल चित्र वाली पोस्ट।",
    "Image attached to the post": "पोस्ट के साथ लगा चित्र", "Text read from the image": "चित्र से पढ़ा गया पाठ",
    "No readable text found (is Tesseract installed?).": "पढ़ने योग्य पाठ नहीं मिला (क्या Tesseract इंस्टॉल है?)।",
    "Words found in the image:": "चित्र में मिले शब्द:", "Why it was flagged": "चिह्नित करने का कारण",
    "No risk indicators found.": "कोई जोखिम संकेत नहीं मिला।", "Identifiers": "पहचान विवरण",
    "Add one to the watchlist to alert on any future post that uses it": "निगरानी सूची में जोड़ें, ताकि आगे किसी पोस्ट में उपयोग होने पर अलर्ट मिले",
    "No phone numbers, payment IDs or links found.": "कोई फ़ोन नंबर, भुगतान आईडी या लिंक नहीं मिला।",
    "On watchlist": "निगरानी सूची में", "Add to watchlist": "निगरानी सूची में जोड़ें",
    "Keyword & identifier rules": "कीवर्ड और पहचान नियम", "Multilingual text model": "बहुभाषी पाठ मॉडल",
    "strongest signals: {s}": "सबसे मज़बूत संकेत: {s}", "Image analysis": "चित्र विश्लेषण", "seen in image: {s}": "चित्र में दिखा: {s}",
    "no banking material in image": "चित्र में बैंकिंग सामग्री नहीं", "AI analyst (Claude)": "एआई विश्लेषक (Claude)",
    "Combined base score": "संयुक्त आधार स्कोर", "Seller-ring boost": "विक्रेता गिरोह बढ़त", "Watchlist match": "निगरानी सूची मिलान",
    "Case {id} not found": "प्रकरण {id} नहीं मिला", "Loading case…": "प्रकरण लोड हो रहा है…",
    "Verdict saved. Keyword weights and the text model were updated.": "निर्णय सहेजा गया। कीवर्ड भार और पाठ मॉडल अपडेट हुए।",
    "Marked as false positive. The model learned from it and rescored all posts.": "गलत चेतावनी के रूप में चिह्नित। मॉडल ने इससे सीखा और सभी पोस्ट दोबारा आँकीं।",
    "Removed through the forum's moderation API. The case is now marked Content removed, and MuleWatch will alert if it comes back.":
        "फ़ोरम के मॉडरेशन API से हटाया गया। प्रकरण अब 'सामग्री हटाई गई' है, और यह फिर दिखने पर MuleWatch अलर्ट देगा।",
    "Added {v} to the watchlist.": "{v} निगरानी सूची में जोड़ा गया।", "Image post": "चित्र पोस्ट",
    "posted {ago}": "पोस्ट {ago}", "language {l}": "भाषा {l}", "open original": "मूल खोलें",
    "Confirm fraud": "धोखाधड़ी की पुष्टि", "Remove via forum API": "फ़ोरम API से हटाएँ", "Removed on forum": "फ़ोरम से हटाया गया",
    "Demo: uses the Charcha forum's moderation API": "डेमो: चर्चा फ़ोरम का मॉडरेशन API उपयोग करता है",
    "Evidence report (PDF)": "साक्ष्य रिपोर्ट (PDF)", "Phone and account numbers are partly hidden for your role.": "आपकी भूमिका के लिए फ़ोन और खाता नंबर आंशिक रूप से छिपे हैं।",
    "Linked posts": "जुड़ी पोस्ट", "Full network": "पूरा नेटवर्क", "Not linked to any other post by text, image or identifiers.": "पाठ, चित्र या पहचान विवरण से किसी अन्य पोस्ट से नहीं जुड़ा।",
    "Reported through the Telegram bot. Reporters are told when you confirm, dismiss or take this down.":
        "टेलीग्राम बॉट से रिपोर्ट किया गया। आपके पुष्टि करने, खारिज करने या हटाने पर रिपोर्टर को सूचना जाती है।",
    "Record hash": "अभिलेख हैश", "SHA-256 of the captured post, metadata and image, recorded at capture time:": "सुरक्षित पोस्ट, मेटाडेटा और चित्र का SHA-256, सुरक्षित करते समय दर्ज:",
    "Draft downloaded. The export is recorded in the case's chain of custody.": "प्रारूप डाउनलोड हुआ। यह प्रकरण की चेन ऑफ़ कस्टडी में दर्ज है।",

    # ---- workflow panel
    "Case workflow": "प्रकरण कार्यप्रवाह", "This case was closed without action.": "यह प्रकरण बिना कार्यवाही बंद किया गया।",
    "Mark notice sent (starts clock)": "सूचना भेजी गई चिह्नित करें (घड़ी शुरू)", "Reopen": "फिर खोलें", "Mark: {s}": "चिह्नित करें: {s}",
    "Assigned to": "आवंटित", "Take this case": "यह प्रकरण लें", "Release": "छोड़ें", "FIR number": "एफ.आई.आर. क्रमांक",
    "Police station": "पुलिस थाना", "Cyber Police Station, …": "साइबर पुलिस थाना, …", "Case notes": "प्रकरण टिप्पणियाँ",
    "What was done, who was contacted, reference numbers…": "क्या किया गया, किससे संपर्क हुआ, संदर्भ क्रमांक…",
    "Save details": "विवरण सहेजें", "FIR": "एफ.आई.आर.", "Next steps": "अगले कदम",
    "An Investigating Officer takes the case from here.": "यहाँ से अनुसंधान अधिकारी प्रकरण संभालते हैं।",

    # ---- clock
    "Removed within the window": "समय-सीमा में हटाया गया", "Removed after the window ran out": "समय-सीमा के बाद हटाया गया",
    "{p} took {d} after the notice ({h} h allowed)": "{p} ने सूचना के बाद {d} लिए ({h} घंटे की अनुमति)",
    "{n} min": "{n} मिनट", "{n} h": "{n} घंटे", "Overdue by {d}": "{d} से अधिक विलंब", "{d} left": "{d} शेष",
    "{p} has not removed the content within {h} h of the notice. Escalate or record non-compliance.":
        "{p} ने सूचना के {h} घंटे में सामग्री नहीं हटाई। उच्च स्तर पर भेजें या अनुपालन न होना दर्ज करें।",
    "for {p} to remove the content · notice sent {when} IST": "{p} द्वारा सामग्री हटाने हेतु · सूचना भेजी {when} IST",

    # ---- recruiter, complaints, banks, jurisdiction
    "Recruiters and bulk resellers are ranked above people selling one account, who are often victims themselves.":
        "भर्तीकर्ता और थोक विक्रेता एक खाता बेचने वालों से ऊपर रखे जाते हैं, जो अक्सर स्वयं पीड़ित होते हैं।",
    "Victim complaints ({n})": "पीड़ित शिकायतें ({n})", "{amount} lost": "{amount} की हानि", "Complaint": "शिकायत", "Date": "दिनांक",
    "Amount": "राशि", "District": "ज़िला", "Matched on": "मिलान",
    "The identifiers in this ad appear in {n} victim complaints. Complaint details are visible to Investigating Officers.":
        "इस विज्ञापन के पहचान विवरण {n} पीड़ित शिकायतों में हैं। शिकायत का विवरण अनुसंधान अधिकारी देख सकते हैं।",
    "Banks and payment apps": "बैंक और भुगतान ऐप", "Draft request": "अनुरोध का प्रारूप", "Suggested jurisdiction": "संभावित क्षेत्राधिकार",
    "medium confidence": "मध्यम विश्वास", "low confidence": "कम विश्वास", "Cyber Police Station, {d}": "साइबर पुलिस थाना, {d}",
    "No location signal yet.": "अभी स्थान का कोई संकेत नहीं।",

    # ---- evidence
    "Evidence": "साक्ष्य", "unchanged since capture": "सुरक्षित करने के बाद से अपरिवर्तित", "a file has changed": "एक फ़ाइल बदली है",
    "captured {when} IST": "सुरक्षित {when} IST", "Download": "डाउनलोड",
    "Captured before evidence capture was added. The record hash is still below.": "साक्ष्य सुविधा जुड़ने से पहले सुरक्षित। अभिलेख हैश नीचे है।",
    "Full-page screenshots are off:": "पूरे पेज के स्क्रीनशॉट बंद हैं:", "install Playwright to turn them on": "चालू करने हेतु Playwright इंस्टॉल करें",
    "Evidence pack (ZIP)": "साक्ष्य पैक (ZIP)", "Show chain of custody ({n})": "चेन ऑफ़ कस्टडी दिखाएँ ({n})",
    "Hide chain of custody ({n})": "चेन ऑफ़ कस्टडी छिपाएँ ({n})", "Downloaded {name}. SHA-256 of the ZIP: {sha}": "{name} डाउनलोड हुआ। ZIP का SHA-256: {sha}",
    "When (IST)": "समय (IST)", "Who": "कौन", "Action": "कार्यवाही",

    # ---- drafts
    "Legal drafts": "विधिक प्रारूप", "English or Hindi · Word or PDF": "अंग्रेज़ी या हिंदी · Word या PDF",
    "Takedown notice to the platform (Sec. 79(3)(b) IT Act, via Sahyog)": "प्लेटफ़ॉर्म को टेकडाउन सूचना (धारा 79(3)(b) आई.टी. अधिनियम, सहयोग द्वारा)",
    "Data preservation request to the platform": "प्लेटफ़ॉर्म को डेटा सुरक्षित रखने का अनुरोध",
    "Request to the bank's nodal officer": "बैंक के नोडल अधिकारी को अनुरोध",
    "Section 63 BSA certificate for the evidence": "साक्ष्य हेतु धारा 63 बी.एस.ए. प्रमाण पत्र",
    "Notice under Section 79(3)(b) IT Act for the platform, to file on the Sahyog portal. Linked posts on the same platform are included.":
        "सहयोग पोर्टल पर दर्ज करने हेतु प्लेटफ़ॉर्म को धारा 79(3)(b) आई.टी. अधिनियम के अंतर्गत सूचना। उसी प्लेटफ़ॉर्म की जुड़ी पोस्ट भी शामिल हैं।",
    "Asks the platform to preserve account records and logs for 180 days, ahead of a formal data request.":
        "औपचारिक डेटा अनुरोध से पहले प्लेटफ़ॉर्म से खाते के अभिलेख और लॉग 180 दिन सुरक्षित रखने का अनुरोध।",
    "Request to the bank's nodal officer for KYC, statements and logs, with linked complaints for marking a lien.":
        "बैंक के नोडल अधिकारी से के.वाई.सी., खाता विवरण और लॉग का अनुरोध, लियन हेतु जुड़ी शिकायतों सहित।",
    "Certificate for the captured records under Section 63(4) of the Bharatiya Sakshya Adhiniyam, with their SHA-256 hashes.":
        "सुरक्षित अभिलेखों हेतु भारतीय साक्ष्य अधिनियम की धारा 63(4) के अंतर्गत प्रमाण पत्र, उनके SHA-256 हैश सहित।",
    "No bank or UPI identifier in this post": "इस पोस्ट में बैंक या यूपीआई विवरण नहीं",
    "{n} fields to fill or confirm [[ … ]]": "{n} विवरण भरने या पुष्टि करने हैं [[ … ]]", "No blanks left": "कोई रिक्त स्थान नहीं",
    "Preparing the draft…": "प्रारूप तैयार हो रहा है…", "Word": "Word",
    "Edit the text here, then download. Every file is marked “DRAFT — to be reviewed and signed by the authorised officer”, and the export is recorded in the audit log. The legal references are a starting point; confirm them before sending.":
        "यहाँ पाठ संपादित करें, फिर डाउनलोड करें। हर फ़ाइल पर “प्रारूप — अधिकृत अधिकारी द्वारा जाँच एवं हस्ताक्षर हेतु” अंकित होता है, और डाउनलोड ऑडिट लॉग में दर्ज होता है। विधिक संदर्भ केवल आरंभिक हैं; भेजने से पहले उनकी पुष्टि करें।",
    "This came back after a takedown: it is linked to {case}, which was removed. Consider a notice against the account itself, not just the post.":
        "यह हटाने के बाद फिर आया है: यह {case} से जुड़ा है, जिसे हटाया गया था। केवल पोस्ट नहीं, खाते के विरुद्ध सूचना पर विचार करें।",

    # ---- analyze
    "Paste a link to a post, ad, Telegram post or image, or paste the text and a screenshot. You get the verdict and the evidence in a few seconds.":
        "किसी पोस्ट, विज्ञापन, टेलीग्राम पोस्ट या चित्र का लिंक डालें, या पाठ और स्क्रीनशॉट डालें। कुछ सेकंड में परिणाम और साक्ष्य मिलेंगे।",
    "Text or screenshot": "पाठ या स्क्रीनशॉट",
    "https://t.me/channel/123, an OLX/Facebook/Instagram/X post, a forum post or an image link": "https://t.me/channel/123, OLX/Facebook/Instagram/X पोस्ट, फ़ोरम पोस्ट या चित्र का लिंक",
    "Link to check": "जाँचने हेतु लिंक",
    "MuleWatch opens the link like a browser, reads the post text, the link-preview details and any pictures (text in images is read by OCR). Pages that need a login may show little; use the text tab or the Chrome extension for those.":
        "MuleWatch लिंक को ब्राउज़र की तरह खोलता है, पोस्ट का पाठ, लिंक-प्रीव्यू विवरण और चित्र पढ़ता है (चित्र का पाठ OCR से)। लॉगिन वाले पेज कम दिखा सकते हैं; उनके लिए पाठ टैब या क्रोम एक्सटेंशन उपयोग करें।",
    "Paste the post text here (English, Hindi or Hinglish)": "पोस्ट का पाठ यहाँ डालें (अंग्रेज़ी, हिंदी या हिंग्लिश)",
    "Try:": "आज़माएँ:", "sample {n}": "नमूना {n}", "Screenshot or poster": "स्क्रीनशॉट या पोस्टर", "Save as a case": "प्रकरण के रूप में सहेजें",
    "Opening link…": "लिंक खुल रहा है…", "Checking…": "जाँच हो रही है…", "Check post": "पोस्ट जाँचें",
    "This link is already a case:": "यह लिंक पहले से प्रकरण है:", "Read from": "यहाँ से पढ़ा", "{n} images": "{n} चित्र",
    "linked to {n} other posts": "{n} अन्य पोस्ट से जुड़ा", "No strong signs of account or card selling": "खाता या कार्ड बिक्री के मज़बूत संकेत नहीं",
    "This looks like a suspicious financial ad": "यह संदिग्ध वित्तीय विज्ञापन लगता है",
    "Structured data published by the page (schema.org)": "पेज द्वारा प्रकाशित संरचित डेटा (schema.org)", "Page content": "पेज की सामग्री",
    "Page content and link-preview metadata": "पेज की सामग्री और लिंक-प्रीव्यू मेटाडेटा", "Telegram public post preview": "टेलीग्राम सार्वजनिक पोस्ट प्रीव्यू",
    "Direct image link (text read by OCR)": "सीधा चित्र लिंक (पाठ OCR से)",

    # ---- watchlist
    "Known numbers, UPI IDs and links. Any post that mentions one is raised to at least score 88 and alerts immediately, even if the wording looks harmless.":
        "ज्ञात नंबर, यूपीआई आईडी और लिंक। इनमें से किसी का उल्लेख करने वाली पोस्ट का स्कोर कम से कम 88 होता है और तुरंत अलर्ट आता है, भले ही भाषा सामान्य लगे।",
    "Type": "प्रकार", "e.g. +919829041736 or earnfast21@ybl": "जैसे +919829041736 या earnfast21@ybl", "Value": "मान",
    "Note (optional)": "टिप्पणी (वैकल्पिक)", "Note": "टिप्पणी", "Add": "जोड़ें", "Added": "जोड़ा गया", "Remove": "हटाएँ",
    "Watchlist is empty": "निगरानी सूची खाली है", "Add identifiers here, or use the + next to any identifier in a case.": "यहाँ पहचान विवरण जोड़ें, या किसी प्रकरण में विवरण के पास + का उपयोग करें।",

    # ---- network
    "Posts are joined when they share a phone number, UPI ID, Telegram/WhatsApp link or wallet, reuse the same image, or repeat near-identical text. Click any node to trace it.":
        "पोस्ट तब जुड़ती हैं जब उनमें एक ही फ़ोन नंबर, यूपीआई आईडी, टेलीग्राम/व्हाट्सऐप लिंक या वॉलेट हो, वही चित्र दोबारा उपयोग हो, या लगभग समान पाठ हो। किसी बिंदु पर क्लिक कर उसे खोजें।",
    "Showing ring {n}": "गिरोह {n} दिखाया जा रहा है", "Minimum risk score": "न्यूनतम जोखिम स्कोर", "{a} posts, {b} shared identifiers": "{a} पोस्ट, {b} साझा पहचान विवरण",
    "Nothing to draw yet": "अभी दिखाने को कुछ नहीं", "Lower the minimum score or wait for flagged posts.": "न्यूनतम स्कोर घटाएँ या चिह्नित पोस्ट की प्रतीक्षा करें।",
    "{level} risk post": "{level} जोखिम पोस्ट", "same image or text": "समान चित्र या पाठ", "Select a node to see what it connects.": "जुड़ाव देखने हेतु कोई बिंदु चुनें।",
    "Connected identifiers": "जुड़े पहचान विवरण", "Used in {n} posts:": "{n} पोस्ट में उपयोग:",

    # ---- sources and bot
    "Public pages MuleWatch crawls every few seconds. New posts are scored the moment they appear.": "सार्वजनिक पेज जिन्हें MuleWatch हर कुछ सेकंड में जाँचता है। नई पोस्ट आते ही आँकी जाती है।",
    "Address": "पता", "Last crawl": "अंतिम जाँच", "Posts collected": "एकत्र पोस्ट", "Active": "सक्रिय", "Public forum": "सार्वजनिक फ़ोरम",
    "Telegram public channel": "टेलीग्राम सार्वजनिक चैनल", "Single web page, new case when it changes": "एक वेब पेज, बदलने पर नया प्रकरण",
    "waiting": "प्रतीक्षा में", "Source type": "स्रोत प्रकार", "Forum (Charcha-compatible)": "फ़ोरम (चर्चा-संगत)",
    "Single web page (checked every minute)": "एक वेब पेज (हर मिनट जाँच)", "https://… link to an ad, profile or listing": "https://… विज्ञापन, प्रोफ़ाइल या सूची का लिंक",
    "Add source": "स्रोत जोड़ें", "Crawl now": "अभी जाँचें", "Crawled now: {n} new posts.": "जाँच पूरी: {n} नई पोस्ट।", "Alert log": "अलर्ट लॉग",
    "Telegram push is on": "टेलीग्राम सूचना चालू है", "Telegram push off (see Phone alerts above)": "टेलीग्राम सूचना बंद (ऊपर फ़ोन अलर्ट देखें)",
    "sent to Telegram": "टेलीग्राम पर भेजा", "Telegram pending": "टेलीग्राम लंबित", "No alerts yet.": "अभी कोई अलर्ट नहीं।",
    "Detection engine": "पहचान इंजन", "Image text reading (OCR)": "चित्र का पाठ पढ़ना (OCR)", "Tesseract ready": "Tesseract तैयार",
    "Tesseract not installed": "Tesseract इंस्टॉल नहीं", "Text model": "पाठ मॉडल",
    "Character n-gram classifier, trained on {n} labelled examples, retrains on every verdict": "कैरेक्टर n-gram वर्गीकरणकर्ता, {n} लेबल वाले उदाहरणों पर प्रशिक्षित, हर निर्णय पर फिर से सीखता है",
    "AI analyst": "एआई विश्लेषक", "Claude second opinion on manual checks": "हाथ से जाँच पर Claude की दूसरी राय",
    "Off (optional, set ANTHROPIC_API_KEY)": "बंद (वैकल्पिक, ANTHROPIC_API_KEY सेट करें)", "Telegram alerts": "टेलीग्राम अलर्ट",
    "On": "चालू", "Off": "बंद", "Crawler": "क्रॉलर", "Running": "चल रहा है", "Stopped": "रुका हुआ", "{n} errors so far": "अब तक {n} त्रुटियाँ",
    "Citizen reporting bot": "नागरिक रिपोर्टिंग बॉट",
    "Let anyone forward a suspicious message, link or screenshot to a Telegram bot and get an instant verdict. Create a bot with {bf}, put its token in {env} as {var}, and restart.":
        "कोई भी संदिग्ध संदेश, लिंक या स्क्रीनशॉट टेलीग्राम बॉट को भेजकर तुरंत परिणाम पा सकता है। {bf} से बॉट बनाएँ, उसका टोकन {env} में {var} के रूप में डालें, और फिर से शुरू करें।",
    "Online": "ऑनलाइन", "Not connected": "जुड़ा नहीं", "Reports received": "प्राप्त रिपोर्ट", "People reporting": "रिपोर्ट करने वाले लोग",
    "Cases opened": "खोले गए प्रकरण", "view": "देखें", "Last report": "अंतिम रिपोर्ट", "none yet": "अभी नहीं", "Phone alerts": "फ़ोन अलर्ट",
    "On, sent to": "चालू, भेजा जाता है", "linked chat": "जुड़ी चैट", "turn off": "बंद करें",
    "Off. To get Critical alerts on the unit's phone, send this to the bot:": "बंद। इकाई के फ़ोन पर गंभीर अलर्ट पाने हेतु बॉट को यह भेजें:",
    "Off. A supervisor can link the unit's alert chat. For your own case alerts, use": "बंद। इकाई की अलर्ट चैट पर्यवेक्षक जोड़ सकते हैं। अपने प्रकरणों के अलर्ट हेतु उपयोग करें",
    "Reporters get a verdict with safety advice in English and Hindi, and a message when investigators confirm, dismiss or take down what they reported. Their identity isn't shown here.":
        "रिपोर्टर को अंग्रेज़ी और हिंदी में सुरक्षा सलाह सहित परिणाम मिलता है, और अनुसंधानकर्ताओं के पुष्टि, खारिज या हटाने पर संदेश मिलता है। उनकी पहचान यहाँ नहीं दिखाई जाती।",

    # ---- complaints
    "An ad that uses the same phone number, UPI ID or account as a complaint is no longer just suspicious: it is tied to money already lost.":
        "शिकायत वाले फ़ोन नंबर, यूपीआई आईडी या खाते का उपयोग करने वाला विज्ञापन केवल संदिग्ध नहीं रहता: वह पहले से हुई हानि से जुड़ा है।",
    "complaints imported": "शिकायतें आयात हुईं", "matched to ads": "विज्ञापनों से मिलान", "lost in matched complaints": "मिलान वाली शिकायतों में हानि",
    "Cases linked to complaints": "शिकायतों से जुड़े प्रकरण", "All": "सभी", "Risk": "जोखिम", "Complaints": "शिकायतें",
    "No ad matches an imported complaint yet.": "अभी कोई विज्ञापन आयातित शिकायत से नहीं मिला।", "Import complaints": "शिकायतें आयात करें",
    "Sample file": "नमूना फ़ाइल",
    "Upload your unit's NCRP or 1930 complaint export (CSV or Excel). MuleWatch reads the suspect's mobile numbers, UPI IDs, bank accounts and links, and links any ad that uses the same identifiers.":
        "अपनी इकाई का NCRP या 1930 शिकायत निर्यात (CSV या Excel) अपलोड करें। MuleWatch संदिग्ध के मोबाइल नंबर, यूपीआई आईडी, बैंक खाते और लिंक पढ़ता है, और उन्हीं विवरणों वाले विज्ञापनों को जोड़ता है।",
    "Victim names and contact details are never imported.": "पीड़ितों के नाम और संपर्क विवरण कभी आयात नहीं होते।",
    "The rest is stored encrypted on this computer.": "शेष इसी कंप्यूटर पर एन्क्रिप्टेड रखा जाता है।",
    "Reading the file…": "फ़ाइल पढ़ी जा रही है…", "Choose a CSV or .xlsx file": "CSV या .xlsx फ़ाइल चुनें",
    "{n} rows. Check which column is which. Columns left on “Don't import” are ignored.": "{n} पंक्तियाँ। जाँचें कि कौन-सा कॉलम क्या है। “आयात न करें” वाले कॉलम छोड़ दिए जाते हैं।",
    "Column in your file": "आपकी फ़ाइल का कॉलम", "Example": "उदाहरण", "Use as": "किस रूप में", "Don't import": "आयात न करें",
    "Name this import": "इस आयात का नाम", "Cancel": "रद्द करें", "Importing…": "आयात हो रहा है…", "Import {n} complaints": "{n} शिकायतें आयात करें",
    "Map at least one suspect identifier column (mobile, UPI, account, link or IFSC).": "कम से कम एक संदिग्ध पहचान कॉलम चुनें (मोबाइल, यूपीआई, खाता, लिंक या आई.एफ.एस.सी.)।",
    "Imported {n} complaints.": "{n} शिकायतें आयात हुईं।", "{n} skipped: already imported or no suspect identifier.": "{n} छोड़ी गईं: पहले से आयातित या संदिग्ध विवरण नहीं।",
    "{n} cases are now linked to complaints.": "{n} प्रकरण अब शिकायतों से जुड़े हैं।", "Imports": "आयात", "{n} skipped": "{n} छोड़ी गईं",
    "Delete this import": "यह आयात हटाएँ", "Nothing imported yet.": "अभी कुछ आयात नहीं हुआ।",
    "Delete the import “{label}” and all its complaints? This can't be undone.": "आयात “{label}” और उसकी सभी शिकायतें हटाएँ? यह वापस नहीं होगा।",
    "Complaint data is encrypted with the key in {path}. Back that folder up with the database.": "शिकायत डेटा {path} की कुंजी से एन्क्रिप्टेड है। उस फ़ोल्डर का डेटाबेस के साथ बैकअप रखें।",
    "Complaints aren't available": "शिकायतें उपलब्ध नहीं",
    "Complaint / acknowledgement number": "शिकायत / पावती क्रमांक", "Complaint date": "शिकायत दिनांक", "Amount lost (₹)": "हानि राशि (₹)",
    "Fraud category": "धोखाधड़ी श्रेणी", "Suspect mobile number(s)": "संदिग्ध मोबाइल नंबर", "Suspect UPI ID / VPA": "संदिग्ध यूपीआई आईडी / VPA",
    "Suspect bank account number": "संदिग्ध बैंक खाता संख्या", "Suspect IFSC": "संदिग्ध आई.एफ.एस.सी.", "Suspect link / handle / website": "संदिग्ध लिंक / हैंडल / वेबसाइट",

    # ---- map
    "High and Critical cases by suggested district, from the account's IFSC branch and places named in the ad. Approximate: use it to route cases, not as proof of location.":
        "संभावित ज़िले अनुसार उच्च और गंभीर प्रकरण, खाते की आई.एफ.एस.सी. शाखा और विज्ञापन में लिखे स्थानों से। अनुमानित: प्रकरण भेजने हेतु उपयोग करें, स्थान के प्रमाण के रूप में नहीं।",
    "Map of Rajasthan districts with case counts": "प्रकरण संख्या सहित राजस्थान के ज़िलों का मानचित्र", "All districts": "सभी ज़िले",
    "{a} cases · {b} critical · {c} open · {d} complaint links": "{a} प्रकरण · {b} गंभीर · {c} खुले · {d} शिकायत जुड़ाव",
    "Route to:": "भेजें:", "All cases in {d}": "{d} के सभी प्रकरण", "Districts with cases": "प्रकरण वाले ज़िले",
    "No located cases yet": "अभी स्थान सहित प्रकरण नहीं", "Cases get a district when the post names a place or gives an IFSC.": "पोस्ट में स्थान या आई.एफ.एस.सी. होने पर प्रकरण को ज़िला मिलता है।",
    "{n} High/Critical cases have no district signal.": "{n} उच्च/गंभीर प्रकरणों में ज़िले का संकेत नहीं।",
    "Mobile numbers by telecom circle": "टेलीकॉम सर्किल अनुसार मोबाइल नंबर",
    "Where each number's series was first allotted. Ported numbers can be used anywhere, so this is a hint, not a location.":
        "जहाँ हर नंबर की सीरीज़ पहली बार आवंटित हुई थी। पोर्ट किए नंबर कहीं भी उपयोग हो सकते हैं, इसलिए यह केवल संकेत है, स्थान नहीं।",

    # ---- officers, profile
    "Who can sign in and what they can do. Changing a role or disabling an account signs that person out everywhere.":
        "कौन साइन इन कर सकता है और क्या कर सकता है। भूमिका बदलने या खाता बंद करने पर वह व्यक्ति हर जगह से साइन आउट हो जाता है।",
    "Officer": "अधिकारी", "Role": "भूमिका", "Last sign-in": "अंतिम साइन इन", "linked": "जुड़ा", "never": "कभी नहीं",
    "Reset password": "पासवर्ड रीसेट", "Disable": "बंद करें", "Enable": "चालू करें", "No users": "कोई उपयोगकर्ता नहीं",
    "Add an officer": "अधिकारी जोड़ें", "Full name": "पूरा नाम", "Designation": "पद", "Sub-Inspector, Constable, Analyst…": "उप-निरीक्षक, कांस्टेबल, विश्लेषक…",
    "Police station / unit": "पुलिस थाना / इकाई", "Temporary password": "अस्थायी पासवर्ड", "Add officer": "अधिकारी जोड़ें",
    "Reviews cases and records verdicts. Phone and account numbers are partly hidden.": "प्रकरणों की समीक्षा और निर्णय दर्ज करते हैं। फ़ोन और खाता नंबर आंशिक रूप से छिपे रहते हैं।",
    "Also moves cases through the workflow, sees complaint details, drafts notices and exports evidence.": "साथ ही प्रकरण आगे बढ़ाते हैं, शिकायत विवरण देखते हैं, सूचना पत्र तैयार करते हैं और साक्ष्य निकालते हैं।",
    "Also assigns cases, manages officers, reads the audit log and gets the daily brief.": "साथ ही प्रकरण आवंटित करते हैं, अधिकारियों का प्रबंधन करते हैं, ऑडिट लॉग देखते हैं और दैनिक सारांश पाते हैं।",
    "Added {name}. They'll be asked to choose their own password at first sign-in.": "{name} जोड़े गए। पहली बार साइन इन पर उन्हें अपना पासवर्ड चुनना होगा।",
    "Temporary password for {name} (at least 8 characters, letters and numbers):": "{name} के लिए अस्थायी पासवर्ड (कम से कम 8 अक्षर, अक्षर और अंक):",
    "Password reset for {name}. Give it to them in person; they must change it at sign-in.": "{name} का पासवर्ड रीसेट हुआ। उन्हें स्वयं दें; साइन इन पर बदलना होगा।",
    "My account": "मेरा खाता", "Choose your own password to continue.": "आगे बढ़ने हेतु अपना पासवर्ड चुनें।", "Current password": "वर्तमान पासवर्ड",
    "New password": "नया पासवर्ड", "Repeat new password": "नया पासवर्ड दोहराएँ", "Change password": "पासवर्ड बदलें",
    "The new passwords don't match": "नए पासवर्ड मेल नहीं खाते", "Password changed.": "पासवर्ड बदल गया।", "not linked": "नहीं जुड़ा",
    "Get alerts for cases assigned to you on your phone.": "आपको आवंटित प्रकरणों के अलर्ट अपने फ़ोन पर पाएँ।",
    "Get alerts for cases assigned to you on your phone, plus the daily brief every morning.": "आपको आवंटित प्रकरणों के अलर्ट अपने फ़ोन पर पाएँ, साथ ही हर सुबह दैनिक सारांश।",
    "Send {cmd} to {bot} from your Telegram.": "अपने टेलीग्राम से {bot} को {cmd} भेजें।", "the MuleWatch bot": "MuleWatch बॉट",
    "I've sent it": "मैंने भेज दिया", "Link a different Telegram": "दूसरा टेलीग्राम जोड़ें", "Link Telegram": "टेलीग्राम जोड़ें", "Unlink Telegram": "टेलीग्राम हटाएँ",
    "Use {link} to change it.": "बदलने हेतु {link} उपयोग करें।", "User": "उपयोगकर्ता",

    # ---- audit
    "Every sign-in, case view, status change, complaint access, export and evidence capture. Each entry carries the hash of the one before it, so a changed or removed entry breaks the chain from that point.":
        "हर साइन इन, प्रकरण देखना, स्थिति बदलना, शिकायत देखना, निर्यात और साक्ष्य सुरक्षित करना। हर प्रविष्टि में पिछली प्रविष्टि का हैश है, इसलिए बदली या हटाई गई प्रविष्टि से आगे की श्रृंखला टूट जाती है।",
    "Chain intact: {n} entries verified.": "श्रृंखला सही: {n} प्रविष्टियाँ सत्यापित।",
    "Chain broken at entry #{n}. The log was changed outside MuleWatch.": "प्रविष्टि #{n} पर श्रृंखला टूटी है। लॉग MuleWatch के बाहर बदला गया।",
    "Export CSV": "CSV निर्यात", "Everyone": "सभी", "system": "सिस्टम", "All actions": "सभी कार्यवाहियाँ", "Case, e.g. MW-00012": "प्रकरण, जैसे MW-00012",
    "Case": "प्रकरण", "Detail": "विवरण", "No entries match": "कोई प्रविष्टि नहीं मिली", "Newer": "नई", "Older": "पुरानी",
    "Audit log not available": "ऑडिट लॉग उपलब्ध नहीं",

    # ---- brief
    "One page for the SP or SHO: new and critical cases, cases linked to complaints, rings, takedown status, how fast each platform removed content, and where cases are.":
        "एसपी या एसएचओ हेतु एक पृष्ठ: नए और गंभीर प्रकरण, शिकायतों से जुड़े प्रकरण, गिरोह, टेकडाउन की स्थिति, हर प्लेटफ़ॉर्म ने कितनी जल्दी सामग्री हटाई, और प्रकरण कहाँ हैं।",
    "English": "अंग्रेज़ी", "Hindi": "हिंदी", "Period": "अवधि", "Last 24 hours": "पिछले 24 घंटे", "Last 7 days": "पिछले 7 दिन",
    "Last 30 days": "पिछले 30 दिन", "Refresh": "ताज़ा करें", "Open PDF": "PDF खोलें", "Send on Telegram now": "अभी टेलीग्राम पर भेजें",
    "Sent automatically every day at {time} IST in {lang}, for all districts.": "हर दिन {time} IST पर {lang} में, सभी ज़िलों हेतु, स्वतः भेजा जाता है।",
    "Needs a Telegram bot (TELEGRAM_BOT_TOKEN in .env).": "टेलीग्राम बॉट आवश्यक (.env में TELEGRAM_BOT_TOKEN)।",
    "Goes to {n} supervisors.": "{n} पर्यवेक्षकों को जाता है।", "No supervisor has linked Telegram yet:": "अभी किसी पर्यवेक्षक ने टेलीग्राम नहीं जोड़ा:",
    "Change the time with DAILY_BRIEF_TIME in .env.": "समय .env में DAILY_BRIEF_TIME से बदलें।",

    # ---- bulk
    "Check many links at once: links from complaints, patrolling, tips or other units. Each one is fetched and scored like a single post, and flagged ones become cases.":
        "एक साथ कई लिंक जाँचें: शिकायतों, गश्त, सूचनाओं या अन्य इकाइयों से मिले लिंक। हर लिंक को एक पोस्ट की तरह खोला और आँका जाता है, और चिह्नित लिंक प्रकरण बनते हैं।",
    "New list": "नई सूची",
    "Paste the links you collected, one per line. Anything else on the same line (a complaint number, where you found it) is kept as a note.":
        "एकत्र किए लिंक डालें, हर पंक्ति में एक। उसी पंक्ति की अन्य जानकारी (शिकायत क्रमांक, कहाँ मिला) टिप्पणी के रूप में रखी जाती है।",
    "Name this list": "इस सूची का नाम", "e.g. Links from Jhotwara patrol, 17 Oct": "जैसे झोटवाड़ा गश्त के लिंक, 17 अक्टूबर",
    "Check {n} links": "{n} लिंक जाँचें", "Check links": "लिंक जाँचें", "or": "या", "Upload a .txt, .csv or Excel file with links": "लिंक वाली .txt, .csv या Excel फ़ाइल अपलोड करें",
    "Links are opened one at a time with a short pause, the same way as Check a post. Up to 500 links per list. Telegram gets one summary when the list is done.":
        "लिंक एक-एक करके थोड़े अंतराल पर खोले जाते हैं, 'पोस्ट जाँचें' की तरह। हर सूची में 500 तक लिंक। सूची पूरी होने पर टेलीग्राम पर एक सारांश जाता है।",
    "Lists": "सूचियाँ", "No lists yet.": "अभी कोई सूची नहीं।", "All lists": "सभी सूचियाँ", "List not found": "सूची नहीं मिली",
    "Started by {who} · {when} IST": "{who} द्वारा शुरू · {when} IST", "{a} of {b} checked": "{b} में से {a} जाँचे गए",
    "checking…": "जाँच जारी…", "stopped": "रोकी गई", "{n} couldn't be opened": "{n} खुल नहीं सके", "{n} already cases": "{n} पहले से प्रकरण",
    "Stop this list": "यह सूची रोकें", "High and Critical": "उच्च और गंभीर", "All links": "सभी लिंक", "Couldn't open": "खुल नहीं सके",
    "Result": "परिणाम", "already a case": "पहले से प्रकरण", "Nothing High or Critical yet": "अभी कुछ उच्च या गंभीर नहीं", "No links here": "यहाँ कोई लिंक नहीं",
    "queued": "कतार में", "done": "पूर्ण", "existing": "पहले से", "error": "त्रुटि", "cancelled": "रद्द",

    # ---- telecom circles
    "Andhra Pradesh & Telangana": "आंध्र प्रदेश व तेलंगाना", "Assam": "असम", "Bihar & Jharkhand": "बिहार व झारखंड", "Chennai": "चेन्नई",
    "Delhi": "दिल्ली", "Gujarat": "गुजरात", "Haryana": "हरियाणा", "Himachal Pradesh": "हिमाचल प्रदेश", "Jammu & Kashmir": "जम्मू व कश्मीर",
    "Karnataka": "कर्नाटक", "Kerala": "केरल", "Kolkata": "कोलकाता", "Madhya Pradesh & Chhattisgarh": "मध्य प्रदेश व छत्तीसगढ़",
    "Maharashtra & Goa": "महाराष्ट्र व गोवा", "Mumbai": "मुंबई", "North East": "पूर्वोत्तर", "Odisha": "ओडिशा", "Punjab": "पंजाब",
    "Rajasthan": "राजस्थान", "Tamil Nadu": "तमिलनाडु", "UP (East)": "उत्तर प्रदेश (पूर्व)", "UP (West)": "उत्तर प्रदेश (पश्चिम)",
    "West Bengal": "पश्चिम बंगाल", "Uttar Pradesh": "उत्तर प्रदेश", "Bank": "बैंक",
}

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    districts = json.loads((root.parent / "backend/app/refdata/rajasthan_districts.json").read_text(encoding="utf-8"))["districts"]
    out = dict(HI)
    for d in districts:                       # district names come from the backend's district list
        out.setdefault(d["name"], d["hi"])
    (root / "src" / "hi.json").write_text(json.dumps(out, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    print(f"{len(out)} entries -> src/hi.json")
