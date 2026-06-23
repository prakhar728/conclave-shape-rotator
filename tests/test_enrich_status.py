"""P2 — enrichment status: skip the LLM (no tokens) when unconfigured / force-disabled,
and record ok/skipped/failed so the meeting page can explain empty insights. The spaCy
draft is created regardless.
"""
from __future__ import annotations

import api.transcripts_routes as routes
import transcripts.enrich as enrich_mod
from transcripts import candidate, store
from transcripts.models import RawSegment, Session, SessionMetadata


def _save(sid):
    store.save_session(Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="s", text="we use Recato")],
        metadata=SessionMetadata(date="2026-06-22", source="t"),
    ))


def _quiet(monkeypatch):
    monkeypatch.setattr(candidate, "detect", lambda t, u: (t.split(), []))
    monkeypatch.setattr(routes, "_build_kb", lambda sid: None)
    monkeypatch.setattr(routes, "_send_attendee_magic_links", lambda sid: None)
    monkeypatch.delenv("CONCLAVE_SKIP_ENRICH", raising=False)


def test_skip_when_no_llm_configured(monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setattr(routes, "_should_skip_enrich", lambda: True)  # no LLM
    # session-aware spy — robust vs. leaked background enrich threads in the full suite
    seen: list[str] = []
    monkeypatch.setattr(enrich_mod, "enrich_session", lambda s: seen.append(s.session_id))
    _save("es-nollm")
    routes._enrich_in_background("es-nollm")
    assert "es-nollm" not in seen  # NO LLM call for this session → no tokens burned
    assert store.load_session("es-nollm").metadata.enrichment_status == "skipped"
    assert store.load_v2("es-nollm") is not None  # draft still created


def test_skip_via_env_flag(monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setenv("CONCLAVE_SKIP_ENRICH", "1")  # real seam reads this → skip
    seen: list[str] = []
    monkeypatch.setattr(enrich_mod, "enrich_session", lambda s: seen.append(s.session_id))
    _save("es-skip")
    routes._enrich_in_background("es-skip")
    assert "es-skip" not in seen
    assert store.load_session("es-skip").metadata.enrichment_status == "skipped"


def test_status_ok_on_success(monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setattr(routes, "_should_skip_enrich", lambda: False)  # LLM available
    monkeypatch.setattr(enrich_mod, "enrich_session", lambda s: setattr(s.derived, "summary", "ok"))
    _save("es-ok")
    routes._enrich_in_background("es-ok")
    assert store.load_session("es-ok").metadata.enrichment_status == "ok"


def test_status_failed_on_error(monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setattr(routes, "_should_skip_enrich", lambda: False)

    def boom(_s):
        raise RuntimeError("llm down")

    monkeypatch.setattr(enrich_mod, "enrich_session", boom)
    _save("es-fail")
    routes._enrich_in_background("es-fail")
    assert store.load_session("es-fail").metadata.enrichment_status == "failed"
    assert store.load_v2("es-fail") is not None  # draft survives
