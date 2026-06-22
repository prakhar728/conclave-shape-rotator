"""KB ingest pipeline: chunk → context-header → embed → index (3.5a C10).

One entry point, ``index_session(session_id)``, called from
``_enrich_in_background`` after v1 enrichment. Also the unit the C11
backfill script loops over.

Failure policy mirrors the enrichment thread's: every stage is
best-effort and logged; a header failure degrades to "", an embedding
failure leaves chunks FTS-searchable but not vector-searchable
(re-runnable later — ``save_chunks`` is idempotent and
``save_chunk_embeddings`` upserts).

Stage timings land in the returned dict for C38's ingest_metrics to
pick up later (3.5f wires the table; the shape is stable from day one).
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from storage import kb
from transcripts.context_header import generate_header
from transcripts.embed import EMBED_MODEL_ID, EmbeddingUnavailable, embed_texts
from transcripts.kb_chunk import chunk_transcript

logger = logging.getLogger(__name__)


def index_session(
    session_id: str,
    *,
    with_headers: bool = True,
    embed_model_id: str = EMBED_MODEL_ID,
) -> Optional[dict]:
    """Chunk + header + embed + index one stored session.

    Returns a stage-timing/count dict, or None when the session doesn't
    exist or has no usable segments. Never raises.
    """
    from transcripts import store

    t0 = time.time()
    session = store.load_session(session_id)
    if session is None:
        logger.error("kb index: session %s not found", session_id)
        return None

    # Part 1: source from the approved v2 (corrected text + confirmed speaker)
    # when present; otherwise the immutable raw. So a user's approved
    # corrections are what gets chunked/embedded/extracted into the KB.
    segments = store.v2_segments_or_raw(session_id)
    if not segments:
        logger.info("kb index: session %s has no segments, skipping", session_id)
        return None

    metrics: dict = {"session_id": session_id}

    # 1. chunk -----------------------------------------------------------
    chunks = chunk_transcript(segments)
    metrics["chunks"] = len(chunks)
    metrics["ms_chunk"] = int((time.time() - t0) * 1000)

    # 2. context headers (best-effort, per-chunk LLM) ----------------------
    t1 = time.time()
    headers: list[str] = []
    if with_headers:
        meta = {
            "title": getattr(session.metadata, "record_id", None) or session_id,
            "date": getattr(session.metadata, "date", None),
            "members": ", ".join(
                getattr(session.metadata, "tags", None) or []
            ) or None,
        }
        for c in chunks:
            headers.append(generate_header(c.text, meta))
    else:
        headers = [""] * len(chunks)
    metrics["headers_nonempty"] = sum(1 for h in headers if h)
    metrics["ms_headers"] = int((time.time() - t1) * 1000)

    # 3. store chunks (FTS rides triggers) --------------------------------
    kb.save_chunks(session_id, chunks, headers=headers)

    # 4. embed + ANN index (best-effort) -----------------------------------
    t2 = time.time()
    try:
        texts = [
            (h + "\n\n" + c.text) if h else c.text
            for h, c in zip(headers, chunks)
        ]
        vectors = embed_texts(texts, kind="document", model_id=embed_model_id)
        kb.save_chunk_embeddings(
            session_id,
            {kb.chunk_id(session_id, c.chunk_index): v
             for c, v in zip(chunks, vectors)},
            model_id=embed_model_id,
        )
        metrics["embedded"] = len(vectors)
    except EmbeddingUnavailable as exc:
        logger.warning(
            "kb index: embeddings unavailable for %s (FTS still indexed): %s",
            session_id, exc,
        )
        metrics["embedded"] = 0
    metrics["ms_embed"] = int((time.time() - t2) * 1000)
    metrics["ms_total"] = int((time.time() - t0) * 1000)

    logger.info(
        "kb index: %s — %d chunks, %d headers, %d embedded in %dms",
        session_id, metrics["chunks"], metrics["headers_nonempty"],
        metrics["embedded"], metrics["ms_total"],
    )
    return metrics
