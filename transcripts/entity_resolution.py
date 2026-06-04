"""Conservative entity resolution (Phase 3.5b C15, Q5).

Thresholds locked by Q5 — bias toward duplicate clutter over false
merges (false merges are unrecoverable; duplicates are visible and
complainable, manual merge UI is v1.5):

    cosine > 0.90          auto-merge
    0.75 – 0.90            LLM tiebreak
    < 0.75                 new entity

People are special-cased: exact casefolded name match merges (the
existing per-meeting roster path, ``identity.resolve_speakers``, has
already normalized speaker labels upstream); no embedding/LLM step —
"Andrew Miller" the string either matches an existing person or it
doesn't. Cross-meeting person identity is explicitly v1.5 (roadmap).

Every decision is returned with its evidence (similarity, tiebreak
used) so C17 can write an audit log — bi-temporal data with silent
merges would be undebuggable.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Callable, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from transcripts.llm import invoke_json, LLMOutputError, LLMUnavailable

log = logging.getLogger(__name__)

AUTO_MERGE_THRESHOLD = 0.90
TIEBREAK_THRESHOLD = 0.75


@dataclass
class ResolutionDecision:
    action: str                      # 'merge' | 'new'
    target_id: Optional[str] = None  # entity id when action == 'merge'
    similarity: float = 0.0
    llm_tiebreak_used: bool = False


def cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a))
    db = math.sqrt(sum(x * x for x in b))
    if da == 0 or db == 0:
        return 0.0
    return num / (da * db)


_TIEBREAK_SYSTEM = """You decide whether two short names refer to the same real-world
entity (project, topic, company, or tool) in a startup-cohort context.
Consider abbreviations, partial names, and casing — but different
products from the same family are DIFFERENT entities (e.g. "Phala TDX"
vs "Phala Network").

Output ONLY a raw JSON object: {"same": true} or {"same": false}."""


def resolve_entity(
    candidate: dict,
    existing: list[dict],
    *,
    embed_fn: Optional[Callable[[list[str]], list[list[float]]]] = None,
    llm: Any = None,
    model: Optional[str] = None,
) -> ResolutionDecision:
    """Resolve one extracted entity against existing entities of the same type.

    ``candidate``: {type, canonical_name}.
    ``existing``: [{id, type, canonical_name, embedding?}] — pre-filtered
    or not; non-matching types are ignored here either way.
    ``embed_fn``: texts -> vectors (defaults to transcripts.embed.embed_texts);
    used only for non-person types and only when an existing row lacks a
    cached embedding vector.
    """
    ctype = candidate["type"]
    cname = candidate["canonical_name"].strip()
    pool = [e for e in existing if e.get("type") == ctype]
    if not pool:
        return ResolutionDecision(action="new")

    # --- people: exact casefolded match only (Q5 scope is projects/topics) --
    if ctype == "person":
        for e in pool:
            if e["canonical_name"].strip().casefold() == cname.casefold():
                return ResolutionDecision(
                    action="merge", target_id=e["id"], similarity=1.0,
                )
        return ResolutionDecision(action="new")

    # --- non-person: embedding cosine against the pool ----------------------
    if embed_fn is None:
        from transcripts.embed import embed_texts

        def embed_fn(texts):  # type: ignore[no-redef]
            return embed_texts(texts, kind="document")

    need = [cname] + [
        e["canonical_name"] for e in pool if not e.get("embedding")
    ]
    try:
        vecs = embed_fn(need)
    except Exception as exc:  # noqa: BLE001 — embed failure → safe default
        log.warning("ER embed failed (%s); defaulting to new entity", exc)
        return ResolutionDecision(action="new")
    cand_vec = vecs[0]
    fresh = iter(vecs[1:])
    best: Optional[tuple[float, dict]] = None
    for e in pool:
        vec = e.get("embedding") or next(fresh)
        sim = cosine(cand_vec, vec)
        if best is None or sim > best[0]:
            best = (sim, e)

    sim, match = best
    if sim > AUTO_MERGE_THRESHOLD:
        return ResolutionDecision(action="merge", target_id=match["id"], similarity=sim)
    if sim >= TIEBREAK_THRESHOLD:
        same = _llm_tiebreak(cname, match["canonical_name"], llm=llm, model=model)
        if same:
            return ResolutionDecision(
                action="merge", target_id=match["id"],
                similarity=sim, llm_tiebreak_used=True,
            )
        return ResolutionDecision(
            action="new", similarity=sim, llm_tiebreak_used=True,
        )
    return ResolutionDecision(action="new", similarity=sim)


def _llm_tiebreak(
    name_a: str, name_b: str, *, llm: Any = None, model: Optional[str] = None
) -> bool:
    """Ambiguous band 0.75-0.90: ask the LLM. Failure → NOT same
    (conservative: duplicates over false merges, per Q5)."""
    messages = [
        SystemMessage(content=_TIEBREAK_SYSTEM),
        HumanMessage(content=f'Name A: "{name_a}"\nName B: "{name_b}"'),
    ]
    try:
        data = invoke_json(messages, llm=llm, model=model, required_keys=("same",))
        return bool(data.get("same"))
    except (LLMOutputError, LLMUnavailable) as exc:
        log.warning("ER tiebreak failed (%s); keeping entities separate", exc)
        return False
