"""Phase 3.5b C17 — flagged extraction pipeline integration tests.

Real store + migrated SQLite; every LLM/embedding seam monkeypatched.
The decisive tests: flag-off no-op, flag-on end-to-end, and bi-temporal
UPDATE correctness through the real execute_upsert path.
"""
from __future__ import annotations

import json

import pytest

from storage import kb, kb_graph
from storage.sqlite import _get_conn
from storage.vec import vec_available
from transcripts import store
from transcripts.kb_chunk import KBChunk
from transcripts.kb_extract import extract_session, kb_pipeline_enabled
from transcripts.extract import ExtractionResult
from transcripts.models import Derived, RawSegment, Session, SessionMetadata

pytestmark = pytest.mark.skipif(
    not vec_available(_get_conn()),
    reason="sqlite-vec not loaded on this connection",
)

SID = "kb-x-1"


@pytest.fixture(autouse=True)
def _world(monkeypatch):
    s = Session(
        session_id=SID,
        raw_diarization=[
            RawSegment(speaker="Ada", text="I'll ship the importer by Friday.", start=0.0, end=4.0),
            RawSegment(speaker="Bob", text="We decided SQLite for storage.", start=4.0, end=8.0),
        ],
        metadata=SessionMetadata(date="2026-06-04", source="test", tags=[]),
        derived=Derived(),
    )
    store.save_session(s)
    kb.save_chunks(SID, [KBChunk(0, [0, 1], "Ada: importer...\nBob: SQLite...", 12)])
    yield
    conn = _get_conn()
    conn.execute("DELETE FROM ingest_metrics WHERE session_id LIKE 'kb-x-%'")
    conn.execute("DELETE FROM obligations WHERE session_id LIKE 'kb-x-%'")
    conn.execute("DELETE FROM entity_mentions WHERE session_id LIKE 'kb-x-%'")
    conn.execute("DELETE FROM embeddings WHERE source_kind IN ('entity','obligation')")
    conn.execute("DELETE FROM entities")
    kb.delete_chunks_for_session(SID)
    conn.execute("DELETE FROM transcript_sessions WHERE session_id LIKE 'kb-x-%'")


EXTRACTION = ExtractionResult(
    entities=[
        {"type": "person", "canonical_name": "Ada Lovelace",
         "raw_mentions": ["Ada"], "turn_ids": [0]},
        {"type": "tool", "canonical_name": "SQLite",
         "raw_mentions": ["SQLite"], "turn_ids": [1]},
    ],
    obligations=[
        {"type": "action", "description": "Ada ships the importer by Friday",
         "source_quote": "I'll ship the importer by Friday",
         "turn_ids": [0], "owner_raw_text": "Ada Lovelace",
         "due_date_raw": "Friday", "status_inferred": "open"},
    ],
)


def _patch_stages(monkeypatch, *, upsert_action="ADD", upsert_target=None):
    from transcripts.upsert import UpsertDecision
    monkeypatch.setenv("ENABLE_KB_PIPELINE", "1")
    monkeypatch.setattr(
        "transcripts.kb_extract.extract_from_chunk",
        lambda text, header, turn_count=None: EXTRACTION,
    )
    monkeypatch.setattr(
        "transcripts.kb_extract.score_importance", lambda items: [7] * len(items),
    )
    monkeypatch.setattr(
        "transcripts.kb_extract.embed_texts",
        lambda texts, **kw: [[0.5] * 768 for _ in texts],
    )
    monkeypatch.setattr(
        "transcripts.kb_extract.decide_upsert",
        lambda new, similar: UpsertDecision(action=upsert_action, target_id=upsert_target),
    )


def test_flag_off_is_noop(monkeypatch):
    monkeypatch.delenv("ENABLE_KB_PIPELINE", raising=False)
    assert not kb_pipeline_enabled()
    assert extract_session(SID) is None
    assert _get_conn().execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0
    assert _get_conn().execute(
        "SELECT COUNT(*) FROM ingest_metrics WHERE session_id = ?", (SID,)
    ).fetchone()[0] == 0


def test_flag_on_end_to_end(monkeypatch):
    _patch_stages(monkeypatch)
    metrics = extract_session(SID)
    assert metrics is not None
    assert metrics["entities"] == 2
    assert metrics["inserted"] == 1

    # entities + mentions persisted
    ada = kb_graph.find_entity("person", "Ada Lovelace")
    assert ada is not None
    mentions = _get_conn().execute(
        "SELECT COUNT(*) FROM entity_mentions WHERE session_id = ?", (SID,)
    ).fetchone()[0]
    assert mentions >= 2

    # obligation persisted with importance + owner link + version
    obs = kb_graph.current_obligations(otype="action")
    assert len(obs) == 1
    ob = obs[0]
    assert ob["importance"] == 7
    assert ob["owner_entity_id"] == ada["id"]
    assert ob["model_version"]

    # all four stage metrics recorded
    stages = {
        r[0] for r in _get_conn().execute(
            "SELECT stage FROM ingest_metrics WHERE session_id = ?", (SID,)
        )
    }
    assert {"extract", "entity_resolution", "importance", "upsert"} <= stages


def test_er_merges_existing_entity(monkeypatch):
    _patch_stages(monkeypatch)
    pre = kb_graph.insert_entity("person", "Ada Lovelace", ["Ada L"])
    extract_session(SID)
    rows = _get_conn().execute(
        "SELECT COUNT(*) FROM entities WHERE type='person'"
    ).fetchone()[0]
    assert rows == 1  # merged, not duplicated
    ada = kb_graph.get_entity(pre)
    assert "Ada" in ada["props"]["raw_mentions"]  # surface forms unioned


def test_update_path_bitemporal(monkeypatch):
    # Seed an existing current obligation, then run with UPDATE decision.
    old_id = kb_graph.insert_obligation(
        {"type": "action", "description": "Ada will ship importer",
         "turn_ids": [0], "status_inferred": "open"},
        session_id=SID, model_version="x0",
    )
    kb_graph.save_source_embedding(
        "obligation", old_id, [0.5] * 768, model_id="nomic-embed-text:v1.5",
    )
    _patch_stages(monkeypatch, upsert_action="UPDATE", upsert_target=old_id)
    extract_session(SID)

    conn = _get_conn()
    old = conn.execute(
        "SELECT valid_to, superseded_by FROM obligations WHERE id = ?", (old_id,)
    ).fetchone()
    assert old["valid_to"] is not None
    new_id = old["superseded_by"]
    assert new_id
    new = conn.execute(
        "SELECT valid_to, description FROM obligations WHERE id = ?", (new_id,)
    ).fetchone()
    assert new["valid_to"] is None  # the new row is current
    # exactly one current action remains
    assert len(kb_graph.current_obligations(otype="action")) == 1


def test_llm_unavailable_aborts_cleanly(monkeypatch):
    from transcripts.llm import LLMUnavailable
    monkeypatch.setenv("ENABLE_KB_PIPELINE", "1")

    def _boom(text, header, turn_count=None):
        raise LLMUnavailable("redpill down")
    monkeypatch.setattr("transcripts.kb_extract.extract_from_chunk", _boom)
    assert extract_session(SID) is None  # no crash, session re-runnable
    assert _get_conn().execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0
