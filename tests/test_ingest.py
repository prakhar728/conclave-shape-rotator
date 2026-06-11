"""C4 gate — batch ingest, no LLM.

Asserts the contract documented in IMPLEMENTATION_PLAN.md §G9 / §H C4:

- Fixtures dir → N sessions, all with empty `derived`.
- Re-ingest is idempotent: no duplicate session_ids, raw unchanged.
- `--force` actually replaces raw under an unchanged session_id.
- **The LLM is never constructed** during ingest (monkeypatch
  `config.get_llm` to raise — ingest must succeed regardless).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import config
from storage import sqlite
from transcripts import store
from transcripts.ingest import ingest_path

FIXTURES = Path(__file__).parent / "fixtures" / "transcripts"


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(sqlite, "_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(sqlite, "_conn", None)
    sqlite.init_db()
    yield
    monkeypatch.setattr(sqlite, "_conn", None)


@pytest.fixture()
def llm_forbidden(monkeypatch):
    """Crash loudly if anything in the ingest path tries to instantiate the LLM."""
    def _boom(*a, **kw):
        raise AssertionError("ingest must not construct an LLM (config.get_llm called)")
    monkeypatch.setattr(config, "get_llm", _boom)
    yield


def test_ingest_dir_stores_sessions_with_empty_derived(tmp_db, llm_forbidden, tmp_path):
    # Two small Otter-style files in a fresh dir keeps the test fast.
    d = tmp_path / "samples"
    d.mkdir()
    (d / "Session A_May_20.txt").write_text(
        "Shaw  0:00\nhello A\n\nAlex (flashbots?)  0:05\nhi A\n\n", encoding="utf-8",
    )
    (d / "Session B_May_21.txt").write_text(
        "Shaw  0:00\nhello B\n\nSpeaker 1  0:04\nhi B\n\n", encoding="utf-8",
    )

    report = ingest_path(d)

    assert report.stored == 2
    assert report.skipped == 0
    assert report.failed == []
    sessions = store.list_sessions()
    assert len(sessions) == 2
    for s in sessions:
        assert s.derived.summary is None
        assert s.derived.signals is None
        assert s.derived.entities is None
        assert s.metadata.source == "otter"


def test_ingest_is_idempotent_no_duplicate_no_raw_change(tmp_db, llm_forbidden, tmp_path):
    f = tmp_path / "Standup_May_20.txt"
    f.write_text("Shaw  0:00\nhello\n\n", encoding="utf-8")

    first = ingest_path(f)
    assert first.stored == 1

    before = store.list_sessions()
    before_raw = [s.raw_diarization for s in before]
    before_ids = {s.session_id for s in before}

    second = ingest_path(f)
    assert second.stored == 0
    assert second.skipped == 1

    after = store.list_sessions()
    after_ids = {s.session_id for s in after}
    after_raw = [s.raw_diarization for s in after]
    assert after_ids == before_ids
    assert after_raw == before_raw  # raw bytes literally unchanged


def test_force_replaces_raw_under_same_session_id(tmp_db, llm_forbidden, tmp_path):
    f = tmp_path / "Daily_May_20.txt"
    f.write_text("Shaw  0:00\nfirst version\n\n", encoding="utf-8")
    ingest_path(f)
    sid = store.list_sessions()[0].session_id
    assert store.load_session(sid).raw_diarization[0].text == "first version"

    # Rewrite the same file with a different body — session_id (slug from
    # filename) stays the same, so without --force we'd be stuck on v1.
    f.write_text(
        "Shaw  0:00\nfirst version corrected\n\nAlex (flashbots?)  0:10\nand a follow-up\n\n",
        encoding="utf-8",
    )
    report = ingest_path(f, force=True)
    assert report.replaced == 1
    assert report.stored == 0

    reloaded = store.load_session(sid)
    assert reloaded.raw_diarization[0].text == "first version corrected"
    assert len(reloaded.raw_diarization) == 2


def test_dry_run_does_not_write(tmp_db, llm_forbidden, tmp_path):
    f = tmp_path / "x_May_20.txt"
    f.write_text("Shaw  0:00\nhi\n\n", encoding="utf-8")
    r = ingest_path(f, dry_run=True)
    assert r.stored == 1
    assert store.list_sessions() == []  # nothing landed in the DB


def test_empty_parse_is_reported_not_stored(tmp_db, llm_forbidden, tmp_path):
    """The 'Notes' file with no Otter headers should fail-soft, not crash."""
    f = tmp_path / "just-notes.txt"
    f.write_text("May 19, 2026\nMeeting May 19, 2026 at 15:55 EDT - Transcript\n", encoding="utf-8")
    r = ingest_path(f)
    assert r.stored == 0
    assert r.failed and "no segments" in r.failed[0][1]
    assert store.list_sessions() == []


def test_ingest_real_cohort_fixtures_no_llm(tmp_db, llm_forbidden):
    """Smoke: the 13 real cohort transcripts ingest end-to-end with no LLM."""
    if not FIXTURES.is_dir() or not list(FIXTURES.glob("*.txt")):
        # The .expected.yaml/.md live in git; the real .txt transcripts are
        # gitignored, so they're absent in fresh checkouts / CI.
        pytest.skip("real cohort transcripts not present (gitignored)")
    r = ingest_path(FIXTURES)
    # 13 files; the BOM "Notes" one is the known non-Otter exception.
    assert r.stored >= 10
    # No crashes — failed entries are surfaced but never crash the batch.
    for path, err in r.failed:
        assert "no segments" in err  # only the known-empty case fails
    # raw is non-empty across the board.
    for s in store.list_sessions():
        assert len(s.raw_diarization) > 0
        assert s.derived.summary is None  # nothing enriched in ingest


# ---------------------------------------------------------------------------
# P5 (§D.1): opt-in --owner-from-first-speaker. Default leaves owner=None.
# ---------------------------------------------------------------------------

def test_ingest_default_leaves_owner_none(tmp_db, llm_forbidden, tmp_path):
    """Phase-1-friendly default: no owner_from_first_speaker → owner stays
    None. This is what keeps existing tests + the existing dashboard
    working unchanged."""
    f = tmp_path / "Session_C_May_20.txt"
    f.write_text("Shaw  0:00\nhello\n\nAlex (flashbots?)  0:05\nhi\n\n", encoding="utf-8")
    ingest_path(f)
    sessions = store.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].metadata.owner is None


def test_ingest_owner_from_first_speaker_opt_in_stamps_owner(tmp_db, llm_forbidden, tmp_path, monkeypatch):
    """With the flag, the first speaker in resolved_speakers whose
    record_id is set becomes metadata.owner. Shaw resolves via
    MOCK_DIRECTORY to shaw-walters.

    MOCK_DIRECTORY is built at import time from a roster dir that's absent in
    fresh checkouts / CI, so patch it explicitly (mirrors test_enrich_mapreduce)
    to keep this test hermetic instead of depending on local roster data."""
    from transcripts import identity
    monkeypatch.setattr(identity, "MOCK_DIRECTORY", {"shaw": "shaw-walters"})
    f = tmp_path / "Session_D_May_20.txt"
    f.write_text("Shaw  0:00\nhello\n\nAlex (flashbots?)  0:05\nhi\n\n", encoding="utf-8")
    ingest_path(f, owner_from_first_speaker=True)
    sessions = store.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].metadata.owner == "shaw-walters"
