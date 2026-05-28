"""Turn-aware chunker with overlap + oversized-turn split.

`IMPLEMENTATION_PLAN.md` §G5. Splits a session's segments into
token-bounded chunks suitable for the map step of map-reduce enrichment
(C8). Two non-obvious rules (revisions #9 and #10):

1. **A single turn can exceed the chunk budget.** A 20-min monologue is
   one ``RawSegment``. The chunker must sentence-split such turns so they
   don't trigger an infinite loop or single-chunk overflow.

2. **The union of chunks covers the original text.** Adjacent chunks
   overlap by ``CHUNK_OVERLAP_TOKENS`` so a signal that straddles a
   boundary is seen by both partial enrich calls — the reduce step then
   dedupes. Splitting an oversized turn produces sub-segments whose
   concatenation equals the original turn's text (white-space preserved
   at the join), so "covers original" still holds after split.

Pure module: no LLM, no I/O. The heuristic ``estimate_tokens`` is
deliberately cheap (chars × ``TOKENS_PER_CHAR``) — the budget already
carries 2 KB of headroom so we don't need tokenizer accuracy.
"""
from __future__ import annotations

import re
from typing import List

from transcripts.config import CHUNK_MAX_TOKENS, CHUNK_OVERLAP_TOKENS, TOKENS_PER_CHAR
from transcripts.models import RawSegment


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def estimate_tokens(text: str) -> int:
    """Cheap token-count heuristic. English averages ~4 chars/token."""
    if not text:
        return 0
    return int(len(text) * TOKENS_PER_CHAR)


def _segment_tokens(seg: RawSegment) -> int:
    """Tokens for the rendered line — includes a small overhead for the
    ``[speaker] `` prefix that the enrich prompt prepends."""
    return estimate_tokens(seg.text) + estimate_tokens(seg.speaker) + 4


def chunk_segments(
    segments: List[RawSegment],
    max_tokens: int = CHUNK_MAX_TOKENS,
    overlap: int = CHUNK_OVERLAP_TOKENS,
) -> List[List[RawSegment]]:
    """Greedy turn-aware chunking with trailing-segment overlap.

    Returns ``[[segments]]`` (one chunk containing every segment) when the
    whole session fits in budget — preserves the single-LLM-call fast path
    for short transcripts.
    """
    if not segments:
        return []

    # First: expand any over-budget single segments into sentence-split
    # sub-segments. After this pass, no individual segment exceeds budget.
    expanded: List[RawSegment] = []
    for seg in segments:
        if _segment_tokens(seg) <= max_tokens:
            expanded.append(seg)
        else:
            expanded.extend(_split_oversized_turn(seg, max_tokens))

    # Fast path: everything fits in one chunk.
    total = sum(_segment_tokens(s) for s in expanded)
    if total <= max_tokens:
        return [expanded]

    chunks: List[List[RawSegment]] = []
    current: List[RawSegment] = []
    current_tokens = 0

    for seg in expanded:
        seg_tokens = _segment_tokens(seg)
        if current and current_tokens + seg_tokens > max_tokens:
            chunks.append(current)
            # Seed the next chunk with the trailing overlap so a boundary-
            # straddling signal is seen by both partial enrich calls.
            current, current_tokens = _build_overlap(current, overlap)
            # Trim overlap from the front until ``seg`` itself fits — a
            # tightly-packed segment must always make it into the new chunk,
            # even if that means giving up some/all of the overlap.
            while current and current_tokens + seg_tokens > max_tokens:
                dropped = current.pop(0)
                current_tokens -= _segment_tokens(dropped)
        current.append(seg)
        current_tokens += seg_tokens

    if current:
        chunks.append(current)

    return chunks


def _build_overlap(prev_chunk: List[RawSegment], overlap_tokens: int) -> tuple[List[RawSegment], int]:
    """Tail of ``prev_chunk`` summing to ≤ ``overlap_tokens``, oldest first.

    Returns (overlap_segments, their_token_count). Returns ``([], 0)`` when
    ``overlap_tokens <= 0`` — useful for tests that want non-overlapping
    chunks to verify the boundary behavior in isolation.
    """
    if overlap_tokens <= 0 or not prev_chunk:
        return [], 0
    tail: List[RawSegment] = []
    acc = 0
    for seg in reversed(prev_chunk):
        t = _segment_tokens(seg)
        if acc + t > overlap_tokens and tail:
            break
        tail.insert(0, seg)
        acc += t
    return tail, acc


def _split_oversized_turn(seg: RawSegment, max_tokens: int) -> List[RawSegment]:
    """Sentence-split a single turn whose body exceeds ``max_tokens``.

    Sub-segments inherit ``speaker`` and ``start`` from the original; the
    join character between sub-segments is a single space, so concatenating
    their ``text`` (space-separated) reconstructs the original body.
    """
    sentences = _SENTENCE_SPLIT_RE.split(seg.text)
    if len(sentences) <= 1:
        # No sentence boundaries found (e.g. one giant run-on). Fall back
        # to a hard character-split so we still respect the budget.
        return _hard_split(seg, max_tokens)

    out: List[RawSegment] = []
    buf: List[str] = []
    speaker_overhead = estimate_tokens(seg.speaker) + 4
    for sentence in sentences:
        # Budget by the actual joined text, not a running sum — the
        # inter-sentence single-space and integer-truncation otherwise drift
        # the count below the real sub-segment size, which then defeats the
        # post-split safety check and forces an unnecessary hard split.
        trial_text = " ".join(buf + [sentence]) if buf else sentence
        trial_tokens = estimate_tokens(trial_text) + speaker_overhead
        if buf and trial_tokens > max_tokens:
            out.append(RawSegment(
                speaker=seg.speaker,
                text=" ".join(buf),
                start=seg.start,
                end=None,
            ))
            buf = [sentence]
        else:
            buf.append(sentence)
    if buf:
        out.append(RawSegment(
            speaker=seg.speaker,
            text=" ".join(buf),
            start=seg.start,
            end=seg.end,
        ))
    # If the very first sentence is itself over budget, the buf-append above
    # produced one over-budget sub-segment; recurse via hard split on those.
    safe: List[RawSegment] = []
    for sub in out:
        if _segment_tokens(sub) <= max_tokens:
            safe.append(sub)
        else:
            safe.extend(_hard_split(sub, max_tokens))
    return safe


def _hard_split(seg: RawSegment, max_tokens: int) -> List[RawSegment]:
    """Last-resort character-window split for a sentence that alone overflows.

    Pathological in practice (>~24k chars for a single sentence), but keeps
    the contract that no chunk ever exceeds the budget.
    """
    char_budget = max(1, int((max_tokens - estimate_tokens(seg.speaker) - 4) / TOKENS_PER_CHAR))
    text = seg.text
    out: List[RawSegment] = []
    for i in range(0, len(text), char_budget):
        out.append(RawSegment(
            speaker=seg.speaker,
            text=text[i:i + char_budget],
            start=seg.start,
            end=seg.end if i + char_budget >= len(text) else None,
        ))
    return out
