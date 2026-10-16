"""Suggest which Rajasthan district (and so which district cyber police station) should handle a case.

Signals, strongest first:
  1. IFSC branch district of an account in the post (where the account was opened)
  2. Place names in the post (district names, towns and localities, in English and Hindi, plus short
     forms seen in seller handles such as "_jpr")
  3. Telecom circle of the mobile number series, only if refdata/phone_series.json has been filled in.
     Ported numbers can be used anywhere, so this is only ever a weak hint.

The result is a suggestion for routing, always labelled approximate."""
import json
import re
from collections import Counter
from pathlib import Path

from .banks import ifsc_info

REF = Path(__file__).parent / "refdata"
_D = json.loads((REF / "rajasthan_districts.json").read_text(encoding="utf-8"))["districts"]
DISTRICTS = {d["name"]: d for d in _D}
_SERIES = json.loads((REF / "phone_series.json").read_text(encoding="utf-8")).get("series", {})

_ALIASES: dict[str, str] = {}
for d in _D:
    for a in [d["name"], d["hi"], *d["aliases"]]:
        _ALIASES[a.lower()] = d["name"]
# match longer names first ("sawai madhopur" before "madhopur")
_PATTERN = re.compile("|".join(
    (r"(?<![a-z])" + re.escape(a) + r"(?![a-z])") if a.isascii() else re.escape(a)
    for a in sorted(_ALIASES, key=len, reverse=True)), re.I)


def district_for_name(name: str) -> str:
    """Normalise a district/city name from another source (IFSC data, complaint export)."""
    n = (name or "").strip().lower()
    if not n:
        return ""
    if n in _ALIASES:
        return _ALIASES[n]
    m = _PATTERN.search(n)
    return _ALIASES[m.group(0).lower()] if m else ""


def place_mentions(text: str) -> list[str]:
    found = []
    for m in _PATTERN.finditer(text or ""):
        found.append(_ALIASES[m.group(0).lower()])
    # handles like kitwala_jpr: underscores aren't word boundaries for the pattern above
    for tok in re.findall(r"[_\-.]([a-z]{3,})\b", (text or "").lower()):
        if tok in _ALIASES:
            found.append(_ALIASES[tok])
    return found


def suggest(post) -> dict:
    ents = post.entities or {}
    votes: Counter = Counter()
    signals = []
    for code in ents.get("ifsc", []):
        info = ifsc_info(code)
        if info["found"]:
            dist = district_for_name(info["district"]) or district_for_name(info["city"])
            in_raj = info["state"].lower().startswith("raj")
            signals.append({"kind": "ifsc", "value": code,
                            "detail": f"{info['bank']} branch in {info['district'] or info['city']}, {info['state']}",
                            "district": dist if in_raj else "", "state": info["state"]})
            if dist and in_raj:
                votes[dist] += 3
    text = (post.text or "") + "\n" + (post.ocr_text or "") + "\n" + (post.author or "")
    for name, n in Counter(place_mentions(text)).items():
        votes[name] += 2 * min(n, 2)
        signals.append({"kind": "place", "value": name, "detail": f"Place named in the post ({DISTRICTS[name]['hi']})",
                        "district": name, "state": "Rajasthan"})
    if _SERIES:
        for ph in ents.get("phone", []):
            d = ph[-10:]
            circle = _SERIES.get(d[:5]) or _SERIES.get(d[:4])
            if circle:
                signals.append({"kind": "phone", "value": ph, "detail": f"Number series of {circle} circle "
                                                                        "(weak: ported numbers move)",
                                "district": "", "state": circle})
    if not votes:
        out_of_state = sorted({s["state"] for s in signals if s["kind"] == "ifsc" and not s["district"] and s["state"]})
        return {"district": "", "police_station": "", "confidence": "none", "signals": signals,
                "note": ("Account branch outside Rajasthan: " + ", ".join(out_of_state) + ". Route through I4C / that "
                         "state's cyber cell.") if out_of_state else "No location signal in this post."}
    best, score = votes.most_common(1)[0]
    total = sum(votes.values())
    confidence = "medium" if score >= 3 and score / total >= 0.6 else "low"
    return {"district": best, "district_hi": DISTRICTS[best]["hi"],
            "police_station": f"Cyber Police Station, {best}", "confidence": confidence,
            "votes": dict(votes), "signals": signals,
            "note": "Approximate: based on where the account branch is and places named in the post."}


def district_points() -> list[dict]:
    return [{"name": d["name"], "hi": d["hi"], "lat": d["lat"], "lon": d["lon"]} for d in _D]
