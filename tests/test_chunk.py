"""C7 gate — turn-aware chunker + pipeline constants.

Asserts the contract documented in IMPLEMENTATION_PLAN.md §G5 / §H C7:

- Short session → exactly one chunk (single-LLM-call fast path preserved).
- Long session → N chunks, each ≤ budget, with trailing overlap so a
  boundary-straddling signal is seen by both partial enrich calls.
- A single oversized turn is sentence-split before chunking.
- **Union of chunks covers the original text.** The reduce step relies on
  this — every original token must be enriched by at least one map call.
"""
from __future__ import annotations

import pytest

from transcripts.chunk import (
    _build_overlap,
    _split_oversized_turn,
    chunk_segments,
    estimate_tokens,
)
from transcripts.config import (
    CHUNK_MAX_TOKENS,
    CHUNK_OVERLAP_TOKENS,
    TOKENS_PER_CHAR,
)
from transcripts.models import RawSegment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seg(speaker: str, text: str, start: float = 0.0) -> RawSegment:
    return RawSegment(speaker=speaker, text=text, start=start)


def _budget_safe(chunks, max_tokens):
    """Every chunk's segment-token-sum must fit in the budget."""
    from transcripts.chunk import _segment_tokens
    return all(sum(_segment_tokens(s) for s in c) <= max_tokens for c in chunks)


def _flat_texts(chunks):
    return [s.text for c in chunks for s in c]


# ---------------------------------------------------------------------------
# estimate_tokens
# ---------------------------------------------------------------------------

def test_estimate_tokens_is_chars_times_factor():
    assert estimate_tokens("") == 0
    assert estimate_tokens("x" * 1000) == int(1000 * TOKENS_PER_CHAR)


# ---------------------------------------------------------------------------
# Fast path: short session → 1 chunk
# ---------------------------------------------------------------------------

def test_short_session_yields_single_chunk():
    segs = [_seg("speaker_1", "Hello there."), _seg("speaker_2", "General Kenobi.")]
    chunks = chunk_segments(segs)
    assert len(chunks) == 1
    assert chunks[0] == segs   # same objects, in order


def test_empty_segments_returns_empty():
    assert chunk_segments([]) == []


# ---------------------------------------------------------------------------
# Long session → N chunks with overlap
# ---------------------------------------------------------------------------

def test_long_session_splits_into_multiple_budget_safe_chunks():
    # Each segment ≈ 400 tokens (1600 chars). 30 of them ≈ 12k tokens >> budget.
    body = "word " * 320  # ~1600 chars → ~400 tokens
    segs = [_seg(f"speaker_{i % 3}", body, start=float(i)) for i in range(30)]
    chunks = chunk_segments(segs, max_tokens=2000, overlap=300)

    assert len(chunks) >= 2
    assert _budget_safe(chunks, max_tokens=2000)


def test_adjacent_chunks_overlap_by_trailing_segments():
    body = "word " * 320
    segs = [_seg("speaker_1", f"{i}: {body}", start=float(i)) for i in range(30)]
    chunks = chunk_segments(segs, max_tokens=2000, overlap=500)

    # Each chunk boundary should share at least one segment with its successor.
    for i in range(len(chunks) - 1):
        tail_texts = {s.text for s in chunks[i][-3:]}
        head_texts = {s.text for s in chunks[i + 1][:3]}
        assert tail_texts & head_texts, (
            f"chunks {i} and {i+1} share no segments — boundary signals would be lost"
        )


def test_zero_overlap_produces_disjoint_chunks():
    body = "word " * 320
    segs = [_seg("speaker_1", f"{i}: {body}", start=float(i)) for i in range(30)]
    chunks = chunk_segments(segs, max_tokens=2000, overlap=0)
    seen: set[str] = set()
    for c in chunks:
        for s in c:
            assert s.text not in seen, "with overlap=0, no segment should appear in two chunks"
            seen.add(s.text)


# ---------------------------------------------------------------------------
# Union covers original text — the property the reducer relies on
# ---------------------------------------------------------------------------

def test_chunk_union_covers_every_original_segment():
    body = "word " * 320
    originals = [_seg("speaker_1", f"original-{i}: {body}", start=float(i)) for i in range(25)]
    chunks = chunk_segments(originals, max_tokens=2000, overlap=400)

    union_texts = {s.text for c in chunks for s in c}
    for o in originals:
        assert o.text in union_texts, f"segment {o.text[:30]!r} fell out of every chunk"


# ---------------------------------------------------------------------------
# Oversized single turn — must be sentence-split
# ---------------------------------------------------------------------------

def test_oversized_turn_is_sentence_split_before_chunking():
    # One ~3000-token segment, then small ones.
    huge_text = ("This is sentence A. " * 600).strip()  # ~3000 tokens
    segs = [_seg("speaker_1", huge_text), _seg("speaker_2", "Reply.")]
    chunks = chunk_segments(segs, max_tokens=1000, overlap=100)

    # The huge segment must have been split into ≥ 2 sub-segments.
    all_segs = [s for c in chunks for s in c]
    speaker_1_segs = [s for s in all_segs if s.speaker == "speaker_1"]
    assert len(speaker_1_segs) >= 2, "oversized turn was not split"
    # And every chunk still fits the budget.
    assert _budget_safe(chunks, max_tokens=1000)


def test_split_oversized_turn_preserves_speaker_and_concatenates_to_original():
    huge = ("This is sentence A. " * 200).strip()  # ~1000 tokens
    seg = _seg("speaker_1", huge, start=0.0)
    parts = _split_oversized_turn(seg, max_tokens=300)
    assert len(parts) > 1
    assert all(p.speaker == "speaker_1" for p in parts)
    # Reconstruction: joining the sub-segment texts with single spaces yields
    # the original (modulo the sentence-split whitespace normalization).
    reconstructed = " ".join(p.text for p in parts)
    assert reconstructed == huge


def test_run_on_text_with_no_sentence_boundaries_falls_back_to_hard_split():
    # No `.`, `!`, or `?` in the text — sentence splitter can't help.
    runon = "x" * 8000  # ~2000 tokens, no sentence boundaries
    seg = _seg("speaker_1", runon)
    parts = _split_oversized_turn(seg, max_tokens=300)
    assert len(parts) > 1
    # Hard split preserves the text byte-for-byte across parts.
    assert "".join(p.text for p in parts) == runon


# ---------------------------------------------------------------------------
# _build_overlap — internal correctness
# ---------------------------------------------------------------------------

def test_build_overlap_picks_tail_within_budget():
    body = "word " * 100  # ~125 tokens per segment
    chunk = [_seg("s", f"{i}: {body}") for i in range(10)]
    tail, tokens = _build_overlap(chunk, overlap_tokens=200)
    # Should pull the last ~1–2 segments (each ~125 tok) without exceeding budget too far.
    assert 1 <= len(tail) <= 3
    assert tail == chunk[-len(tail):]   # tail comes from the end, in order


def test_build_overlap_with_zero_budget_is_empty():
    chunk = [_seg("s", "anything")]
    assert _build_overlap(chunk, overlap_tokens=0) == ([], 0)


# ---------------------------------------------------------------------------
# Pipeline constants — sanity
# ---------------------------------------------------------------------------

def test_constants_have_expected_relative_sizes():
    """Catch a footgun where someone bumps OVERLAP past MAX without realizing."""
    assert 0 < CHUNK_OVERLAP_TOKENS < CHUNK_MAX_TOKENS
    assert CHUNK_MAX_TOKENS >= 1000   # below this, the single-call path is moot
