"""Build a model from its config file, and load split files as (texts, labels, langs)."""
from pathlib import Path

import yaml

from common.io import read_jsonl
from common.text import model_input


def load_config(path) -> dict:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    for key in ("name", "type"):
        if key not in cfg:
            raise ValueError(f"{path}: missing '{key}'")
    cfg.setdefault("params", {})
    cfg.setdefault("cost", {})
    cfg.setdefault("seeds", [13])
    return cfg


def build(cfg: dict, seed: int = 13, output_dir: str = "checkpoints"):
    t = cfg["type"]
    if t == "tfidf_lr":
        from models.tfidf_lr import TfidfLR
        return TfidfLR(cfg["params"], seed)
    if t == "hf":
        from models.hf_finetune import HFClassifier
        return HFClassifier(cfg["params"], seed, output_dir=f"{output_dir}/{cfg['name']}_s{seed}")
    if t == "llm":
        from models.llm_prompt import LLMClassifier
        return LLMClassifier(cfg["params"], seed)
    raise ValueError(f"unknown model type {t!r}")


def load_split(split_dir) -> dict[str, list[dict]]:
    """{part: examples} for every <part>.jsonl in the split directory."""
    split_dir = Path(split_dir)
    parts = {p.stem: read_jsonl(p) for p in sorted(split_dir.glob("*.jsonl"))}
    if "train" not in parts:
        raise SystemExit(f"{split_dir}/train.jsonl not found; run `python -m data.splits` first")
    return parts


def xy(examples: list[dict]) -> tuple[list[str], list[str], list[str]]:
    return ([model_input(e) for e in examples], [e["label"] for e in examples], [e.get("lang", "") for e in examples])
