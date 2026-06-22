"""Part 1 increment 1b — v2 model + store seams (V2-1..V2-9).

Store-level tests (real temp SQLite via conftest). Each test uses a unique
session_id for isolation. The load-bearing invariant: edits land on `v2`;
`raw_diarization` is never mutated.
"""
from __future__ import annotations

import pytest

from transcripts import store
from transcripts.models import (
    CandidateAnnotation,
    RawSegment,
    Session,
    SessionMetadata,
    TokenSpan,
)


def _saved(sid: str) -> Session:
    s = Session(
        session_id=sid,
        raw_diarization=[
            RawSegment(speaker="speaker_1", text="we use the DStack protocol"),
            RawSegment(speaker="speaker_2", text="great lets ship it"),
        ],
        metadata=SessionMetadata(date="2026-06-19", source="test"),
    )
    store.save_session(s)
    return s


def test_v2_created_in_draft():  # V2-1
    _saved("v2-1")
    v2 = store.create_v2_draft("v2-1")
    assert v2.status == "draft"
    assert v2.approved_at is None
    # v2 mirrors raw at creation
    assert v2.segments[0].text == "we use the DStack protocol"
    assert v2.segments[0].speaker_label == "speaker_1"
    assert v2.segments[0].speaker_name is None


def test_approve_transitions_status():  # V2-2
    _saved("v2-2")
    store.create_v2_draft("v2-2")
    v2 = store.approve_v2("v2-2")
    assert v2.status == "approved"
    assert v2.approved_at is not None


def test_approve_is_idempotent():  # V2-3
    _saved("v2-3")
    store.create_v2_draft("v2-3")
    first = store.approve_v2("v2-3")
    again = store.approve_v2("v2-3")
    assert again.status == "approved"
    assert again.approved_at == first.approved_at  # idempotent, keeps timestamp


def test_word_edit_writes_v2_not_raw():  # V2-4
    _saved("v2-4")
    store.create_v2_draft("v2-4")
    raw_before = [s.model_dump() for s in store.load_session("v2-4").raw_diarization]
    store.edit_token("v2-4", 0, 3, "Dstack")  # "DStack" -> "Dstack"
    v2 = store.load_v2("v2-4")
    assert v2.segments[0].tokens[3] == "Dstack"
    raw_after = [s.model_dump() for s in store.load_session("v2-4").raw_diarization]
    assert raw_after == raw_before


def test_raw_immutable_under_all_edits():  # V2-5
    _saved("v2-5")
    store.create_v2_draft("v2-5")
    sess_before = store.load_session("v2-5")
    raw_before = [s.model_dump() for s in sess_before.raw_diarization]
    store.edit_token("v2-5", 0, 3, "Dstack")
    store.add_annotation(
        "v2-5",
        CandidateAnnotation(
            span=TokenSpan(segment_id=0, token_start=3, token_end=4),
            surface="Dstack", state="candidate",
        ),
    )
    store.assign_speaker("v2-5", 0, "Alice")
    store.approve_v2("v2-5")
    sess_after = store.load_session("v2-5")
    assert [s.model_dump() for s in sess_after.raw_diarization] == raw_before
    assert sess_after.metadata.source == "test"  # provenance unchanged


def test_span_annotation_roundtrips():  # V2-6
    _saved("v2-6")
    store.create_v2_draft("v2-6")
    store.add_annotation(
        "v2-6",
        CandidateAnnotation(
            span=TokenSpan(segment_id=0, token_start=3, token_end=5),
            surface="DStack protocol", state="candidate", type="project", source="user",
        ),
    )
    v2 = store.load_v2("v2-6")
    assert len(v2.annotations) == 1
    a = v2.annotations[0]
    assert (a.surface, a.state, a.type, a.source) == (
        "DStack protocol", "candidate", "project", "user",
    )
    assert (a.span.segment_id, a.span.token_start, a.span.token_end) == (0, 3, 5)


def test_speaker_assignment_independent_of_raw():  # V2-7
    _saved("v2-7")
    store.create_v2_draft("v2-7")
    store.assign_speaker("v2-7", 0, "Alice")
    v2 = store.load_v2("v2-7")
    assert v2.segments[0].speaker_name == "Alice"
    assert v2.segments[0].speaker_label == "speaker_1"  # raw label kept
    assert store.load_session("v2-7").raw_diarization[0].speaker == "speaker_1"


def test_reload_after_approve_preserves():  # V2-8
    _saved("v2-8")
    store.create_v2_draft("v2-8")
    store.edit_token("v2-8", 1, 0, "Great")
    store.add_annotation(
        "v2-8",
        CandidateAnnotation(
            span=TokenSpan(segment_id=0, token_start=3, token_end=4),
            surface="DStack", state="oov",
        ),
    )
    store.assign_speaker("v2-8", 0, "Alice")
    store.approve_v2("v2-8")
    v2 = store.load_v2("v2-8")
    assert v2.status == "approved"
    assert v2.segments[1].tokens[0] == "Great"
    assert v2.segments[0].speaker_name == "Alice"
    assert len(v2.annotations) == 1


def test_span_anchors_survive_length_change():  # V2-9
    _saved("v2-9")
    store.create_v2_draft("v2-9")
    # annotate a LATER token ("protocol", idx 4)
    store.add_annotation(
        "v2-9",
        CandidateAnnotation(
            span=TokenSpan(segment_id=0, token_start=4, token_end=5),
            surface="protocol", state="candidate",
        ),
    )
    # edit an EARLIER token to a much longer string (char length changes,
    # token COUNT does not) → downstream span must still anchor correctly
    store.edit_token("v2-9", 0, 2, "the-entire-massively-longer-word")
    v2 = store.load_v2("v2-9")
    a = v2.annotations[0]
    assert a.span.token_start == 4
    assert v2.segments[0].tokens[a.span.token_start] == "protocol"


def test_edit_after_approve_rejected():  # §4 contract / V2-3
    _saved("v2-x")
    store.create_v2_draft("v2-x")
    store.approve_v2("v2-x")
    with pytest.raises(ValueError):
        store.edit_token("v2-x", 0, 0, "nope")


def test_v2_cascades_on_session_delete():  # FK ON DELETE CASCADE (0015)
    from storage import sqlite as ss
    _saved("v2-casc")
    store.create_v2_draft("v2-casc")
    assert store.load_v2("v2-casc") is not None
    ss._get_conn().execute(
        "DELETE FROM transcript_sessions WHERE session_id = ?", ("v2-casc",)
    )
    assert store.load_v2("v2-casc") is None  # cascaded away with the session
