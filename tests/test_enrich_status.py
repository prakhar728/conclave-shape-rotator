"""P2 — enrichment status: skip the LLM (no tokens) when unconfigured / force-disabled,
and record ok/skipped/failed so the meeting page can explain empty insights. The spaCy
draft is created regardless (in parallel).
"""
from __future__ import annotations

import api.transcripts_routes as routes
import transcripts.enrich as enrich_mod
from config import Settings
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
    monkeypatch.setattr(Settings, "llm_configured", lambda self:False)
    calls = []
    monkeypatch.setattr(enrich_mod, "enrich_session", lambda s: calls.append(1))
    _save("es-nollm")
    routes._enrich_in_background("es-nollm")
    assert calls == []  # NO LLM call → no tokens burned
    assert store.load_session("es-nollm").metadata.enrichment_status == "skipped"
    assert store.load_v2("es-nollm") is not None  # draft still created (parallel)


def test_skip_via_env_flag(monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setattr(Settings, "llm_configured", lambda self:True)  # configured…
    monkeypatch.setenv("CONCLAVE_SKIP_ENRICH", "1")                 # …but force-skipped
    calls = []
    monkeypatch.setattr(enrich_mod, "enrich_session", lambda s: calls.append(1))
    _save("es-skip")
    routes._enrich_in_background("es-skip")
    assert calls == []
    assert store.load_session("es-skip").metadata.enrichment_status == "skipped"


def test_status_ok_on_success(monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setattr(Settings, "llm_configured", lambda self:True)
    monkeypatch.setattr(enrich_mod, "enrich_session", lambda s: setattr(s.derived, "summary", "ok"))
    _save("es-ok")
    routes._enrich_in_background("es-ok")
    assert store.load_session("es-ok").metadata.enrichment_status == "ok"


def test_status_failed_on_error(monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setattr(Settings, "llm_configured", lambda self:True)

    def boom(_s):
        raise RuntimeError("llm down")

    monkeypatch.setattr(enrich_mod, "enrich_session", boom)
    _save("es-fail")
    routes._enrich_in_background("es-fail")
    assert store.load_session("es-fail").metadata.enrichment_status == "failed"
    assert store.load_v2("es-fail") is not None  # draft survives
