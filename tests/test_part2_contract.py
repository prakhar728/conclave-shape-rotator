"""Part 1 → Part 2 contract drift-guard (C9).

Part 2 (graph synthesis, built in a separate worktree) consumes the approved v2
+ per-user vocab. These tests PIN that shape: if Part 1's later work renames a
field, this fails LOUD instead of silently breaking Part 2. Update Part 2 AND
this pin together. See docs/plans/graph-synthesis.md.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from transcripts import store, vocab
from transcripts.models import (
    CandidateAnnotation,
    RawSegment,
    Session,
    SessionMetadata,
    TokenSpan,
    TranscriptV2,
    V2Segment,
    VocabEntry,
)

EXPECTED_FIELDS = {
    TranscriptV2: {"session_id", "status", "segments", "annotations", "approved_at", "insights_stale"},
    V2Segment: {"segment_id", "speaker_label", "speaker_name", "tokens"},
    TokenSpan: {"segment_id", "token_start", "token_end"},
    CandidateAnnotation: {"span", "surface", "state", "type", "source", "confidence"},
    VocabEntry: {"user_id", "surface_norm", "is_entity", "type", "canonical_id", "provenance"},
}


@pytest.mark.parametrize("model, fields", list(EXPECTED_FIELDS.items()))
def test_contract_fields_pinned(model, fields):  # C9-3 drift guard
    assert set(model.model_fields) == fields, (
        f"{model.__name__} contract changed — update Part 2 (graph synthesis) "
        f"and this pin together."
    )


def test_annotation_state_and_source_values():  # C9-4
    span = TokenSpan(segment_id=0, token_start=0, token_end=1)
    for st in ("known", "candidate", "oov"):
        CandidateAnnotation(span=span, surface="x", state=st)
    for src in ("nlp", "correction", "user"):
        CandidateAnnotation(span=span, surface="x", state="known", source=src)
    with pytest.raises(ValidationError):
        CandidateAnnotation(span=span, surface="x", state="bogus")


def test_approved_v2_contract_shape():  # C9-1 — exactly what Part 2 reads
    store.save_session(Session(
        session_id="c9",
        raw_diarization=[RawSegment(speaker="speaker_1", text="hello world")],
        metadata=SessionMetadata(date="2026-06-22", source="t"),
    ))
    store.create_v2_draft("c9")
    store.approve_v2("c9")
    v2 = store.load_v2("c9")
    assert v2.status == "approved" and v2.approved_at is not None
    seg = v2.segments[0]
    assert all(hasattr(seg, f) for f in ("segment_id", "speaker_label", "speaker_name", "tokens"))
    # the corrected-segments helper Part 2 also consumes: Part 2 reads speaker+text;
    # start/end were added (#41 timestamps for the transcript DTO) and are ignored by
    # the KB, so assert the contract is a SUPERSET of {speaker, text}, not exact.
    segs = store.v2_segments_or_raw("c9")
    assert {"speaker", "text"} <= set(segs[0].keys())


def test_vocab_contract_shape():  # C9-2
    vocab.put("c9u", "DStack", is_entity=True, type="project", provenance="user")
    entry = vocab.get("c9u", "DStack")
    assert set(entry.model_dump().keys()) == {
        "user_id", "surface_norm", "is_entity", "type", "canonical_id", "provenance",
    }
