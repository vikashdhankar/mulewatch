"""Detect repeated / coordinated advertisements.

Three independent link types feed one union-find:
  1. near-duplicate text   (MinHash LSH over word 3-shingles, Jaccard >= 0.5)
  2. reposted images        (perceptual hash, Hamming distance <= 10)
  3. shared identifiers     (same phone / UPI / Telegram / WhatsApp / wallet / handle)
Connected components with >= 2 posts are 'rings'."""
import re
from collections import defaultdict

from datasketch import MinHash, MinHashLSH

from .imaging import phash_distance

LINK_KINDS = ("phone", "upi", "telegram", "whatsapp", "handle", "email", "crypto_wallet", "card_number", "ifsc",
              "bank_account")
IGNORE_DOMAINS = {"facebook.com", "instagram.com", "x.com", "twitter.com", "youtube.com", "olx.in",
                  "google.com", "t.me", "wa.me", "whatsapp.com", "telegram.me"}


def _shingles(text: str) -> set[str]:
    t = re.sub(r"\d+", "0", text.lower())
    words = re.findall(r"[\wऀ-ॿ]+", t)
    return {" ".join(words[i:i + 3]) for i in range(max(0, len(words) - 2))}


class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def entity_keys(entities: dict) -> list[str]:
    keys = []
    for kind in LINK_KINDS:
        for v in entities.get(kind, []):
            keys.append(f"{kind}:{v}")
    for d in entities.get("domains", []):
        if d not in IGNORE_DOMAINS:
            keys.append(f"domain:{d}")
    return keys


def compute(posts: list) -> dict:
    """posts: objects with id, text, ocr_text, entities, image_phash.
    Returns {post_id: {"cluster": root_id, "related": {other_id: set(reasons)}}}"""
    uf = UF()
    related: dict[int, dict[int, set]] = defaultdict(lambda: defaultdict(set))

    def link(a, b, why):
        if a == b:
            return
        uf.union(a, b)
        related[a][b].add(why)
        related[b][a].add(why)

    # 1. near-duplicate text
    lsh = MinHashLSH(threshold=0.5, num_perm=96)
    mh = {}
    for p in posts:
        sh = _shingles((p.text or "") + " " + (p.ocr_text or ""))
        if len(sh) < 4:
            continue
        m = MinHash(num_perm=96)
        for s in sh:
            m.update(s.encode("utf-8"))
        mh[p.id] = m
        lsh.insert(str(p.id), m)
    for pid, m in mh.items():
        for other in lsh.query(m):
            o = int(other)
            if o != pid and mh[o].jaccard(m) >= 0.5:
                link(pid, o, "near-duplicate text")

    # 2. reposted images
    imgs = [p for p in posts if p.image_phash]
    for i, a in enumerate(imgs):
        for b in imgs[i + 1:]:
            if phash_distance(a.image_phash, b.image_phash) <= 10:
                link(a.id, b.id, "same / edited image")

    # 3. shared identifiers
    owners: dict[str, list[int]] = defaultdict(list)
    for p in posts:
        for k in entity_keys(p.entities or {}):
            owners[k].append(p.id)
    for key, ids in owners.items():
        if 2 <= len(ids) <= 400:
            kind, val = key.split(":", 1)
            for o in ids[1:]:
                link(ids[0], o, f"shared {kind.replace('_', ' ')} {val}")
            # make reasons visible between every pair (cheap for typical ring sizes)
            if len(ids) <= 40:
                for a in ids:
                    for b in ids:
                        if a != b:
                            related[a][b].add(f"shared {kind.replace('_', ' ')} {val}")

    out = {}
    for p in posts:
        out[p.id] = {"cluster": uf.find(p.id) if p.id in uf.p else None, "related": related.get(p.id, {})}
    return out


def ring_boost(base: float, cluster_size: int, cluster_max_base: float, platforms: int) -> float:
    if cluster_size < 2 or cluster_max_base < 55:
        return 0.0
    boost = 4 + 2.0 * min(cluster_size, 6) + 3 * (platforms > 1)
    return round(min(20.0, boost if base >= 20 else boost * 0.7), 1)
