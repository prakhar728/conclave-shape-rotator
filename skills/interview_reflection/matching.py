"""
Cohort matching — "who should talk to whom, and why".

Cross-person pass over the stored collaboration profiles (aggregate.py reads
across slugs). The LLM's only job was extraction; matching itself is
deterministic code + a pinned embedding model:

  Step A — tag bucketing (deterministic, explainable): candidate pairs are those
    whose need-tags intersect the other side's offer/domain tags (help), share a
    domain at a nearby stage (peer), or sit in adjacent domains (cross-pollinate).
  Step B — embedding rank (recovers phrasing the tags missed): embed the
    need/offer/building text with a pinned sentence-transformers model and
    cosine-rank; a similarity floor filters weak matches and also lets a strong
    semantic match survive thin tag overlap.

Match score = weighted blend of tag overlap + embedding similarity + a low-weight
style tiebreaker (demonstrated-credibility offers rank higher).

Three intro types — help (directional A→B), peer (symmetric), cross-pollinate
(symmetric) — each emitted with both evidence quotes. Output also includes a
cohort connection graph (nodes = people, edges = intros colored by type).

Embeddings load the real model offline (local_files_only); tests monkeypatch
`_get_model` to None to force the deterministic hash fallback.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from itertools import combinations, permutations
from pathlib import Path
from typing import Optional

import numpy as np

from config import settings
from skills.interview_reflection import taxonomy
from skills.interview_reflection.aggregate import list_all_slugs, load_latest_profile


# Score-blend weights (eyeball-tuned at S9/S10) and gates.
W_TAG, W_EMB, W_STYLE = 0.40, 0.50, 0.10
SIMILARITY_FLOOR = 0.30          # cosine floor for help/cross candidates
CROSS_SIM_CEILING = 0.75         # above this, it's not "different spaces"
PEER_STAGE_MAX_DIST = 1          # stages this close count as peers

EMBED_MODEL_NAME = settings.embedding_model   # "all-MiniLM-L6-v2", pinned
_FALLBACK_DIM = 256

_model = None
_model_load_failed = False


@dataclass
class Intro:
    frm: str
    to: str
    type: str                     # "help" | "peer" | "cross-pollinate"
    score: float
    reason: str
    quote_from: Optional[str] = None
    quote_to: Optional[str] = None
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["from"] = d.pop("frm")
        return d


# --- embedding (pinned model, offline hash fallback) ---

def _get_model():
    global _model, _model_load_failed
    if _model_load_failed:
        return None
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(EMBED_MODEL_NAME, local_files_only=True)
        except Exception:
            _model_load_failed = True
            return None
    return _model


def _fallback_vector(text: str) -> np.ndarray:
    """Deterministic offline embedding from token hashing (same idea as
    hackathon_novelty.deterministic)."""
    vec = np.zeros(_FALLBACK_DIM, dtype=np.float32)
    for token in text.lower().split() or [""]:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % _FALLBACK_DIM
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] += sign * (1.0 + digest[5] / 255.0)
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


def embed_texts(texts: list[str]) -> dict[str, np.ndarray]:
    """Return {text: unit-normalized vector} for each non-empty text."""
    uniq = sorted({t for t in texts if t and t.strip()})
    if not uniq:
        return {}
    model = _get_model()
    if model is None:
        return {t: _fallback_vector(t) for t in uniq}
    raw = model.encode(uniq, show_progress_bar=False)
    out: dict[str, np.ndarray] = {}
    for t, v in zip(uniq, raw):
        v = np.asarray(v, dtype=np.float32)
        norm = np.linalg.norm(v)
        out[t] = v / norm if norm > 0 else v
    return out


def _cosine(cache: dict[str, np.ndarray], a: str, b: str) -> float:
    va, vb = cache.get(a), cache.get(b)
    if va is None or vb is None:
        return 0.0
    return float(np.dot(va, vb))


# --- profile helpers ---

def load_cohort_profiles(root: Optional[Path] = None) -> dict[str, dict]:
    """{slug: collaboration_profile} for every slug with a stored profile."""
    profiles: dict[str, dict] = {}
    for slug in list_all_slugs(root):
        profile = load_latest_profile(slug, root)
        if profile:
            profiles[slug] = profile
    return profiles


def _tags_of(items: list[dict]) -> set[str]:
    out: set[str] = set()
    for it in items or []:
        out.update(it.get("tags") or [])
    return out


def _join(items: list[dict]) -> str:
    parts = []
    for it in items or []:
        text = it.get("text") or ""
        quote = it.get("quote") or ""
        parts.append(f"{text} {quote}".strip())
    return " ; ".join(p for p in parts if p)


def _building_text(profile: dict) -> str:
    return profile.get("building") or " ".join(profile.get("building_tags") or [])


def _rep_quote(profile: dict) -> Optional[str]:
    """A representative quote for a person (for peer/cross intros)."""
    for bucket in ("offers", "needs", "interests"):
        for it in profile.get(bucket) or []:
            if it.get("quote"):
                return it["quote"]
    return None


def _pick_item(items: list[dict], overlap: set[str]) -> Optional[dict]:
    """The item whose tags drove the overlap, else the first quoted item."""
    for it in items or []:
        if set(it.get("tags") or []) & overlap and it.get("quote"):
            return it
    for it in items or []:
        if it.get("quote"):
            return it
    return None


def _style(offer_item: Optional[dict]) -> float:
    """Low-weight tiebreaker: demonstrated expertise outranks merely claimed.
    (Coachability-based weighting can layer on once the panel is loaded too.)"""
    if offer_item and offer_item.get("credibility") == "demonstrated":
        return 1.0
    return 0.4


# --- intro builders ---

def _help_intros(profiles: dict[str, dict], cache: dict[str, np.ndarray]) -> list[Intro]:
    intros: list[Intro] = []
    for a, b in permutations(profiles, 2):
        pa, pb = profiles[a], profiles[b]
        if not pa.get("needs"):
            continue
        need_tags = _tags_of(pa["needs"])
        offer_tags = _tags_of(pb.get("offers")) | set(pb.get("building_tags") or [])
        overlap = need_tags & offer_tags

        need_text, offer_text = _join(pa["needs"]), _join(pb.get("offers"))
        sim = _cosine(cache, need_text, offer_text)

        if not overlap and sim < SIMILARITY_FLOOR:
            continue   # neither a shared tag nor a strong semantic match

        need_item = _pick_item(pa["needs"], overlap)
        offer_item = _pick_item(pb.get("offers"), overlap)
        if offer_item is None:
            continue   # nothing quotable to offer

        tag_overlap_norm = len(overlap) / len(need_tags) if need_tags else 0.0
        score = W_TAG * tag_overlap_norm + W_EMB * sim + W_STYLE * _style(offer_item)

        need_desc = need_item["text"] if need_item else "this"
        reason = (
            f"{a} needs help with {need_desc}; {b} has done {offer_item['text']}"
        )
        intros.append(Intro(
            frm=a, to=b, type="help", score=round(score, 3), reason=reason,
            quote_from=need_item.get("quote") if need_item else None,
            quote_to=offer_item.get("quote"),
            tags=sorted(overlap),
        ))
    return intros


def _peer_intros(profiles: dict[str, dict], cache: dict[str, np.ndarray],
                 peer_pairs: set) -> list[Intro]:
    intros: list[Intro] = []
    for a, b in combinations(sorted(profiles), 2):
        pa, pb = profiles[a], profiles[b]
        dom = set(pa.get("building_tags") or []) & set(pb.get("building_tags") or [])
        sa, sb = taxonomy.stage_index(pa.get("stage")), taxonomy.stage_index(pb.get("stage"))
        if not dom or sa is None or sb is None or abs(sa - sb) > PEER_STAGE_MAX_DIST:
            continue
        peer_pairs.add(frozenset((a, b)))

        sim = _cosine(cache, _building_text(pa), _building_text(pb))
        union = set(pa.get("building_tags") or []) | set(pb.get("building_tags") or [])
        tag_overlap = len(dom) / len(union) if union else 0.0
        score = W_TAG * tag_overlap + W_EMB * sim + W_STYLE * 0.5
        reason = (
            f"Both building in {', '.join(sorted(dom))} around "
            f"{pa.get('stage')}/{pb.get('stage')} — natural accountability partners"
        )
        intros.append(Intro(
            frm=a, to=b, type="peer", score=round(score, 3), reason=reason,
            quote_from=_rep_quote(pa), quote_to=_rep_quote(pb), tags=sorted(dom),
        ))
    return intros


def _cross_intros(profiles: dict[str, dict], cache: dict[str, np.ndarray],
                  peer_pairs: set) -> list[Intro]:
    intros: list[Intro] = []
    for a, b in combinations(sorted(profiles), 2):
        if frozenset((a, b)) in peer_pairs:
            continue
        pa, pb = profiles[a], profiles[b]
        ta, tb = set(pa.get("building_tags") or []), set(pb.get("building_tags") or [])
        if not taxonomy.are_adjacent(ta, tb):
            continue
        sim = _cosine(cache, _building_text(pa), _building_text(pb))
        if not (SIMILARITY_FLOOR <= sim < CROSS_SIM_CEILING):
            continue
        score = W_TAG * 0.5 + W_EMB * sim
        reason = (
            f"Different but adjacent spaces ({', '.join(sorted(ta))} ↔ "
            f"{', '.join(sorted(tb))}) — transferable approach worth a cross-pollination intro"
        )
        intros.append(Intro(
            frm=a, to=b, type="cross-pollinate", score=round(score, 3), reason=reason,
            quote_from=_rep_quote(pa), quote_to=_rep_quote(pb),
            tags=sorted(ta | tb),
        ))
    return intros


# --- entry point ---

def run_matching(root: Optional[Path] = None, top_k: Optional[int] = None) -> dict:
    profiles = load_cohort_profiles(root)

    # Embed every text the matcher will compare, once.
    texts: list[str] = []
    for p in profiles.values():
        texts += [_join(p.get("needs")), _join(p.get("offers")), _building_text(p)]
    cache = embed_texts(texts)

    peer_pairs: set = set()
    intros = (
        _help_intros(profiles, cache)
        + _peer_intros(profiles, cache, peer_pairs)
        + _cross_intros(profiles, cache, peer_pairs)
    )
    intros.sort(key=lambda i: i.score, reverse=True)
    if top_k is not None:
        intros = intros[:top_k]

    graph = {
        "nodes": [{"slug": s} for s in sorted(profiles)],
        "edges": [
            {"from": i.frm, "to": i.to, "type": i.type, "score": i.score}
            for i in intros
        ],
    }
    return {"intros": [i.to_dict() for i in intros], "graph": graph}
