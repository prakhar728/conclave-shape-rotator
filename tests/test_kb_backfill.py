"""Phase 3.5a C11 — backfill script behavior (import-and-call, fake embed)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from storage import kb
from storage.sqlite import _get_conn
from storage.vec import vec_available
from transcripts import store
from transcripts.models import Derived, RawSegment, Session, SessionMetadata

pytestmark = pytest.mark.skipif(
    not vec_available(_get_conn()),
    reason="sqlite-vec not loaded on this connection",
)

SCRIPT = Path(__file__).parent.parent / "scripts" / "chunk_and_embed_existing.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("backfill", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def two_sessions():
    sids = ["kb-bf-1", "kb-bf-2"]
    for sid in sids:
        store.save_session(Session(
            session_id=sid,
            raw_diarization=[RawSegment(speaker="A", text=f"hello from {sid}", start=0.0, end=1.0)],
            metadata=SessionMetadata(date="2026-06-04", source="test", tags=[]),
            derived=Derived(),
        ))
    yield sids
    for sid in sids:
        kb.delete_chunks_for_session(sid)
        _get_conn().execute("DELETE FROM embeddings WHERE source_id LIKE ?", (f"{sid}%",))
        _get_conn().execute("DELETE FROM transcript_sessions WHERE session_id = ?", (sid,))


def test_backfill_only_and_skip_indexed(two_sessions, monkeypatch, capsys):
    monkeypatch.setattr(
        "transcripts.kb_pipeline.embed_texts",
        lambda texts, **kw: [[0.5] * 768 for _ in texts],
    )
    mod = _load_script()

    # --only indexes exactly one session
    monkeypatch.setattr(sys, "argv", ["backfill", "--only", "kb-bf-1"])
    assert mod.main() == 0
    assert kb.query_chunks_for_session("kb-bf-1")
    assert kb.query_chunks_for_session("kb-bf-2") == []

    # --skip-indexed leaves the already-indexed session untouched
    before = kb.query_chunks_for_session("kb-bf-1")[0]["created_at"]
    monkeypatch.setattr(sys, "argv", ["backfill", "--only", "kb-bf-1", "--skip-indexed"])
    assert mod.main() == 0
    after = kb.query_chunks_for_session("kb-bf-1")[0]["created_at"]
    assert after == before
    out = capsys.readouterr().out
    assert "1 skipped" in out


def test_backfill_idempotent_rerun(two_sessions, monkeypatch):
    monkeypatch.setattr(
        "transcripts.kb_pipeline.embed_texts",
        lambda texts, **kw: [[0.5] * 768 for _ in texts],
    )
    mod = _load_script()
    monkeypatch.setattr(sys, "argv", ["backfill", "--only", "kb-bf-2"])
    assert mod.main() == 0
    assert mod.main() == 0  # re-run, no --skip-indexed: full re-index
    rows = kb.query_chunks_for_session("kb-bf-2")
    assert len(rows) == 1  # replaced, not duplicated
    cnt = _get_conn().execute(
        "SELECT COUNT(*) FROM embeddings WHERE source_id LIKE 'kb-bf-2%'"
    ).fetchone()[0]
    assert cnt == 1


def test_backfill_unknown_session(two_sessions, monkeypatch):
    mod = _load_script()
    monkeypatch.setattr(sys, "argv", ["backfill", "--only", "nope"])
    assert mod.main() == 1
