import json
import os
from pathlib import Path
from typing import Iterable, Iterator


def read_jsonl(path) -> list[dict]:
    return list(iter_jsonl(path))


def iter_jsonl(path) -> Iterator[dict]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_jsonl(path, rows: Iterable[dict], append: bool = False, private: bool = False) -> int:
    """Write rows as JSON lines. private=True makes the file readable by the owner only (raw data)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "a" if append else "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    if private:
        os.chmod(path, 0o600)
    return n


def load_env() -> None:
    """Load research/.env if python-dotenv is installed (it is in requirements.txt)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
