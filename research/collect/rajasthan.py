"""Rajasthan place names (English, Hindi and common spellings) and PIN codes, for the discovery geo score."""
import re

# district (or place) -> spellings. Bhiwadi is a town (Khairthal-Tijara district, earlier Alwar) but is
# listed on its own because it is searched on its own.
PLACES: dict[str, list[str]] = {
    "jaipur": ["jaipur", "जयपुर"],
    "jodhpur": ["jodhpur", "जोधपुर"],
    "udaipur": ["udaipur", "उदयपुर"],
    "kota": ["kota", "कोटा"],
    "bikaner": ["bikaner", "बीकानेर"],
    "bharatpur": ["bharatpur", "भरतपुर"],
    "sikar": ["sikar", "सीकर"],
    "jhunjhunu": ["jhunjhunu", "jhunjhunun", "jhunjhunoo", "jhunjunu", "jhunjhnu", "झुंझुनूं", "झुंझुनू", "झुंझुनु",
                  "झुन्झुनू"],
    "ajmer": ["ajmer", "अजमेर"],
    "alwar": ["alwar", "अलवर"],
    "bhilwara": ["bhilwara", "भीलवाड़ा", "भीलवाडा"],
    "sri_ganganagar": ["sri ganganagar", "sriganganagar", "shri ganganagar", "shriganganagar", "ganganagar",
                       "श्रीगंगानगर", "श्री गंगानगर", "गंगानगर"],
    "nagaur": ["nagaur", "nagour", "नागौर"],
    "pali": ["pali", "पाली"],
    "barmer": ["barmer", "बाड़मेर", "बाडमेर"],
    "churu": ["churu", "चूरू", "चुरू"],
    "tonk": ["tonk", "टोंक"],
    "dausa": ["dausa", "दौसा"],
    "chittorgarh": ["chittorgarh", "chittaurgarh", "chittor", "चित्तौड़गढ़", "चित्तौडगढ", "चित्तौड़"],
    "bhiwadi": ["bhiwadi", "भिवाड़ी", "भिवाडी"],
    "rajasthan": ["rajasthan", "राजस्थान"],
}


def _place_rx(term: str) -> re.Pattern:
    body = r"[\s\-]*".join(re.escape(p) for p in term.split())
    if term.isascii():
        return re.compile(r"(?<![a-z0-9])" + body + r"(?![a-z0-9])", re.I)
    return re.compile(r"(?<![ऀ-ॿ])" + body + r"(?![ऀ-ॿ])")


_PLACE_RX = [(d, _place_rx(t)) for d, terms in PLACES.items() for t in terms]

# Rajasthan PIN codes start 30-34. A six-digit number that is an amount (₹300000, 300000 rs, limit 300000)
# is not counted.
_PIN = re.compile(r"(?<![\d.,])(3[0-4]\d)\s?(\d{3})(?![\d.,])")
_AMOUNT_BEFORE = re.compile(r"(₹|\$|rs\.?|inr|usdt|price|rate|amount|limit|balance|salary|turnover|payout|"
                            r"commission|deposit|transaction|txn|@)\s*[:\-]?\s*$", re.I)
_AMOUNT_AFTER = re.compile(r"^\s*(/-|rs\b|₹|k\b|inr|usdt|\+|lakh|lac|rupees|रुपये)", re.I)


def places_in(text: str) -> set[str]:
    """Districts / places mentioned in the text; 'rajasthan_pin' for a Rajasthan PIN code."""
    if not text:
        return set()
    found = {d for d, rx in _PLACE_RX if rx.search(text)}
    for m in _PIN.finditer(text):
        before, after = text[max(0, m.start() - 14):m.start()], text[m.end():m.end() + 8]
        if not _AMOUNT_BEFORE.search(before) and not _AMOUNT_AFTER.search(after):
            found.add("rajasthan_pin")
            break
    return found


# spellings this short also occur inside unrelated words (kotak, pali in napali, tonk ...): in a username they
# count only as a whole word (between _ / digits / capitals), longer ones also inside a run-together name
_MIN_SUBSTRING = 6


def username_places(username: str) -> set[str]:
    """Places named in a channel username: USDT_BUYER_JAIPUR, Usdtsellerrajasthan, kota_kit_99."""
    if not username:
        return set()
    words = {w.lower() for w in re.split(r"[_\d]+|(?<=[a-z])(?=[A-Z])", username) if w}
    flat = username.lower()
    found = set()
    for d, terms in PLACES.items():
        for t in terms:
            if not t.isascii():
                continue
            t = t.replace(" ", "")
            if t in words or (len(t) >= _MIN_SUBSTRING and t in flat):
                found.add(d)
    return found
