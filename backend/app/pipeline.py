"""Ingestion pipeline: OCR -> extraction -> scoring -> coordination -> alerts."""
import hashlib
from collections import defaultdict
from datetime import datetime

from . import complaints, evidence, jurisdiction, llm, recruiter
from .alerts import maybe_alert, notify
from .config import MEDIA_DIR, level_for
from .coordination import compute as compute_coordination
from .coordination import ring_boost
from .db import KeywordStat, Post, WatchItem
from .extract import detect_language
from .imaging import ocr_image, phash
from .ml import retrain
from .scoring import analyze, categorize, finalize


def keyword_stats(session) -> dict:
    return {k.term: (k.confirmed, k.false_positive) for k in session.query(KeywordStat).all()}


def _evidence_hash(post: Post) -> str:
    h = hashlib.sha256()
    for part in (post.platform, post.author, post.url, post.text, post.ocr_text,
                 post.posted_at.isoformat() if post.posted_at else ""):
        h.update((part or "").encode("utf-8") + b"\x00")
    if post.image_path:
        try:
            h.update((MEDIA_DIR / post.image_path).read_bytes())
        except OSError:
            pass
    return h.hexdigest()


def _apply_analysis(post: Post, a: dict):
    post.matches = a["matches"]
    post.entities = a["entities"]
    post.reasons = a["reasons"]
    post.scores = a["scores"] | {"groups": a["groups"], "entity_spans": a["entity_spans"]}


def ingest(session, *, text: str = "", platform: str = "unknown", author: str = "", url: str = "",
           image_path: str = "", posted_at: datetime | None = None, source: str = "manual",
           ocr_hint: str = "", use_llm: bool = False, train_label: int | None = None,
           recompute: bool = True, extra_images: list[str] | None = None, html: str = "") -> Post:
    ocr_text, ph = "", ""
    if image_path:
        full = str(MEDIA_DIR / image_path)
        ocr_text = ocr_image(full) or ocr_hint
        ph = phash(full)
    for extra in extra_images or []:           # more images from the same post (e.g. a fetched page)
        more = ocr_image(str(MEDIA_DIR / extra))
        if more:
            ocr_text = (ocr_text + "\n---\n" + more).strip()

    llm_result = llm.assess(text + ("\n[OCR] " + ocr_text if ocr_text else ""),
                            str(MEDIA_DIR / image_path) if image_path else None) if use_llm and llm.enabled() else None
    a = analyze(text, ocr_text, keyword_stats(session),
                llm_result if llm_result and "score" in llm_result else None, citizen=source == "citizen")

    post = Post(text=text, platform=platform, author=author, url=url, image_path=image_path,
                ocr_text=ocr_text, image_phash=ph, source=source, train_label=train_label,
                posted_at=posted_at or datetime.utcnow(), language=detect_language(text + " " + ocr_text),
                llm=llm_result or {})
    _apply_analysis(post, a)
    post.risk_score = a["base_score"]
    post.risk_level = level_for(post.risk_score)
    post.category = categorize(set(a["groups"]), a["entities"], post.risk_score)
    post.evidence_hash = _evidence_hash(post)
    post.status = "NEW"
    post.jurisdiction = jurisdiction.suggest(post)
    session.add(post)
    session.flush()
    if source != "preview":
        evidence.capture(session, post, html)
    if recompute:
        recompute_all(session, alert=True)
    return post


def watch_hits(post: Post, watch: list[WatchItem]) -> list[str]:
    if not watch:
        return []
    ents = post.entities or {}
    values = {str(v).lower() for vs in ents.values() if isinstance(vs, list) for v in vs}
    blob = ((post.text or "") + " " + (post.ocr_text or "")).lower()
    hits = []
    for w in watch:
        v = w.value.lower().strip()
        if v in values or (len(v) >= 4 and v in blob) or (w.kind == "phone" and any(v[-10:] in x for x in values)):
            hits.append(f"{w.kind} {w.value}")
    return hits


def recompute_all(session, alert: bool = True, push: bool = True):
    """Re-run coordination over the whole corpus and refresh final scores, complaint links, recruiter
    priority and reappearance after takedown."""
    posts = session.query(Post).all()
    if not posts:
        return
    coord = compute_coordination(posts)
    clusters = defaultdict(list)
    for p in posts:
        root = coord[p.id]["cluster"]
        if root is not None:
            clusters[root].append(p)
    watch = session.query(WatchItem).all()
    gained = {p.id for p in complaints.match_posts(session, posts)}
    removed = {p.id: p.removed_at for p in posts if p.removed_at}
    reappeared = []

    for p in posts:
        prev = p.risk_level if p.id and p.risk_score is not None and p.scores.get("final_done") else None
        root = coord[p.id]["cluster"]
        members = clusters.get(root, [p]) if root is not None else [p]
        size = len(members)
        base = float(p.scores.get("base", p.risk_score or 0))
        max_base = max(float(m.scores.get("base", 0)) for m in members)
        platforms = len({m.platform for m in members})
        boost = ring_boost(base, size, max_base, platforms)
        hits = watch_hits(p, watch)

        p.cluster_id = root if size >= 2 else None
        p.cluster_size = size
        rel = coord[p.id]["related"]
        p.related = sorted(({"id": o, "why": sorted(w)} for o, w in rel.items()),
                           key=lambda r: (-len(r["why"]), r["id"]))[:25]
        # a post linked to content that was taken down, and seen after the takedown: it came back
        if p.repost_of is None and p.id not in removed and p.source != "preview":
            back = [o for o in rel if o in removed and (p.ingested_at or datetime.utcnow()) > removed[o]]
            if back:
                p.repost_of = min(back)
                reappeared.append(p)
        final = finalize(base, boost, hits)
        if p.complaint_count:
            final = max(final, 90.0)
        if p.repost_of is not None:
            final = max(final, 85.0)
        p.risk_score = final
        p.risk_level = level_for(final)
        p.category = categorize(set(p.scores.get("groups", [])), p.entities or {}, final)
        p.scores = dict(p.scores, ring_boost=boost, watchlist=hits, final=final, final_done=True,
                        ring_platforms=platforms, complaints=complaints.describe(p),
                        repost=(f"Reappeared after takedown of MW-{p.repost_of:05d}" if p.repost_of else ""))
        if alert:
            maybe_alert(session, p, hits, previous_level=prev, push_allowed=push)

    scores = recruiter.compute(posts)
    for p in posts:
        p.recruiter_score, p.recruiter_reasons = scores.get(p.id, (0.0, []))

    if alert:
        for p in posts:
            if p.id in gained and p.source != "preview":
                notify(session, p, complaints.describe(p) + ". Open the case to see the complaints.", push=push)
        for p in reappeared:
            why = next((r["why"] for r in p.related or [] if r["id"] == p.repost_of), [])
            notify(session, p, f"Reappeared after takedown: linked to MW-{p.repost_of:05d} (removed) by "
                               + (", ".join(why[:2]) or "shared identifiers"), push=push)
    session.commit()
    evidence.queue_screenshots(posts)


def rescore_all(session, alert: bool = False):
    """Re-run text analysis for every post (OCR & LLM results reused): after feedback/retraining, and at
    startup so cases captured by an older version are scored with the current rules."""
    stats = keyword_stats(session)
    for p in session.query(Post).all():
        p.jurisdiction = jurisdiction.suggest(p)
        llm_res = p.llm if p.llm and "score" in p.llm else None
        a = analyze(p.text or "", p.ocr_text or "", stats, llm_res, citizen=p.source == "citizen")
        extra = [r for r in (p.reasons or []) if r.startswith(("Posted as a comment", "Citizen report:"))]
        _apply_analysis(p, a)
        p.reasons = p.reasons + [r for r in extra if r not in p.reasons]
        p.scores = dict(p.scores, base=a["base_score"], final_done=True)
    session.flush()
    recompute_all(session, alert=alert)


def base_training_set() -> list[tuple[str, int]]:
    import json
    from .config import BASE_DIR
    path = BASE_DIR / "training" / "training_data.jsonl"
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [(r["text"], int(r["label"])) for r in rows]


def training_samples(session) -> list[tuple[str, int]]:
    out = base_training_set()
    for p in session.query(Post).all():
        y = None
        if p.label == "confirmed":
            y = 1
        elif p.label == "false_positive":
            y = 0
        elif p.train_label is not None:
            y = p.train_label
        if y is not None:
            out.append(((p.text or "") + " " + (p.ocr_text or ""), y))
    return out


def apply_feedback(session, post: Post, label: str):
    """Investigator verdict -> per-term precision stats + classifier retrain + rescore."""
    old = post.label
    post.label = label
    terms = {m["term"] for m in post.matches or []}
    for t in terms:
        ks = session.get(KeywordStat, t) or KeywordStat(term=t, confirmed=0, false_positive=0)
        if old == "confirmed":
            ks.confirmed = max(0, ks.confirmed - 1)
        if old == "false_positive":
            ks.false_positive = max(0, ks.false_positive - 1)
        if label == "confirmed":
            ks.confirmed += 1
        elif label == "false_positive":
            ks.false_positive += 1
        session.add(ks)
    session.flush()
    retrain(training_samples(session))
    rescore_all(session)
