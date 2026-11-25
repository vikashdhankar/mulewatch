"""Coarse language tag for per-language scores: en, hi (Devanagari), hinglish (romanised Hindi), mixed.

It is a heuristic used to pre-fill the annotation task; annotators can correct it in Label Studio,
and the corrected tag wins.
"""
import re

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_LATIN = re.compile(r"[A-Za-z]")
_WORD = re.compile(r"[A-Za-z]+")

# frequent romanised-Hindi function and domain words; English words that collide are left out
HINGLISH_MARKERS = {
    "hai", "hain", "ho", "hoga", "hogi", "kare", "karo", "karein", "karna", "kar", "ke", "ki", "ka", "ko",
    "se", "me", "mein", "par", "pe", "aur", "ya", "nahi", "nahin", "mat", "bhi", "sirf", "sab", "kuch",
    "chahiye", "chaiye", "milega", "milegi", "milenge", "paisa", "paise", "rupaye", "kamao", "kamaye",
    "ghar", "baithe", "roz", "rozana", "din", "khata", "khaata", "wala", "wale", "wali", "apna", "apne",
    "apni", "aap", "aapka", "aapke", "tum", "hum", "humara", "bhai", "bhaiyo", "jaldi", "abhi", "turant",
    "lena", "dena", "dijiye", "bechna", "becho", "kharido", "kitna", "kitne", "sasta", "kaam", "naya",
    "purana", "zyada", "jyada", "kam", "bas", "toh", "to", "kya", "kyu", "kyun", "hoti", "hota", "rahe",
    "raha", "rahi", "gaya", "gayi", "sath", "saath", "liye", "lie", "wahi", "yahan", "vaha", "jo", "jab",
}
# "to", "me", "ho", "par", "kam", "bas", "jo" collide with English: count them only alongside others
_WEAK = {"to", "me", "ho", "par", "kam", "bas", "jo", "se", "ya", "din"}


def detect_language(text: str) -> str:
    text = text or ""
    dev = len(_DEVANAGARI.findall(text))
    lat = len(_LATIN.findall(text))
    if dev == 0 and lat == 0:
        return "en"
    if dev and lat:
        share = dev / (dev + lat)
        if 0.2 <= share <= 0.8:
            return "mixed"
        if share > 0.8:
            return "hi"
    elif dev:
        return "hi"
    words = [w.lower() for w in _WORD.findall(text)]
    if not words:
        return "en"
    strong = sum(1 for w in words if w in HINGLISH_MARKERS and w not in _WEAK)
    weak = sum(1 for w in words if w in _WEAK)
    score = strong + 0.5 * weak if strong else 0
    return "hinglish" if score >= 2 or (len(words) <= 8 and strong >= 1) else "en"
