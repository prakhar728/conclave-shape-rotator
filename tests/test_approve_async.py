"""Approve must return fast and never burn tokens it was told to skip.

The HTTP endpoint flips the draft → approved synchronously, then runs the heavy build
(insight re-derive + KB) in the BACKGROUND — so a big transcript / LLM call can't time
out the request and produce a false "Couldn't approve" after the approval persisted.
And re-derive honors the no-LLM skip (no tokens on approve).
"""
from __future__ import annotations

import api.transcripts_routes as routes
import transcripts.enrich as enrich_mod
from transcripts import store
from transcripts.models import RawSegment, Session, SessionMetadata


def _draft(sid):
    store.save_session(Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="s", text="we use Recato")],
        metadata=SessionMetadata(date="2026-06-23", source="t"),
    ))
    store.create_v2_draft(sid)


def test_rederive_honors_skip(monkeypatch):  # the token-burn bug
    monkeypatch.setattr(routes, "_should_skip_enrich", lambda: True)
    seen: list[str] = []
    monkeypatch.setattr(enrich_mod, "enrich_session", lambda s: seen.append(s.session_id))
    _draft("rd-skip")
    routes._rederive_insights_from_v2("rd-skip")
    assert seen == []  # LLM disabled → no enrich call → no tokens, no network block


def test_approve_now_flips_status_without_building(monkeypatch):
    built: list[str] = []
    monkeypatch.setattr(routes, "_post_approve_build", lambda sid: built.append(sid))
    _draft("ap-now")
    assert routes._approve_v2_now("ap-now") is True
    assert store.load_v2("ap-now").status == "approved"  # flipped synchronously
    assert built == []  # the fast path does NOT block on the build
    assert routes._approve_v2_now("ap-now") is False  # idempotent → no re-approve


def test_approve_and_build_runs_full_inline(monkeypatch):  # sweep path unchanged
    built: list[str] = []
    monkeypatch.setattr(routes, "_post_approve_build", lambda sid: built.append(sid))
    _draft("ap-full")
    routes.approve_and_build("ap-full")
    assert built == ["ap-full"] and store.load_v2("ap-full").status == "approved"


def test_post_approve_build_failure_is_isolated(monkeypatch):
    # Even if the build half explodes, the approval stands (it ran first + separately).
    _draft("ap-iso")
    assert routes._approve_v2_now("ap-iso") is True
    monkeypatch.setattr(routes, "_rederive_insights_from_v2",
                        lambda sid: (_ for _ in ()).throw(RuntimeError("boom")))
    try:
        routes._post_approve_build("ap-iso")
    except RuntimeError:
        pass  # the background thread would log this; it never touches the response
    assert store.load_v2("ap-iso").status == "approved"
