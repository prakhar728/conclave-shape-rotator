"""Ground-truth writes — the flywheel (docs/plans/transcript-refine.md §6, §15).

When a user confirms/tags an entity or corrects a word, write BOTH the v2
annotation AND the per-user vocab entry, so the dictionary grows and future
candidate detection gets smarter. The human's value is authoritative — a user
tag's type wins over any nlp guess (last-write-wins on the vocab key).
"""
from __future__ import annotations

from typing import Optional

from transcripts import candidate, store, vocab
from transcripts.models import CandidateAnnotation, TokenSpan


def tag_entity(
    session_id: str,
    segment_id: int,
    token_start: int,
    token_end: int,
    surface: str,
    type: Optional[str],
    user_id: str,
    *,
    is_entity: bool = True,
) -> CandidateAnnotation:
    """User tags a span as an entity of `type`. Writes a `source="user"`,
    `state="known"` annotation to the v2 draft AND upserts the user's vocab
    (provenance="user" → wins over any prior nlp guess)."""
    ann = CandidateAnnotation(
        span=TokenSpan(segment_id=segment_id, token_start=token_start, token_end=token_end),
        surface=surface, state="known", type=type, source="user",
    )
    store.add_annotation(session_id, ann)
    vocab.put(user_id, surface, is_entity=is_entity, type=type, provenance="user")
    return ann


def correct_word(
    session_id: str,
    segment_id: int,
    token_idx: int,
    new_text: str,
    user_id: str,
) -> str:
    """User corrects a word. Always edits the v2 token. Then the POS filter
    decides: a NOUN/PROPN/OOV correction is a likely graph-worthy term → write it
    to vocab ('correction' provenance); a grammar fix is text-only, never touches
    vocab/graph. Returns 'promote' or 'text'."""
    store.edit_token(session_id, segment_id, token_idx, new_text)
    decision = candidate.classify_correction(new_text)
    if decision == "promote":
        vocab.put(user_id, new_text, is_entity=True, provenance="correction")
    return decision
