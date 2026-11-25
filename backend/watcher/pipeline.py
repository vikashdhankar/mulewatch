"""The per-post pipeline as pure functions: redact -> classify -> risk score -> route.

Nothing here reads the database, the network or the clock: history (identifiers seen before, a channel's
posting times) comes in through a `History` object, so every step can be tested on its own."""
import html
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Protocol

from common.text import model_input

from .config import FRAUD_CATEGORIES

# identifiers that link posts to a seller (e-mails, links and ID numbers are masked but not linked on)
LINK_TYPES = ("PHONE", "UPI", "ACCOUNT", "CARD", "HANDLE")
NOT_FRAUD = ("legit_finance", "unrelated")

CATEGORY_LABEL = {
    "payout_mule": "Payout Mule", "account_sale": "Account Sale", "usdt_p2p": "USDT P2P",
    "crypto_investment_scam": "Crypto Investment Scam", "task_job_scam": "Task/Job Scam",
    "legit_finance": "Legit Finance", "unrelated": "Unrelated",
}


# ----------------------------------------------------------------------------- a. redact

@dataclass(frozen=True)
class Redacted:
    text: str
    ocr_text: str
    keys: tuple[str, ...]           # "<TYPE>:<keyed hash>", distinct, sorted: the linkable identifiers

    @property
    def model_text(self) -> str:
        return model_input({"text": self.text, "ocr_text": self.ocr_text})


def redact(post: dict, redactor) -> Redacted:
    """Mask identifiers (research/pii/redact.py) and keep keyed hashes of the linkable ones. The channel's own
    @handle is not an identifier of a seller, so it is left out of the keys."""
    r = redactor.redact_post(post)
    own = redactor.hash("HANDLE", (post.get("channel") or "").lower())
    keys = {f"{e['type']}:{e['hash']}" for e in r["entities"]
            if e["type"] in LINK_TYPES and not (e.get("meta") or {}).get("partial")
            and not (e["type"] == "HANDLE" and e["hash"] == own)}
    return Redacted(r["text"], r["ocr_text"], tuple(sorted(keys)))


# ----------------------------------------------------------------------------- b. classify

@dataclass(frozen=True)
class Classification:
    category: str
    p: float                        # probability that the post is fraud (any fraud category), final
    p_model: float                  # the same from the model alone
    probs: dict                     # per category, from the model
    cues: tuple[str, ...]           # words that pushed the model towards the category
    model: str
    llm: dict | None = None         # {"category": ..., "p": ...} when the LLM was asked, {"error": ...} if it failed


class Model(Protocol):
    name: str

    def predict(self, text: str) -> tuple[dict, list[str]]: ...           # ({category: prob}, cue words)


def classify(text: str, model: Model, llm_cfg: dict, llm: Callable[[str], str | None] | None = None) -> Classification:
    """Category + probability + cue words. The LLM is asked for a second opinion only when the model is unsure
    (gray_low <= p <= gray_high); its answer moves p by `weight` and may name the fraud type."""
    probs, cues = model.predict(text)
    p_model = sum(probs.get(c, 0.0) for c in FRAUD_CATEGORIES)
    top_fraud = max(FRAUD_CATEGORIES, key=lambda c: probs.get(c, 0.0))
    top_other = max(NOT_FRAUD, key=lambda c: probs.get(c, 0.0))
    p, info = p_model, None
    if llm is not None and llm_cfg.get("enabled", True) and llm_cfg["gray_low"] <= p_model <= llm_cfg["gray_high"]:
        answer = llm(text)
        if answer is None:
            info = {"error": "no valid answer"}
        else:
            p_llm = llm_cfg["p_fraud"] if answer in FRAUD_CATEGORIES else llm_cfg["p_not_fraud"]
            p = (1 - llm_cfg["weight"]) * p_model + llm_cfg["weight"] * p_llm
            info = {"category": answer, "p": p_llm}
            if answer in FRAUD_CATEGORIES:
                top_fraud = answer
    category = top_fraud if p >= 0.5 else top_other
    return Classification(category, round(p, 4), round(p_model, 4), {k: round(v, 4) for k, v in probs.items()},
                          tuple(cues), model.name, info)


# ----------------------------------------------------------------------------- c. risk score

class History(Protocol):
    def known(self, keys: list[str]) -> set[str]: ...                       # keys seen in any earlier post
    def channels_of(self, keys: list[str]) -> dict[str, set[str]]: ...     # key -> channels it was seen in
    def channel_times(self, channel: str, since: datetime, until: datetime) -> list[datetime]: ...
    def channel_first_seen(self, channel: str) -> datetime | None: ...


@dataclass(frozen=True)
class Signals:
    new_keys: tuple[str, ...] = ()
    places: tuple[str, ...] = ()            # Rajasthan districts named in the post
    burst: bool = False
    last_hour: int = 0                      # channel's posts in the hour up to this one (this one included)
    mean_hourly: float = 0.0                # its hourly mean over the last 7 days (or since first seen)
    cross_channel: tuple[str, ...] = ()     # keys seen in >= cross_channel_min channels, this one included
    linked: int = 0                         # keys of this post already seen in other posts
    max_channels: int = 0


def burst_check(times: list[datetime], now: datetime, first_seen: datetime | None, factor: float,
                min_posts: int) -> tuple[bool, int, float]:
    """Is the channel posting more than `factor` times its usual hourly rate? `times` are its earlier posts in
    the last 7 days. With less than 7 days of history the mean is taken over the time it has been watched, so a
    channel isn't flagged just for being new."""
    week = now - timedelta(days=7)
    earlier = [t for t in times if week <= t <= now]
    last_hour = 1 + sum(1 for t in earlier if t > now - timedelta(hours=1))
    start = max(week, min([first_seen] + earlier) if first_seen else min(earlier, default=now))
    hours = max(1.0, (now - start).total_seconds() / 3600)
    mean = (len(earlier) + 1) / hours
    return last_hour >= min_posts and last_hour > factor * mean, last_hour, round(mean, 3)


def compute_signals(keys: tuple[str, ...], channel: str, posted_at: datetime, places: list[str],
                    history: History, risk_cfg: dict) -> Signals:
    keys = list(keys)
    known = history.known(keys) if keys else set()
    chans = history.channels_of(keys) if keys else {}
    counts = {k: len(chans.get(k, set()) | {channel}) for k in keys}
    cross = tuple(k for k in keys if counts[k] >= risk_cfg["cross_channel_min"])
    times = history.channel_times(channel, posted_at - timedelta(days=7), posted_at)
    burst, last_hour, mean = burst_check(times, posted_at, history.channel_first_seen(channel),
                                         risk_cfg["burst_factor"], risk_cfg["burst_min_posts"])
    return Signals(new_keys=tuple(k for k in keys if k not in known), places=tuple(dict.fromkeys(places)),
                   burst=burst, last_hour=last_hour, mean_hourly=mean, cross_channel=cross,
                   linked=sum(1 for k in keys if k in known), max_channels=max(counts.values(), default=0))


def risk_score(cls: Classification, sig: Signals, risk_cfg: dict) -> tuple[float, dict]:
    """0-100 = w_model * p * severity(category) + new identifier + Rajasthan place + burst + cross-channel."""
    w = risk_cfg["weights"]
    parts = {
        "model": w["model"] * cls.p * float(risk_cfg["severity"][cls.category]),
        "new_identifier": w["new_identifier"] if sig.new_keys else 0,
        "rajasthan_place": w["rajasthan_place"] if sig.places else 0,
        "burst": w["burst"] if sig.burst else 0,
        "cross_channel": w["cross_channel"] if sig.cross_channel else 0,
    }
    parts = {k: round(v, 2) for k, v in parts.items()}
    return round(min(100.0, max(0.0, sum(parts.values()))), 1), parts


# ----------------------------------------------------------------------------- d. route

def route(score: float, thresholds: dict) -> str:
    if score >= thresholds["high"]:
        return "HIGH"
    if score >= thresholds["medium"]:
        return "MEDIUM"
    return "LOW"


def case_level(route_: str, score: float) -> str:
    """The command center's level names: a HIGH alert at 80+ is Critical, as everywhere else in the app."""
    return {"HIGH": "Critical" if score >= 80 else "High", "MEDIUM": "Medium"}.get(route_, "Low")


# ----------------------------------------------------------------------------- explanation

def reasons(cls: Classification, sig: Signals, parts: dict) -> list[str]:
    """Human-readable lines for the case page. No identifier values, only counts."""
    label = CATEGORY_LABEL.get(cls.category, cls.category)
    out = [f"Telegram watcher: {label}, fraud probability {cls.p:.2f}"
           + (f" (model {cls.p_model:.2f}, LLM said {CATEGORY_LABEL.get(cls.llm['category'], cls.llm['category'])})"
              if cls.llm and "category" in cls.llm else "") + f" → +{parts['model']:.0f}"]
    if cls.cues:
        out.append("Cue words: " + ", ".join(cls.cues))
    if sig.new_keys:
        out.append(f"{len(sig.new_keys)} identifier(s) never seen before → +{parts['new_identifier']:.0f}")
    if sig.places:
        out.append("Rajasthan place named: " + ", ".join(sig.places) + f" → +{parts['rajasthan_place']:.0f}")
    if sig.burst:
        out.append(f"Channel burst: {sig.last_hour} posts in the last hour vs {sig.mean_hourly:.2f}/h usual"
                   f" → +{parts['burst']:.0f}")
    if sig.cross_channel:
        out.append(f"Identifier seen in {sig.max_channels} channels → +{parts['cross_channel']:.0f}")
    return out


@dataclass
class AlertView:
    masked_text: str
    category: str
    score: float
    channel: str
    link: str
    district: str = ""
    linked: int = 0
    case_url: str = ""
    cues: list = field(default_factory=list)


def format_alert(a: AlertView, max_chars: int = 280) -> str:
    """Telegram (HTML) message for the duty officer: masked text only, never a phone number or UPI ID."""
    e = lambda s: html.escape(str(s), quote=False)  # noqa: E731
    text = a.masked_text.strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "…"
    lines = [f"🚨 <b>MuleWatch Telegram alert</b> — score {a.score:.0f}",
             f"<b>{e(CATEGORY_LABEL.get(a.category, a.category))}</b> in @{e(a.channel)}",
             f"District: {e(a.district) if a.district else 'not identified'}",
             f"Linked identifiers: {a.linked}", "", f"<i>{e(text)}</i>"]
    if a.cues:
        lines.append("Cues: " + e(", ".join(a.cues[:5])))
    lines += ["", f"🔗 {e(a.link)}"]
    if a.case_url:
        lines.append(f"🔎 {e(a.case_url)}")
    return "\n".join(lines)
