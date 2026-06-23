"""P1 — the editable v2 draft must be created independent of (slow/failable) LLM
enrichment, so `/refine` has a draft immediately and even when enrich blows up.
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


def test_draft_created_even_when_enrich_fails(monkeypatch):
    monkeypatch.setattr(candidate, "detect", lambda t, u: (t.split(), []))
    monkeypatch.setattr(routes, "_should_skip_enrich", lambda: False)  # enrich runs

    def boom(_session):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(enrich_mod, "enrich_session", boom)
    monkeypatch.setattr(routes, "_build_kb", lambda sid: None)
    monkeypatch.setattr(routes, "_send_attendee_magic_links", lambda sid: None)

    _save("pe-fail")
    routes._enrich_in_background("pe-fail")  # must not raise

    v2 = store.load_v2("pe-fail")
    assert v2 is not None and v2.status == "draft"  # draft survived the enrich failure


def test_draft_created_on_happy_path(monkeypatch):
    monkeypatch.setattr(candidate, "detect", lambda t, u: (t.split(), []))
    monkeypatch.setattr(routes, "_should_skip_enrich", lambda: False)  # enrich runs
    monkeypatch.setattr(enrich_mod, "enrich_session", lambda s: None)
    monkeypatch.setattr(routes, "_build_kb", lambda sid: None)
    monkeypatch.setattr(routes, "_send_attendee_magic_links", lambda sid: None)

    _save("pe-ok")
    routes._enrich_in_background("pe-ok")
    assert store.load_v2("pe-ok").status == "draft"
