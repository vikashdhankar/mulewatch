"""List interface strings that have no Hindi translation yet:  python3 scripts/check_i18n.py
Finds literal t("..."), tr("...") and <T k="..."> keys in src/. Keys built at run time (statuses, districts...)
are not seen here; add those to hi_source.py by hand."""
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
hi = json.loads((root / "src" / "hi.json").read_text(encoding="utf-8"))
rx = re.compile(r'''(?:\bt|\btr)\(\s*"((?:[^"\\]|\\.)+)"|<T\s+k="([^"]+)"''')
missing = {}
for f in sorted((root / "src").rglob("*.jsx")) + sorted((root / "src").rglob("*.js")):
    for m in rx.finditer(f.read_text(encoding="utf-8")):
        k = (m.group(1) or m.group(2)).replace('\\"', '"')
        if k not in hi:
            missing.setdefault(k, f.name)
for k, f in missing.items():
    print(f"{f}: {k}")
print(f"{len(missing)} missing")
