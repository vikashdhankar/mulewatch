"""Watcher settings from watcher.yaml (or the file in WATCHER_CONFIG)."""
import copy
import os
from pathlib import Path

import yaml

from .research import ROOT

DEFAULT = Path(__file__).with_name("watcher.yaml")
FRAUD_CATEGORIES = ["payout_mule", "account_sale", "usdt_p2p", "crypto_investment_scam", "task_job_scam"]
CATEGORIES = FRAUD_CATEGORIES + ["legit_finance", "unrelated"]


def load(path: str | os.PathLike | None = None, overrides: dict | None = None) -> dict:
    cfg = yaml.safe_load(Path(path or os.getenv("WATCHER_CONFIG") or DEFAULT).read_text(encoding="utf-8")) or {}
    if overrides:
        cfg = merge(cfg, overrides)
    sev = cfg["risk"]["severity"]
    missing = [c for c in CATEGORIES if c not in sev]
    if missing:
        raise ValueError(f"risk.severity has no value for {missing}")
    t = cfg["risk"]["thresholds"]
    if not 0 < t["medium"] < t["high"] <= 100:
        raise ValueError("risk.thresholds need 0 < medium < high <= 100")
    return cfg


def merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def path(rel: str) -> Path:
    """A path from the config: relative paths are relative to the repository root."""
    p = Path(rel)
    return p if p.is_absolute() else ROOT / p
