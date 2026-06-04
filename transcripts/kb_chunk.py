"""Turn-aware KB chunker (Phase 3.5a C6).

Produces the chunk rows the 3.5 knowledge pipeline stores, embeds, and
indexes — distinct from the v1 enrichment chunker (`transcripts/chunk.py`,
which feeds map-reduce summarization and keeps no turn identity).

Rules (KB-AND-GRAPH-ROADMAP-v2 §3 "Pipeline", Survey D1/D2):

- chunk budget = ``min(model_ctx × 0.4, 6000)`` heuristic tokens
- never split mid-turn; 1–2 turn trailing overlap between chunks
- oversized single turn → recursive sentence split (sub-turns inherit
  the turn id; ``turn_ids`` may repeat a turn across chunks)

Turn ids are 0-indexed positions in the parsed segment list — the same
convention as the eval yamls (CONVENTIONS.md §Turn-id) and the bake-off.

Pure module: no LLM, no I/O, no storage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Hard ceiling per Survey D1 — even huge-context models don't get
#: bigger chunks; retrieval granularity beats stuffing.
CHUNK_TOKEN_CEILING = 6000

#: Default model context for budget computation. gemma-3-27b serves
#: 54k; min(54k × 0.4, 6k) = 6k. Local qwen at 8k ctx → 3.2k budget.
DEFAULT_MODEL_CTX = 54_000

#: The embedder is the real binding constraint for retrieval chunks:
#: Ollama's nomic-embed-text GGUF is architecturally capped at 2048
#: (nomic-bert.context_length — the 8192 advertised for nomic v1.5
#: elsewhere is NOT available via Ollama; num_ctx override rejected,
#: verified empirically 2026-06-04). Budget takes 0.6 × this to leave
#: room for the search_document: prefix, the context header, and
#: chars/4-heuristic underestimation on real transcript text.
EMBED_MODEL_CTX = 2048

#: Trailing turns carried into the next chunk.
OVERLAP_TURNS = 2

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class KBChunk:
    """One storable chunk: contiguous turn span + rendered text."""
    chunk_index: int
    turn_ids: list[int] = field(default_factory=list)
    text: str = ""
    token_count: int = 0


def chunk_budget(
    model_ctx: int = DEFAULT_MODEL_CTX,
    embed_ctx: int = EMBED_MODEL_CTX,
) -> int:
    """min(extraction window, embeddable window, hard ceiling).

    With Ollama-nomic's 2048 cap this resolves to ~1228 heuristic
    tokens (~5KB text) — also a better retrieval granularity than the
    6k extraction-window-sized chunks the roadmap formula alone gives.
    """
    return min(int(model_ctx * 0.4), int(embed_ctx * 0.6), CHUNK_TOKEN_CEILING)


def estimate_tokens(text: str) -> int:
    """Cheap chars/4 heuristic — same as the v1 chunker's policy."""
    return max(1, len(text) // 4) if text else 0


def chunk_transcript(
    segments: list[dict],
    *,
    model_ctx: int = DEFAULT_MODEL_CTX,
    overlap_turns: int = OVERLAP_TURNS,
) -> list[KBChunk]:
    """Pack parsed segments into turn-aware chunks.

    ``segments``: ``NormalizedInput.segments`` dicts (speaker/text).
    Turn id = position in this list.

    Returns chunks whose rendered ``text`` is ``speaker: body`` lines.
    A single over-budget turn is sentence-split across chunks; every
    piece keeps the original turn id, so consumers must treat
    ``turn_ids`` as "turns represented in this chunk", not "complete
    turns contained".
    """
    budget = chunk_budget(model_ctx)

    # Expand: (turn_id, speaker, body) — oversize turns become several
    # entries with the same turn_id.
    pieces: list[tuple[int, str, str]] = []
    for tid, seg in enumerate(segments):
        speaker = str(seg.get("speaker") or "speaker_unknown")
        body = (seg.get("text") or "").strip()
        if not body:
            continue
        line_tokens = estimate_tokens(body) + estimate_tokens(speaker) + 2
        if line_tokens <= budget:
            pieces.append((tid, speaker, body))
        else:
            for part in _split_sentences(body, budget - estimate_tokens(speaker) - 2):
                pieces.append((tid, speaker, part))

    chunks: list[KBChunk] = []
    current: list[tuple[int, str, str]] = []
    current_tokens = 0

    def _flush() -> None:
        nonlocal current, current_tokens
        if not current:
            return
        text = "\n".join(f"{sp}: {body}" for _, sp, body in current)
        chunks.append(KBChunk(
            chunk_index=len(chunks),
            turn_ids=sorted({tid for tid, _, _ in current}),
            text=text,
            token_count=estimate_tokens(text),
        ))
        tail = current[-overlap_turns:] if overlap_turns > 0 else []
        current = list(tail)
        current_tokens = sum(
            estimate_tokens(b) + estimate_tokens(s) + 2 for _, s, b in current
        )

    for piece in pieces:
        tid, speaker, body = piece
        t = estimate_tokens(body) + estimate_tokens(speaker) + 2
        if current and current_tokens + t > budget:
            _flush()
            # Overlap alone may still not leave room (tight budgets):
            # drop overlap from the front until the new piece fits.
            while current and current_tokens + t > budget:
                _, ds, db = current.pop(0)
                current_tokens -= estimate_tokens(db) + estimate_tokens(ds) + 2
        current.append(piece)
        current_tokens += t

    # Final flush — but without seeding pointless overlap.
    if current:
        text = "\n".join(f"{sp}: {body}" for _, sp, body in current)
        chunks.append(KBChunk(
            chunk_index=len(chunks),
            turn_ids=sorted({tid for tid, _, _ in current}),
            text=text,
            token_count=estimate_tokens(text),
        ))
    return chunks


def _split_sentences(body: str, budget: int) -> list[str]:
    """Recursive sentence split for an over-budget turn body.

    Falls back to a hard character window when a single sentence alone
    exceeds the budget (pathological run-on).
    """
    budget = max(budget, 16)
    sentences = _SENTENCE_SPLIT_RE.split(body)
    if len(sentences) <= 1:
        return _hard_split(body, budget)
    out: list[str] = []
    buf: list[str] = []
    for sentence in sentences:
        trial = " ".join(buf + [sentence]) if buf else sentence
        if buf and estimate_tokens(trial) > budget:
            out.append(" ".join(buf))
            buf = [sentence]
        else:
            buf.append(sentence)
    if buf:
        out.append(" ".join(buf))
    # A single sentence may itself exceed budget — recurse via hard split.
    safe: list[str] = []
    for part in out:
        if estimate_tokens(part) <= budget:
            safe.append(part)
        else:
            safe.extend(_hard_split(part, budget))
    return safe


def _hard_split(body: str, budget: int) -> list[str]:
    window = max(1, budget * 4)
    return [body[i:i + window] for i in range(0, len(body), window)]
