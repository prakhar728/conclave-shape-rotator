"""Part 1 increment 3 — the KB build sources from the approved v2 (G-5).

So a user's approved corrections actually reach the graph. Draft (un-approved)
v2 and missing v2 both fall back to the immutable raw.
"""
from __future__ import annotations

import transcripts.kb_pipeline as kbp
from transcripts import store
from transcripts.models import RawSegment, Session, SessionMetadata


def _save(sid: str, text: str = "hello world") -> None:
    store.save_session(
        Session(
            session_id=sid,
            raw_diarization=[RawSegment(speaker="speaker_1", text=text)],
            metadata=SessionMetadata(date="2026-06-19", source="test"),
        )
    )


def test_helper_uses_approved_v2():  # G-5
    _save("k1")
    store.create_v2_draft("k1")
    store.edit_token("k1", 0, 0, "HELLO")
    store.approve_v2("k1")
    assert store.v2_segments_or_raw("k1")[0]["text"] == "HELLO world"


def test_helper_falls_back_to_raw():  # G-5 fallback
    _save("k2")
    # no v2 → raw
    assert store.v2_segments_or_raw("k2")[0]["text"] == "hello world"
    # draft (NOT approved) → still raw (KB only builds from approved corrections)
    store.create_v2_draft("k2")
    store.edit_token("k2", 0, 0, "HELLO")
    assert store.v2_segments_or_raw("k2")[0]["text"] == "hello world"


def test_approved_v2_uses_confirmed_speaker():
    _save("k3")
    store.create_v2_draft("k3")
    store.assign_speaker("k3", 0, "Alice")
    store.approve_v2("k3")
    assert store.v2_segments_or_raw("k3")[0]["speaker"] == "Alice"


def test_index_session_chunks_corrected_text(monkeypatch):  # G-5 integration
    captured: dict = {}

    def spy_chunk(segs):
        captured["segs"] = segs
        return []  # short-circuit the rest of indexing; we only check the source

    monkeypatch.setattr(kbp, "chunk_transcript", spy_chunk)
    monkeypatch.setattr(kbp, "embed_texts", lambda texts, **kw: [])
    _save("k4")
    store.create_v2_draft("k4")
    store.edit_token("k4", 0, 0, "HELLO")
    store.approve_v2("k4")
    kbp.index_session("k4")
    assert captured["segs"][0]["text"] == "HELLO world"
