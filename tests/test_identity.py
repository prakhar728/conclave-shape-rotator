"""C5 gate — mock identity linkage.

Asserts the contract documented in IMPLEMENTATION_PLAN.md §G2 / §H C5:

- Known cohort name → mock record_id; unknown / anonymous → unresolved.
- Parenthetical labels (``"Alex (flashbots?)"``) strip on the lookup side
  but stay verbatim on the raw segment.
- First-name shortcut works **only when unique**; ambiguous first names
  do not resolve (a wrong link is worse than no link).
- Roster aliases declared inside ``name:`` parentheticals resolve too.
- Ingest pipeline populates ``resolved_speakers``.
- ``link_identities`` re-links existing sessions after the directory grows.
- Missing cohort-data path → empty directory, no crash.
- **No LLM is ever constructed** — `config.get_llm` raises if touched.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import config
from storage import sqlite
from transcripts import identity, store
from transcripts.identity import (
    MOCK_DIRECTORY,
    _load_mock_directory,
    _normalize_name,
    extract_affiliation,
    link_identities,
    resolve_identity,
    resolve_speakers,
)
from transcripts.ingest import ingest_path
from transcripts.models import RawSegment, Session, SessionMetadata


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(sqlite, "_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(sqlite, "_conn", None)
    sqlite.init_db()
    yield
    monkeypatch.setattr(sqlite, "_conn", None)


@pytest.fixture()
def llm_forbidden(monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("identity must not construct an LLM (config.get_llm called)")
    monkeypatch.setattr(config, "get_llm", _boom)
    yield


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def test_normalize_strips_parenthetical_lowercases_and_collapses_whitespace():
    assert _normalize_name("Alex (flashbots?)") == "alex"
    assert _normalize_name("  Shaw   Walters  ") == "shaw walters"
    assert _normalize_name("Hunter (tinycloud)") == "hunter"
    assert _normalize_name("") == ""


# ---------------------------------------------------------------------------
# v5 — extract_affiliation
# ---------------------------------------------------------------------------

def test_extract_affiliation_pulls_parenthetical_content():
    assert extract_affiliation("Alex (flashbots?)") == "flashbots"
    assert extract_affiliation("Hunter (tinycloud)") == "tinycloud"
    assert extract_affiliation("Sevenfloor (Xiaoting)") == "Xiaoting"


def test_extract_affiliation_returns_none_without_parenthetical():
    assert extract_affiliation("Shaw") is None
    assert extract_affiliation("Shaw Walters") is None
    assert extract_affiliation("") is None


def test_extract_affiliation_strips_trailing_question_mark():
    """`(flashbots?)` from a transcriber's hedge → still cleanly 'flashbots'."""
    assert extract_affiliation("Alex (flashbots?)") == "flashbots"
    assert extract_affiliation("Someone (idk?)") == "idk"


def test_extract_affiliation_handles_empty_parens():
    """Edge: empty or whitespace-only parens → None, not empty string."""
    assert extract_affiliation("Foo ()") is None
    assert extract_affiliation("Foo (   )") is None
    assert extract_affiliation("Foo (?)") is None


# ---------------------------------------------------------------------------
# resolve_identity against the real cohort directory
# ---------------------------------------------------------------------------

def test_resolve_known_full_name():
    """Real cohort member → real record_id."""
    if "shaw walters" not in MOCK_DIRECTORY:
        pytest.skip("cohort-data not present in this checkout")
    assert resolve_identity("Shaw Walters") == "shaw-walters"
    assert resolve_identity("Albiona Hoti") == "albiona-hoti"


def test_resolve_unique_first_name():
    """Unique first names get a shortcut so transcripts using just 'Shaw' work."""
    if "shaw" not in MOCK_DIRECTORY:
        pytest.skip("cohort-data not present in this checkout")
    assert resolve_identity("Shaw") == "shaw-walters"


def test_resolve_parenthetical_strips_then_looks_up():
    """`Alex (flashbots?)` strips to `alex`. Alex isn't in the cohort, so this
    is `None` — but the *normalize* path is exercised by the unit above and
    by the directory check below."""
    # The lookup key after stripping is the bare first name.
    # If the cohort happens to have a unique "Hunter", the parenthetical
    # form resolves to that record.
    if "hunter" in MOCK_DIRECTORY:
        rid = resolve_identity("Hunter (tinycloud)")
        assert rid == MOCK_DIRECTORY["hunter"]


def test_anonymous_labels_never_resolve():
    assert resolve_identity("Speaker 1") is None
    assert resolve_identity("Speaker 47") is None
    assert resolve_identity("Unknown Speaker") is None
    assert resolve_identity("") is None
    assert resolve_identity("  ") is None


def test_unknown_label_returns_none():
    assert resolve_identity("Definitely Not A Cohort Member") is None


# ---------------------------------------------------------------------------
# Directory construction
# ---------------------------------------------------------------------------

def test_ambiguous_first_name_does_not_get_a_shortcut():
    """`Andrew` is both Andrew Forman and Andrew Miller → no shortcut."""
    if "andrew forman" not in MOCK_DIRECTORY or "andrew miller" not in MOCK_DIRECTORY:
        pytest.skip("cohort-data not present in this checkout")
    assert resolve_identity("Andrew") is None
    assert resolve_identity("Andrew Forman") == "andrew-forman"
    assert resolve_identity("Andrew Miller") == "andrew-miller"


def test_missing_people_dir_yields_empty_directory_not_crash(tmp_path):
    d = _load_mock_directory(tmp_path / "does-not-exist")
    assert d == {}


def test_load_mock_directory_handles_roster_aliases(tmp_path):
    """Parenthetical alias inside a `name:` field becomes a lookup key."""
    pdir = tmp_path / "people"
    pdir.mkdir()
    (pdir / "matt.md").write_text(
        "---\nrecord_id: matt-van-ommeren\nname: \"Matt Van Ommeren (quasimatt)\"\n---\nbody\n",
        encoding="utf-8",
    )
    (pdir / "shaw.md").write_text(
        "---\nrecord_id: shaw-walters\nname: \"Shaw Walters\"\n---\nbody\n",
        encoding="utf-8",
    )
    d = _load_mock_directory(pdir)
    assert d["matt van ommeren"] == "matt-van-ommeren"
    assert d["quasimatt"] == "matt-van-ommeren"   # the alias works
    assert d["shaw walters"] == "shaw-walters"
    assert d["shaw"] == "shaw-walters"            # unique-first-name shortcut
    assert d["matt"] == "matt-van-ommeren"        # also unique here


def test_first_name_shortcut_suppressed_on_collision(tmp_path):
    pdir = tmp_path / "people"
    pdir.mkdir()
    (pdir / "a.md").write_text(
        "---\nrecord_id: andrew-forman\nname: \"Andrew Forman\"\n---\n", encoding="utf-8",
    )
    (pdir / "b.md").write_text(
        "---\nrecord_id: andrew-miller\nname: \"Andrew Miller\"\n---\n", encoding="utf-8",
    )
    d = _load_mock_directory(pdir)
    assert "andrew" not in d           # no shortcut
    assert d["andrew forman"] == "andrew-forman"
    assert d["andrew miller"] == "andrew-miller"


# ---------------------------------------------------------------------------
# resolve_speakers + the verbatim-label invariant
# ---------------------------------------------------------------------------

def _session_with_labels(*labels: str) -> Session:
    segs = [RawSegment(speaker=l, text="t", start=float(i)) for i, l in enumerate(labels)]
    return Session(
        session_id="sx",
        raw_diarization=segs,
        metadata=SessionMetadata(date="2026-05-20", source="otter"),
    )


def test_resolve_speakers_keys_by_verbatim_label_and_omits_unresolved():
    if "shaw" not in MOCK_DIRECTORY:
        pytest.skip("cohort-data not present in this checkout")
    s = _session_with_labels("Shaw", "Speaker 1", "Not A Real Person")
    out = resolve_speakers(s)
    assert "Shaw" in out
    assert out["Shaw"]["record_id"] == "shaw-walters"
    assert out["Shaw"]["mock"] is True
    assert out["Shaw"]["name"] == "Shaw"          # verbatim label is preserved
    assert "Speaker 1" not in out                 # anonymous omitted, not None
    assert "Not A Real Person" not in out


def test_raw_diarization_labels_are_not_mutated_by_resolution():
    s = _session_with_labels("Alex (flashbots?)", "Shaw")
    resolve_speakers(s)
    assert s.raw_diarization[0].speaker == "Alex (flashbots?)"  # unchanged


# ---------------------------------------------------------------------------
# Ingest integration + the re-link pass
# ---------------------------------------------------------------------------

def test_ingest_populates_resolved_speakers(tmp_db, llm_forbidden, tmp_path):
    if "shaw" not in MOCK_DIRECTORY:
        pytest.skip("cohort-data not present in this checkout")
    f = tmp_path / "Standup_May_20.txt"
    f.write_text(
        "Shaw  0:00\nhello\n\nSpeaker 1  0:04\nhi\n\nNot A Cohort Member  0:08\nyo\n\n",
        encoding="utf-8",
    )
    ingest_path(f)
    s = store.list_sessions()[0]
    assert "Shaw" in s.metadata.resolved_speakers
    assert s.metadata.resolved_speakers["Shaw"]["record_id"] == "shaw-walters"
    assert "Speaker 1" not in s.metadata.resolved_speakers
    assert "Not A Cohort Member" not in s.metadata.resolved_speakers


def test_link_identities_picks_up_directory_changes(tmp_db, llm_forbidden, monkeypatch, tmp_path):
    """Ingest first with an empty directory, then grow the directory and re-link."""
    monkeypatch.setattr(identity, "MOCK_DIRECTORY", {})

    f = tmp_path / "Late_May_20.txt"
    f.write_text("Late Arrival  0:00\nhi\n\n", encoding="utf-8")
    ingest_path(f)
    s_before = store.list_sessions()[0]
    assert s_before.metadata.resolved_speakers == {}

    # Directory grows (mock the roster lookup).
    monkeypatch.setattr(identity, "MOCK_DIRECTORY", {"late arrival": "late-arrival"})
    changed = link_identities()
    assert changed == 1

    s_after = store.load_session(s_before.session_id)
    assert s_after.metadata.resolved_speakers["Late Arrival"]["record_id"] == "late-arrival"


def test_link_identities_noop_when_nothing_changes(tmp_db, llm_forbidden, monkeypatch, tmp_path):
    monkeypatch.setattr(identity, "MOCK_DIRECTORY", {"shaw": "shaw-walters"})
    f = tmp_path / "S_May_20.txt"
    f.write_text("Shaw  0:00\nhi\n\n", encoding="utf-8")
    ingest_path(f)
    # Already linked at ingest time; a re-link with the same directory is a no-op.
    assert link_identities() == 0
