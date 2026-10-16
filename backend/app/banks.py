"""Which bank or payment app a case's identifiers point to.

* IFSC  -> bank (first four letters) and branch, city, district, state from the bundled IFSC list
          (Razorpay's open IFSC dataset; refresh with `python -m app.banks --update`).
* UPI ID -> the app and its sponsor (PSP) bank from refdata/upi_handles.json. The PSP bank maps the UPI ID
          to the real account, so that's where to ask which account (at any bank) it is linked to.
* Account number alone doesn't reveal the bank; it is grouped with an IFSC from the same post if there is one."""
import csv
import gzip
import json
import sqlite3
import sys
import threading
from pathlib import Path

from .config import DATA_DIR

REF = Path(__file__).parent / "refdata"
IFSC_GZ = REF / "ifsc_branches.csv.gz"
IFSC_DB = DATA_DIR / "ifsc.sqlite"
IFSC_SOURCE = "https://github.com/razorpay/ifsc/releases/latest/download/IFSC.csv"

BANK_NAMES: dict[str, str] = json.loads((REF / "banknames.json").read_text(encoding="utf-8"))
_UPI = json.loads((REF / "upi_handles.json").read_text(encoding="utf-8"))
UPI_HANDLES = {k: v for k, v in _UPI.items() if not k.startswith("_")}
_lock = threading.Lock()


def _db():
    with _lock:
        if not IFSC_DB.exists() or IFSC_DB.stat().st_mtime < IFSC_GZ.stat().st_mtime:
            tmp = IFSC_DB.with_suffix(".tmp")
            tmp.unlink(missing_ok=True)
            con = sqlite3.connect(tmp)
            con.execute("CREATE TABLE ifsc (ifsc TEXT PRIMARY KEY, branch TEXT, city TEXT, district TEXT, state TEXT)")
            with gzip.open(IFSC_GZ, "rt", encoding="utf-8", newline="") as f:
                rows = csv.reader(f)
                next(rows)
                con.executemany("INSERT OR REPLACE INTO ifsc VALUES (?,?,?,?,?)", rows)
            con.commit()
            con.close()
            tmp.replace(IFSC_DB)
    return sqlite3.connect(IFSC_DB)


def ifsc_info(code: str) -> dict:
    code = (code or "").strip().upper()
    bank = code[:4]
    out = {"ifsc": code, "bank_code": bank, "bank": BANK_NAMES.get(bank, ""), "branch": "", "city": "",
           "district": "", "state": "", "found": False}
    try:
        con = _db()
        row = con.execute("SELECT branch, city, district, state FROM ifsc WHERE ifsc = ?", (code,)).fetchone()
        con.close()
    except (sqlite3.Error, OSError):
        row = None
    if row:
        out.update(branch=row[0].title(), city=row[1].title(), district=row[2].title(), state=row[3].title(), found=True)
    return out


def upi_info(vpa: str) -> dict:
    handle = vpa.split("@", 1)[1].lower() if "@" in (vpa or "") else ""
    app, bank = UPI_HANDLES.get(handle, ["", ""])
    return {"vpa": vpa, "handle": handle, "app": app, "bank_code": bank, "bank": BANK_NAMES.get(bank, "")}


def routes(post) -> list[dict]:
    """Group a case's financial identifiers by the bank that can act on them."""
    ents = post.entities or {}
    groups: dict[str, dict] = {}

    def add(code, name, item):
        key = code or "?"
        g = groups.setdefault(key, {"bank_code": code, "bank": name or "Bank not identified", "items": []})
        if item not in g["items"]:
            g["items"].append(item)

    ifscs = [ifsc_info(c) for c in ents.get("ifsc", [])]
    for i in ifscs:
        where = ", ".join(x for x in (i["branch"], i["district"], i["state"]) if x)
        add(i["bank_code"], i["bank"], {"kind": "ifsc", "value": i["ifsc"],
                                        "detail": f"Branch: {where}" if where else "IFSC not in the bundled list"})
    for a in ents.get("bank_account", []):
        if len(ifscs) == 1:
            i = ifscs[0]
            add(i["bank_code"], i["bank"], {"kind": "account", "value": a, "detail": f"Posted with IFSC {i['ifsc']}"})
        else:
            add("", "", {"kind": "account", "value": a,
                         "detail": "No single IFSC in the post: ask NPCI/I4C or check the complaint data for the bank"})
    for v in ents.get("upi", []):
        u = upi_info(v)
        detail = (f"{u['app']} UPI ID — {u['bank']} is the sponsor bank and can say which account it is linked to"
                  if u["bank"] else f"Unknown UPI handle @{u['handle']}: check NPCI's list of payment apps")
        add(u["bank_code"], u["bank"], {"kind": "upi", "value": v, "detail": detail})
    out = sorted(groups.values(), key=lambda g: (g["bank_code"] == "", g["bank"]))
    return out


def update_dataset(url: str = IFSC_SOURCE) -> int:
    """Download the latest IFSC list and rebuild the bundled compact copy."""
    import io
    import requests
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    rows = csv.DictReader(io.StringIO(r.content.decode("utf-8")))
    n = 0
    with gzip.open(IFSC_GZ, "wt", encoding="utf-8", compresslevel=9, newline="") as f:
        w = csv.writer(f)
        w.writerow(["IFSC", "BRANCH", "CITY", "DISTRICT", "STATE"])
        for row in rows:
            w.writerow([row["IFSC"], row["BRANCH"], row["CITY"], row["DISTRICT"], row["STATE"]])
            n += 1
    IFSC_DB.unlink(missing_ok=True)
    return n


if __name__ == "__main__":
    if "--update" in sys.argv:
        print(f"Updated: {update_dataset()} branches")
    elif len(sys.argv) > 1:
        for a in sys.argv[1:]:
            print(upi_info(a) if "@" in a else ifsc_info(a))
    else:
        print("python -m app.banks --update | <IFSC> | <upi@handle>")
