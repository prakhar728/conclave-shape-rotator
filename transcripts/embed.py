"""Chunk/query embeddings via Ollama nomic-embed-text v1.5 (Phase 3.5a C8).

Survey D8 (model) + D18 (dimensions): full 768-dim vectors persist in
the ``embeddings`` table (model-keyed, so A/B swaps don't re-ingest);
the ANN index (``chunks_vec``) holds Matryoshka-truncated 256-dim
renormalized copies. Re-deriving the 256 from the stored 768 is a pure
function — no model call.

nomic-embed-text REQUIRES task prefixes — retrieval quality drops
sharply without them:
  - documents:  ``search_document: <text>``
  - queries:    ``search_query: <text>``

Embeddings go over Ollama's native ``/api/embed`` (the OpenAI-compat
``/v1`` path doesn't expose batch semantics as cleanly); the base URL
is derived from ``settings.ollama_base_url`` by stripping ``/v1``.

Always Ollama-served regardless of CONCLAVE_LLM_BACKEND — embedding is
in-process-adjacent and operator-blind by construction (no third-party
API in the query path; Roadmap "Operator-blind preservation").
"""
from __future__ import annotations

import json
import math
import struct
import urllib.request
from typing import Callable, Optional

EMBED_MODEL_ID = "nomic-embed-text:v1.5"
FULL_DIM = 768
#: ANN dim — must match storage.vec.VEC_DIM (chunks_vec float[256]).
INDEX_DIM = 256

DOC_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "

#: Batch size for /api/embed calls — bounded to keep request bodies sane.
BATCH_SIZE = 32


class EmbeddingUnavailable(Exception):
    """Ollama embed endpoint unreachable or returned malformed output."""


def _native_base_url() -> str:
    from config import settings
    base = settings.ollama_base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return base


def _http_embed(model: str, inputs: list[str], timeout: float = 120.0) -> list[list[float]]:
    """POST /api/embed — separated for test injection."""
    url = f"{_native_base_url()}/api/embed"
    body = json.dumps({"model": model, "input": inputs}).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except Exception as exc:  # noqa: BLE001 — network errors vary wildly
        raise EmbeddingUnavailable(f"ollama embed failed: {exc}") from exc
    embeddings = data.get("embeddings")
    if not isinstance(embeddings, list) or len(embeddings) != len(inputs):
        raise EmbeddingUnavailable(
            f"ollama embed returned {type(embeddings).__name__} "
            f"of len {len(embeddings) if isinstance(embeddings, list) else 'n/a'} "
            f"for {len(inputs)} inputs"
        )
    return embeddings


def embed_texts(
    texts: list[str],
    *,
    kind: str = "document",          # 'document' | 'query'
    model_id: str = EMBED_MODEL_ID,
    transport: Optional[Callable[[str, list[str]], list[list[float]]]] = None,
) -> list[list[float]]:
    """Embed texts with the correct nomic task prefix. Returns full-dim vectors.

    ``transport(model, inputs)`` injection for tests; defaults to the
    real Ollama HTTP call, batched at BATCH_SIZE.
    """
    if kind not in ("document", "query"):
        raise ValueError(f"kind must be 'document' or 'query', got {kind!r}")
    prefix = DOC_PREFIX if kind == "document" else QUERY_PREFIX
    prefixed = [prefix + (t or "") for t in texts]

    call = transport or _http_embed
    out: list[list[float]] = []
    for i in range(0, len(prefixed), BATCH_SIZE):
        out.extend(call(model_id, prefixed[i:i + BATCH_SIZE]))
    return out


def truncate_matryoshka(vec: list[float], dim: int = INDEX_DIM) -> list[float]:
    """Slice to ``dim`` and L2-renormalize (Matryoshka truncation contract)."""
    head = vec[:dim]
    norm = math.sqrt(sum(x * x for x in head))
    if norm == 0.0:
        return head
    return [x / norm for x in head]


def serialize_f32(vec: list[float]) -> bytes:
    """Little-endian float32 blob — the layout sqlite-vec expects."""
    return struct.pack(f"<{len(vec)}f", *vec)


def deserialize_f32(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))
