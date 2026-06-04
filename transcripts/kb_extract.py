"""KB extraction pipeline: extract → importance → ER → upsert (3.5b C17).

⚠️ The riskiest wiring in Phase 3.5 — hence the kill switch:

    ENABLE_KB_PIPELINE=1   pipeline runs (dev/test, later prod)
    unset / anything else  pipeline is a no-op

Default OFF everywhere. Migrations 0007/0008 + the C13-C16 modules all
ship inert; flipping the env var on (or off — the rollback) requires no
deploy. ``kb_pipeline_enabled()`` is the single source of truth.

Stage order per roadmap §3 Pipeline (runs after 3.5a's chunk/embed):

    load chunks (storage.kb)          [3.5a output]
      ↓ extract_from_chunk per chunk  [C13, 1 LLM call/chunk]
      ↓ merge entities / dedupe obligations across chunks
      ↓ entity resolution             [C15, embeddings + 0-2 LLM/entity]
      ↓ importance scoring            [C14, 1 LLM call/10 items]
      ↓ Mem0 upsert                   [C16, 1 LLM call/obligation]
      ↓ bi-temporal writes            [storage.kb_graph]

Every stage records (llm_calls, ms, items) into ingest_metrics.
LLMUnavailable aborts the session cleanly (re-runnable); per-item
failures degrade per each module's own policy.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

from storage import kb, kb_graph
from transcripts.embed import EMBED_MODEL_ID, EmbeddingUnavailable, embed_texts
from transcripts.entity_resolution import resolve_entity
from transcripts.extract import (
    EXTRACT_PROMPT_VERSION,
    dedupe_obligations,
    extract_from_chunk,
    merge_entities,
)
from transcripts.importance import score_importance
from transcripts.llm import LLMUnavailable
from transcripts.upsert import decide_upsert

logger = logging.getLogger(__name__)

UPSERT_TOP_K = 5


def kb_pipeline_enabled() -> bool:
    return os.environ.get("ENABLE_KB_PIPELINE", "").strip().lower() in ("1", "true", "yes")


def extract_session(session_id: str) -> Optional[dict]:
    """Run the full KB extraction pipeline for one session.

    Returns a metrics dict, or None when disabled / nothing to do.
    Never raises.
    """
    if not kb_pipeline_enabled():
        return None
    try:
        return _run(session_id)
    except LLMUnavailable as exc:
        logger.warning("kb extract: LLM unavailable for %s, session re-runnable: %s",
                       session_id, exc)
        return None
    except Exception:
        logger.exception("kb extract failed for session %s", session_id)
        return None


def _run(session_id: str) -> Optional[dict]:
    from transcripts import store

    session = store.load_session(session_id)
    if session is None:
        logger.error("kb extract: session %s not found", session_id)
        return None
    chunks = kb.query_chunks_for_session(session_id)
    if not chunks:
        logger.info("kb extract: session %s has no chunks (run kb_pipeline first)",
                    session_id)
        return None
    n_turns = len(session.raw_diarization or [])
    metrics: dict = {"session_id": session_id}

    # --- 1. extraction ------------------------------------------------------
    t0 = time.time()
    raw_entities: list[dict] = []
    raw_obligations: list[dict] = []
    for c in chunks:
        r = extract_from_chunk(
            c["text"], c.get("context_header") or "", turn_count=n_turns,
        )
        raw_entities.extend(r.entities)
        raw_obligations.extend(r.obligations)
    entities = merge_entities(raw_entities)
    obligations = dedupe_obligations(raw_obligations)
    ms = int((time.time() - t0) * 1000)
    kb_graph.record_metric(
        session_id, "extract", llm_calls=len(chunks), ms=ms,
        items_in=len(chunks), items_out=len(entities) + len(obligations),
    )
    metrics.update(entities=len(entities), obligations=len(obligations),
                   ms_extract=ms)

    # --- 2. entity resolution ------------------------------------------------
    t1 = time.time()
    er_llm_calls = 0
    entity_id_by_name: dict[str, str] = {}
    for ent in entities:
        pool = kb_graph.entities_for_er(ent["type"], model_id=EMBED_MODEL_ID)
        decision = resolve_entity(ent, pool)
        if decision.llm_tiebreak_used:
            er_llm_calls += 1
        if decision.action == "merge" and decision.target_id:
            eid = decision.target_id
            kb_graph.merge_mentions_into_entity(eid, ent["raw_mentions"])
        else:
            eid = kb_graph.insert_entity(
                ent["type"], ent["canonical_name"], ent["raw_mentions"],
            )
            _try_embed_entity(eid, ent["canonical_name"])
        entity_id_by_name[ent["canonical_name"].casefold()] = eid
        kb_graph.add_mentions(
            eid, session_id, ent["turn_ids"], ent["raw_mentions"][0],
        )
    ms = int((time.time() - t1) * 1000)
    kb_graph.record_metric(
        session_id, "entity_resolution", llm_calls=er_llm_calls, ms=ms,
        items_in=len(entities), items_out=len(entity_id_by_name),
    )
    metrics["ms_er"] = ms

    # --- 3. importance --------------------------------------------------------
    t2 = time.time()
    scores = score_importance(obligations)
    for ob, s in zip(obligations, scores):
        ob["importance"] = s
    llm_calls = (len(obligations) + 9) // 10 if obligations else 0
    ms = int((time.time() - t2) * 1000)
    kb_graph.record_metric(
        session_id, "importance", llm_calls=llm_calls, ms=ms,
        items_in=len(obligations), items_out=len(obligations),
    )
    metrics["ms_importance"] = ms

    # --- 4. owner linking (no LLM — uses ER results) ---------------------------
    for ob in obligations:
        owner = (ob.get("owner_raw_text") or "").casefold()
        if owner and owner in entity_id_by_name:
            ob["owner_entity_id"] = entity_id_by_name[owner]

    # --- 5. Mem0 upsert + bi-temporal writes -----------------------------------
    t3 = time.time()
    upsert_llm_calls = 0
    inserted = 0
    for ob in obligations:
        try:
            vec = embed_texts([ob["description"]], kind="document")[0]
        except EmbeddingUnavailable:
            vec = None
        similar = (
            kb_graph.similar_obligations(
                vec, otype=ob["type"], k=UPSERT_TOP_K, model_id=EMBED_MODEL_ID,
            ) if vec else []
        )
        decision = decide_upsert(ob, similar)
        if similar:
            upsert_llm_calls += 1
        new_id = kb_graph.execute_upsert(
            decision, ob, session_id=session_id,
            model_version=EXTRACT_PROMPT_VERSION,
        )
        if new_id:
            inserted += 1
            if vec:
                kb_graph.save_source_embedding(
                    "obligation", new_id, vec, model_id=EMBED_MODEL_ID,
                )
    ms = int((time.time() - t3) * 1000)
    kb_graph.record_metric(
        session_id, "upsert", llm_calls=upsert_llm_calls, ms=ms,
        items_in=len(obligations), items_out=inserted,
    )
    metrics.update(inserted=inserted, ms_upsert=ms)

    logger.info(
        "kb extract: %s — %d entities, %d obligations (%d inserted)",
        session_id, len(entities), len(obligations), inserted,
    )
    return metrics


def _try_embed_entity(entity_id: str, canonical_name: str) -> None:
    """Cache a name embedding for future ER rounds; failure is non-fatal."""
    try:
        vec = embed_texts([canonical_name], kind="document")[0]
        kb_graph.save_source_embedding("entity", entity_id, vec, model_id=EMBED_MODEL_ID)
    except EmbeddingUnavailable as exc:
        logger.warning("entity embedding skipped for %s: %s", entity_id, exc)
