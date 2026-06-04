"""Phase 3.5a C6 — turn-aware KB chunker unit tests."""
from __future__ import annotations

import pytest

from transcripts.kb_chunk import (
    KBChunk,
    chunk_budget,
    chunk_transcript,
    estimate_tokens,
    CHUNK_TOKEN_CEILING,
)


def seg(speaker: str, text: str) -> dict:
    return {"speaker": speaker, "text": text}


SMALL = [
    seg("Ada", "We should ship the importer."),
    seg("Bob", "Agreed, by Friday."),
    seg("Ada", "I'll write the tests first."),
]


def test_budget_ceiling():
    # The embedder cap (2048 × 0.6 = 1228) binds for any realistic
    # extraction ctx; lifting embed_ctx exposes the other two terms.
    assert chunk_budget(1_000_000) == 1228
    assert chunk_budget(1_000_000, embed_ctx=100_000) == CHUNK_TOKEN_CEILING
    assert chunk_budget(8_000, embed_ctx=100_000) == 3_200  # 0.4 × ctx


def test_small_transcript_single_chunk():
    chunks = chunk_transcript(SMALL)
    assert len(chunks) == 1
    c = chunks[0]
    assert isinstance(c, KBChunk)
    assert c.chunk_index == 0
    assert c.turn_ids == [0, 1, 2]
    assert "Ada: We should ship the importer." in c.text
    assert c.token_count == estimate_tokens(c.text)


def test_empty_and_blank_turns_skipped():
    segs = [seg("Ada", "hello"), seg("Bob", "   "), seg("Cyd", "world")]
    chunks = chunk_transcript(segs)
    assert chunks[0].turn_ids == [0, 2]  # blank turn 1 not represented


def test_multi_chunk_with_overlap():
    # ~26 tokens per turn; budget 200 fits ~7 turns, so 2-turn overlap
    # is honorable at every boundary (overlap is best-effort and gets
    # dropped when a single turn nearly fills the budget by itself).
    segs = [seg(f"S{i}", "word " * 20) for i in range(30)]
    chunks = chunk_transcript(segs, model_ctx=500, overlap_turns=2)  # budget=200
    assert len(chunks) >= 2
    for a, b in zip(chunks, chunks[1:]):
        # 2-turn overlap: first turns of b include last turns of a
        assert set(a.turn_ids[-2:]) & set(b.turn_ids)
    # indices are sequential
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_overlap_dropped_when_turns_nearly_fill_budget():
    # One ~125-token turn per 200-token budget: no room for overlap —
    # chunks are disjoint rather than violating the budget.
    segs = [seg(f"S{i}", "word " * 100) for i in range(4)]
    chunks = chunk_transcript(segs, model_ctx=500, overlap_turns=2)
    assert len(chunks) == 4
    seen: set[int] = set()
    for c in chunks:
        assert not (seen & set(c.turn_ids))
        seen |= set(c.turn_ids)


def test_never_splits_midturn_when_turn_fits():
    segs = [seg("A", "x" * 400), seg("B", "y" * 400)]  # ~100 tokens each
    chunks = chunk_transcript(segs, model_ctx=300)  # budget=120 — one turn per chunk
    for c in chunks:
        for line in c.text.split("\n"):
            assert line.startswith(("A: ", "B: "))
            # the line is the complete turn body, not a fragment
            assert len(line) >= 400


def test_oversize_turn_sentence_split_keeps_turn_id():
    long_body = ". ".join(f"Sentence number {i} with several words here" for i in range(80)) + "."
    segs = [seg("Mono", long_body)]
    chunks = chunk_transcript(segs, model_ctx=500)  # budget=200 << body size
    assert len(chunks) >= 2
    for c in chunks:
        assert c.turn_ids == [0]  # every piece traces to the same turn
    # union of chunk texts covers the original words
    rejoined = " ".join(c.text.split(": ", 1)[1] for c in chunks)
    assert "Sentence number 0" in rejoined
    assert "Sentence number 79" in rejoined


def test_pathological_runon_hard_split():
    segs = [seg("Run", "x" * 5000)]  # no sentence boundaries
    chunks = chunk_transcript(segs, model_ctx=500)
    assert len(chunks) >= 2
    assert all(c.turn_ids == [0] for c in chunks)


def test_budget_respected():
    segs = [seg(f"S{i}", "word " * 50) for i in range(20)]
    budget = chunk_budget(1000)  # 400
    chunks = chunk_transcript(segs, model_ctx=1000)
    for c in chunks:
        # token_count measures rendered text; allow the speaker-prefix
        # overhead slack the packer accounts for
        assert c.token_count <= budget + 50


def test_empty_input():
    assert chunk_transcript([]) == []
