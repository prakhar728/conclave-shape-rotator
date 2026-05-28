"""Layer-1 transcript pipeline: parse, enrich (fake LLM), store, immutability."""
from __future__ import annotations

import json
import os

import pytest

from transcripts import store
from transcripts.enrich import enrich_session, transcript_text
from transcripts.models import PIPELINE_VERSION
from transcripts.parse import build_session, parse_transcript
from transcripts.sources import NormalizedInput, read_obj

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxterm_session.json")


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Point the shared SQLite store at an isolated temp file for this test."""
    from storage import sqlite

    monkeypatch.setattr(sqlite, "_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(sqlite, "_conn", None)
    sqlite.init_db()
    yield
    monkeypatch.setattr(sqlite, "_conn", None)


class FakeLLM:
    """Stands in for config.get_llm() — returns a canned JSON response."""

    def __init__(self, payload: dict):
        self._payload = payload
        self.last_messages = None

    def invoke(self, messages):
        self.last_messages = messages
        return type("Resp", (), {"content": json.dumps(self._payload)})()


def _voxterm_raw() -> dict:
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


# --- parsing / VoxTerm merge ---

def test_parse_voxterm_batch_maps_fields():
    session = parse_transcript(_voxterm_raw())

    assert session.session_id == "transcript-2026-05-27-1430-voxterm"  # from record_id
    assert session.metadata.source == "voxterm"  # inferred from origin_device
    assert session.metadata.date == "2026-05-27"  # from started_at
    assert session.metadata.origin_device.startswith("b0c1d2e3")
    assert session.metadata.location == "cohort-room-2"
    assert session.metadata.resolved_speakers == {}
    assert session.metadata.tags == []
    assert session.metadata.pipeline_version == PIPELINE_VERSION

    # VoxTerm single timestamp `t` maps to start, end stays None.
    seg = session.raw_diarization[0]
    assert seg.speaker == "speaker_1"
    assert seg.start == 2.1
    assert seg.end is None
    assert len(session.raw_diarization) == 4

    # derived starts entirely null.
    assert session.derived.summary is None
    assert session.derived.signals is None
    assert session.derived.entities is None
    assert session.derived.graph_nodes is None


def test_parse_generic_segment_list_with_start_end():
    raw = [
        {"speaker": "speaker_1", "start": 0.0, "end": 3.2, "text": "Hello there."},
        {"speaker": "speaker_2", "start": 3.5, "end": 6.0, "text": "General Kenobi."},
        {"speaker": "speaker_1", "start": 6.1, "end": 6.1, "text": "   "},
    ]
    session = parse_transcript(raw, source="whisper", tags=["demo"])

    assert session.metadata.source == "whisper"
    assert session.metadata.tags == ["demo"]
    assert len(session.raw_diarization) == 2  # blank segment dropped
    assert session.raw_diarization[0].end == 3.2
    # content-hash id since there's no record_id.
    assert session.session_id.startswith(f"{session.metadata.date}-whisper-")


def test_parse_multiple_batches_concatenate_in_order():
    raw = [
        {"record_id": "r1", "batch_index": 1, "segments": [{"t": 10, "speaker": "speaker_1", "text": "second"}]},
        {"record_id": "r1", "batch_index": 0, "segments": [{"t": 1, "speaker": "speaker_1", "text": "first"}]},
    ]
    session = parse_transcript(raw)
    assert session.session_id == "r1"
    assert [s.text for s in session.raw_diarization] == ["first", "second"]


# --- build_session (post-C2 generic normalizer) ---

def test_build_session_uses_provenance_session_id_then_falls_back_to_hash():
    # provenance.session_id present → used verbatim.
    ni = NormalizedInput(
        segments=[{"speaker": "Shaw", "text": "hi", "start": 0.0, "end": None}],
        provenance={"source": "otter", "session_id": "my-meeting", "date": "2026-05-20"},
        source="otter",
    )
    s = build_session(ni)
    assert s.session_id == "my-meeting"
    assert s.metadata.date == "2026-05-20"
    assert s.metadata.source == "otter"

    # No provenance.session_id → deterministic content hash, prefixed by date+source.
    ni2 = NormalizedInput(
        segments=[{"speaker": "Shaw", "text": "hi", "start": 0.0, "end": None}],
        provenance={"source": "otter", "date": "2026-05-20"},
        source="otter",
    )
    s2 = build_session(ni2)
    assert s2.session_id.startswith("2026-05-20-otter-")


def test_build_session_drops_blank_segments_and_sorts_by_start():
    ni = NormalizedInput(
        segments=[
            {"speaker": "B", "text": "second", "start": 2.0, "end": None},
            {"speaker": "A", "text": "first", "start": 1.0, "end": None},
            {"speaker": "C", "text": "   ", "start": 3.0, "end": None},
        ],
        provenance={"source": "otter", "session_id": "x", "date": "2026-05-20"},
        source="otter",
    )
    s = build_session(ni)
    assert [seg.text for seg in s.raw_diarization] == ["first", "second"]


def test_parse_transcript_routes_through_sources_read_obj():
    """The historical entry point still works because it now dispatches to sources."""
    raw = {"segments": [{"t": 0.0, "speaker": "speaker_1", "text": "hello"}],
           "record_id": "abc", "origin_device": "dev"}
    s = parse_transcript(raw)
    assert s.session_id == "abc"
    assert s.metadata.source == "voxterm"


# --- enrichment ---

def test_enrich_fills_derived_with_typed_signals():
    session = parse_transcript(_voxterm_raw())
    fake = FakeLLM({
        "summary": "The team locked the hybrid matcher as v1.",
        "signals": [
            {"kind": "decision", "text": "Ship tag-based matching first.", "speakers": ["speaker_1"]},
            {"kind": "action_item", "text": "Wire VoxTerm transcripts in by Friday.", "speakers": ["speaker_1"]},
            {"kind": "bogus_kind", "text": "Coerced to insight.", "speakers": []},
            {"kind": "insight", "text": ""},
        ],
        "entities": [
            {"name": "matching engine", "type": "project", "evidence": "main topic"},
            {"name": "VoxTerm", "type": "weird", "evidence": "data source"},
            {"name": "", "type": "person"},
        ],
    })

    enrich_session(session, llm=fake)
    d = session.derived

    assert d.summary == "The team locked the hybrid matcher as v1."
    # blank-text signal dropped; bad kind coerced to "insight".
    assert len(d.signals) == 3
    assert {s.kind for s in d.signals} == {"decision", "action_item", "insight"}
    # blank-name entity dropped; bad type coerced to "concept".
    assert len(d.entities) == 2
    assert any(e.name == "VoxTerm" and e.type == "concept" for e in d.entities)

    # The transcript was actually passed to the model, wrapped as data.
    human = fake.last_messages[-1].content
    assert "<transcript>" in human and "speaker_1" in human


def test_transcript_text_renders_speaker_lines():
    session = parse_transcript(_voxterm_raw())
    text = transcript_text(session)
    assert text.startswith("[speaker_1] So for the matching engine")
    assert text.count("\n") == 3


# --- storage + immutability ---

def test_store_roundtrip_and_listing(tmp_db):
    session = parse_transcript(_voxterm_raw())
    enrich_session(session, llm=FakeLLM({"summary": "s", "signals": [], "entities": []}))
    store.save_session(session)

    loaded = store.load_session(session.session_id)
    assert loaded is not None
    assert loaded.session_id == session.session_id
    assert loaded.derived.summary == "s"
    assert len(loaded.raw_diarization) == 4

    by_source = store.list_sessions(source="voxterm")
    assert [s.session_id for s in by_source] == [session.session_id]
    assert store.list_sessions(date_from="2026-06-01") == []  # out of range


def test_raw_diarization_is_immutable_across_resave(tmp_db):
    session = parse_transcript(_voxterm_raw())
    store.save_session(session)

    # Simulate a later stage that (wrongly) tries to rewrite raw + (rightly) derived.
    tampered = session.model_copy(deep=True)
    tampered.raw_diarization = tampered.raw_diarization[:1]  # drop segments
    tampered.derived.summary = "added later"
    store.save_session(tampered)

    reloaded = store.load_session(session.session_id)
    assert len(reloaded.raw_diarization) == 4  # raw NOT overwritten
    assert reloaded.derived.summary == "added later"  # derived DID move forward
