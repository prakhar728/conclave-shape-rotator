"""Conservative entity resolution (Phase 3.5b C15, Q5; OI-7 redesign 2026-06-11).

People → exact casefolded name match (the roster path; no embedding). Non-person
entities are pooled by their derived CATEGORY (tech / affiliation) and resolve in
layers:

    1. lexical gate    normalized-exact name match → deterministic merge (catches
                       DStack/Dstack, Flash Bots/Flashbots). Also the
                       degenerate-embedding guard: lexically-disjoint names can
                       NEVER auto-merge.
    2. definition cos  embed the entity DEFINITION (a sentence), not the bare
                       name — sentences don't collapse the way 1-token names do.
    3. LLM tiebreak    when cosine ≥ TIEBREAK_THRESHOLD the in-TEE LLM decides,
                       fed both names + definitions. The embedding only
                       *proposes*; the LLM disposes. **No bare-cosine auto-merge**
                       — that short-circuit was the OI-7 black-hole bug.

Bias toward duplicate clutter over false merges (false merges are unrecoverable;
duplicates are visible and mergeable in the UI). Every decision carries its
evidence (similarity, tiebreak used) for the C17 audit log.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from storage.kb_graph import category_of
from transcripts.llm import invoke_json, LLMOutputError, LLMUnavailable

log = logging.getLogger(__name__)

#: Retained for reference/back-compat. The resolver no longer auto-merges on
#: cosine alone (that was the OI-7 bug); lexical match is the only deterministic
#: merge, everything else routes through the LLM tiebreak.
AUTO_MERGE_THRESHOLD = 0.90
TIEBREAK_THRESHOLD = 0.75


def _normalize_name(name: str) -> str:
    """Casefold + strip light punctuation + collapse all whitespace, for the
    lexical gate. "DStack"/"Dstack"/"D-Stack" → "dstack"; "Flash Bots" →
    "flashbots"."""
    n = (name or "").casefold()
    n = re.sub(r"[.,'\"()\-/_]", "", n)
    n = re.sub(r"\s+", "", n)
    return n


def _lexical_match(a: str, b: str) -> bool:
    """Conservative deterministic merge: normalized-exact only. Typos /
    abbreviations are left to the definition-embedding + LLM layer (avoids
    Sam/Sami-style false merges)."""
    na, nb = _normalize_name(a), _normalize_name(b)
    return bool(na) and na == nb


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


_TIEBREAK_SYSTEM = """You decide whether two entities refer to the same real-world
thing (project, topic, company, or tool) in a startup-cohort context. You are given
each entity's name and a short definition. Consider abbreviations, partial names,
and casing — but different products from the same family are DIFFERENT entities
(e.g. "Phala TDX" vs "Phala Network").

Output ONLY a raw JSON object: {"same": true} or {"same": false}."""


def resolve_entity(
    candidate: dict,
    existing: list[dict],
    *,
    embed_fn: Optional[Callable[[list[str]], list[list[float]]]] = None,
    llm: Any = None,
    model: Optional[str] = None,
) -> ResolutionDecision:
    """Resolve one extracted entity against existing entities in its CATEGORY.

    ``candidate``: {type, canonical_name, definition?}.
    ``existing``: [{id, type, canonical_name, definition?, embedding?}].
    The pool is filtered to the candidate's derived category (person / tech /
    affiliation), so a tool and a project naming the same tech resolve together.
    ``embed_fn``: texts -> vectors (defaults to transcripts.embed.embed_texts);
    the *definition* is embedded, not the bare name (fixes the OI-7 collapse).
    """
    ctype = candidate["type"]
    cname = candidate["canonical_name"].strip()
    cdef = (candidate.get("definition") or "").strip()
    ccat = category_of(ctype)
    pool = [e for e in existing if category_of(e.get("type") or "") == ccat]
    if not pool:
        return ResolutionDecision(action="new")

    # --- people: exact casefolded match only (cross-meeting identity is v1.5) --
    if ccat == "person":
        for e in pool:
            if e["canonical_name"].strip().casefold() == cname.casefold():
                return ResolutionDecision(
                    action="merge", target_id=e["id"], similarity=1.0,
                )
        return ResolutionDecision(action="new")

    # --- (1) lexical gate: normalized-exact name → deterministic merge, no LLM -
    for e in pool:
        if _lexical_match(cname, e["canonical_name"]):
            return ResolutionDecision(action="merge", target_id=e["id"], similarity=1.0)

    # --- (2) definition-embedding cosine → (3) LLM tiebreak -------------------
    # The embedding only PROPOSES the nearest candidate; the LLM disposes. There
    # is NO bare-cosine auto-merge — that short-circuit was the OI-7 black hole.
    if embed_fn is None:
        from transcripts.embed import embed_texts

        def embed_fn(texts):  # type: ignore[no-redef]
            return embed_texts(texts, kind="document")

    def _text(name: str, definition: str) -> str:
        return f"{name} — {definition}" if definition else name

    need = [_text(cname, cdef)]
    for e in pool:
        if not e.get("embedding"):
            need.append(_text(e["canonical_name"], (e.get("definition") or "").strip()))
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
    if sim >= TIEBREAK_THRESHOLD:
        same = _llm_tiebreak(
            cname, match["canonical_name"], cdef, (match.get("definition") or ""),
            llm=llm, model=model,
        )
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
    name_a: str, name_b: str, def_a: str = "", def_b: str = "",
    *, llm: Any = None, model: Optional[str] = None,
) -> bool:
    """Cosine ≥ TIEBREAK_THRESHOLD: ask the LLM, fed both names + definitions.
    Failure → NOT same (conservative: duplicates over false merges)."""
    a = f'Name A: "{name_a}"' + (f"\nDefinition A: {def_a}" if def_a else "")
    b = f'Name B: "{name_b}"' + (f"\nDefinition B: {def_b}" if def_b else "")
    messages = [
        SystemMessage(content=_TIEBREAK_SYSTEM),
        HumanMessage(content=f"{a}\n{b}"),
    ]
    try:
        data = invoke_json(messages, llm=llm, model=model, required_keys=("same",))
        return bool(data.get("same"))
    except (LLMOutputError, LLMUnavailable) as exc:
        log.warning("ER tiebreak failed (%s); keeping entities separate", exc)
        return False
