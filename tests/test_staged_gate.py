"""Part 1 increment 2 — staged-pipeline gate (G-1..G-10).

Drives `_enrich_in_background` / `approve_and_build` directly with the heavy
stages spied out. The load-bearing guarantees: with the gate ON nothing reaches
the KB until approve; with it OFF behavior is unchanged; the choke point gates
every ingest path.
"""
from __future__ import annotations

import pathlib

import pytest

import api.transcripts_routes as routes
import transcripts.enrich as enrich_mod
import transcripts.kb_extract as kbx
import transcripts.kb_pipeline as kbp
from transcripts import store
from transcripts.models import RawSegment, Session, SessionMetadata


def _save(sid: str) -> None:
    store.save_session(
        Session(
            session_id=sid,
            raw_diarization=[RawSegment(speaker="speaker_1", text="hello world")],
            metadata=SessionMetadata(date="2026-06-19", source="test"),
        )
    )


@pytest.fixture()
def spies(monkeypatch):
    calls = {"enrich": 0, "index": 0, "extract": 0}

    def fake_enrich(session):
        calls["enrich"] += 1
        session.derived.summary = "stub"

    monkeypatch.setattr(enrich_mod, "enrich_session", fake_enrich)
    monkeypatch.setattr(kbp, "index_session", lambda sid: calls.__setitem__("index", calls["index"] + 1))
    monkeypatch.setattr(kbx, "extract_session", lambda sid: calls.__setitem__("extract", calls["extract"] + 1))
    return calls


def test_gate_off_builds_now(spies, monkeypatch):  # default behavior unchanged
    monkeypatch.delenv("CONCLAVE_REFINE_GATE", raising=False)
    _save("g-off")
    routes._enrich_in_background("g-off")
    assert spies["enrich"] == 1
    assert spies["index"] == 1 and spies["extract"] == 1
    assert store.load_v2("g-off").status == "draft"  # draft still created


def test_gate_on_pauses_before_kb(spies, monkeypatch):  # G-1 / G-2
    monkeypatch.setenv("CONCLAVE_REFINE_GATE", "1")
    _save("g-on")
    routes._enrich_in_background("g-on")
    assert spies["enrich"] == 1
    assert spies["index"] == 0 and spies["extract"] == 0  # KB paused → graph empty
    assert store.load_v2("g-on").status == "draft"


def test_approve_opens_gate(spies, monkeypatch):  # G-3
    monkeypatch.setenv("CONCLAVE_REFINE_GATE", "1")
    _save("g-appr")
    routes._enrich_in_background("g-appr")
    assert spies["index"] == 0
    routes.approve_and_build("g-appr")
    assert spies["index"] == 1 and spies["extract"] == 1
    assert store.load_v2("g-appr").status == "approved"


def test_reapprove_does_not_rebuild(spies, monkeypatch):  # G-7
    monkeypatch.setenv("CONCLAVE_REFINE_GATE", "1")
    _save("g-re")
    routes._enrich_in_background("g-re")
    routes.approve_and_build("g-re")
    routes.approve_and_build("g-re")  # second approval
    assert spies["index"] == 1 and spies["extract"] == 1  # built exactly once


def test_enrich_failure_recoverable(spies, monkeypatch):  # G-8
    monkeypatch.setenv("CONCLAVE_REFINE_GATE", "1")
    monkeypatch.setattr(
        enrich_mod, "enrich_session",
        lambda session: (_ for _ in ()).throw(RuntimeError("llm down")),
    )
    _save("g-fail")
    routes._enrich_in_background("g-fail")  # must not raise
    assert spies["index"] == 0 and spies["extract"] == 0
    assert store.load_v2("g-fail") is None  # no draft when enrich failed
    # recover: enrich works on re-run → draft now exists
    monkeypatch.setattr(
        enrich_mod, "enrich_session",
        lambda session: setattr(session.derived, "summary", "ok"),
    )
    routes._enrich_in_background("g-fail")
    assert store.load_v2("g-fail") is not None


def test_all_ingest_paths_route_through_choke_point():  # G-10 / N1
    api_dir = pathlib.Path(routes.__file__).parent
    for fname in (
        "webhooks_recato.py", "upload_routes.py", "record_routes.py", "bot_routes.py",
    ):
        text = (api_dir / fname).read_text()
        assert "_enrich_in_background" in text, (
            f"{fname} must funnel through the gated choke point"
        )
        # ...and must NOT call the gated build stages directly (would bypass the
        # gate while keeping the choke-point call). Audit-strengthened G-10.
        for bypass in ("_build_kb", "extract_session"):
            assert bypass not in text, (
                f"{fname} calls {bypass} directly — bypasses the refinement gate"
            )
