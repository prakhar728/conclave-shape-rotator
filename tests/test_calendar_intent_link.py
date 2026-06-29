"""Task #11 — calendar description → meeting intent → insights, end-to-end.

A regression guard for the quiet, high-leverage chain that grounds auto-recorded
meetings in their calendar agenda with zero user effort:

    Google Calendar event.description
      → meeting_calendar_links.link_completed_meeting sets session.metadata.raw_intent
        → enrich_session compiles it into the <meeting_intent> prompt block
          → session.metadata.meeting_intent_version is stamped (provenance probe)

Everything is test-double / no-network: ``gc.get_event`` is monkeypatched and the
LLM is a canned FakeLLM. The point is to make a future refactor that silently drops
any link in this chain go RED here.

Covers spec §7:
  * stubbed calendar desc → raw_intent (honouring the manual-intent-wins guard);
  * FakeLLM enrich → <meeting_intent> present + meeting_intent_version set;
  * empty/whitespace description → no raw_intent, no fragment;
  * observable signal: the log line fires when the description is applied.
"""
from __future__ import annotations

import json
import logging

import pytest
from cryptography.fernet import Fernet

from storage.sqlite import _get_conn
from transcripts import store as tstore
from transcripts.enrich import enrich_session
from transcripts.models import Derived, RawSegment, Session, SessionMetadata

MEET = "abc-defg-hij"


class FakeLLM:
    """One canned response per .invoke(); mirrors tests/test_meeting_intent.py."""

    model_name = "fake-llm"

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls: list[list] = []

    def invoke(self, messages):
        self.calls.append(list(messages))
        if not self._responses:
            raise AssertionError("FakeLLM ran out of canned responses")
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        body = item if isinstance(item, str) else json.dumps(item)
        return type("Resp", (), {"content": body})()


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    """A host with a Google connection + an auto-record row for MEET, plus a
    persisted session so link_completed_meeting can load/mutate it."""
    from config import settings
    monkeypatch.setattr(settings, "google_client_id", "cid")
    monkeypatch.setattr(settings, "google_client_secret", "cs")
    monkeypatch.setattr(settings, "google_redirect_uri", "https://app.test/cb")
    monkeypatch.setattr(settings, "token_enc_key", Fernet.generate_key().decode())

    from tests.conftest import reset_workspace_domain_tables
    c = _get_conn()
    c.execute("DELETE FROM google_oauth_tokens")
    c.execute("DELETE FROM calendar_auto_record")
    c.execute("DELETE FROM meeting_calendar_links")
    c.execute("DELETE FROM meeting_shares")
    reset_workspace_domain_tables()

    from infra import identity, workspaces, google_calendar as gc, calendar_auto_record as car
    user = identity.upsert_user_by_supabase(supabase_id="sb-cal", email="host@example.com")
    ws = workspaces.ensure_personal_workspace(user["id"])
    gc.save_tokens(user_id=user["id"], access_token="a", refresh_token="r",
                   expiry="2099-01-01T00:00:00+00:00", scopes="s")
    car.set_auto_record(user_id=user["id"], google_event_id="ev1", workspace_id=ws["id"],
                        meet_code=MEET, enabled=True)
    yield user["id"]


def _persist_session(session_id: str = MEET, *, raw_intent=None) -> None:
    """Store a minimal session so link_completed_meeting can load + mutate it."""
    tstore.save_session(Session(
        session_id=session_id,
        raw_diarization=[RawSegment(speaker="A", text="hi", start=0.0)],
        metadata=SessionMetadata(date="2026-06-08", source="google_meet",
                                  raw_intent=raw_intent),
        derived=Derived(),
    ))


def _event(description=None, attendees=None):
    return {
        "id": "ev1", "title": "Design review",
        "start": "2026-06-08T10:00:00Z", "end": "2026-06-08T11:00:00Z",
        "organizer": "host@example.com",
        "attendees": attendees if attendees is not None else [],
        "meet_code": MEET,
        "description": description,
    }


# --- the link step: calendar description → raw_intent ------------------------

def test_calendar_description_becomes_raw_intent(monkeypatch, _setup, caplog):
    user_id = _setup
    from infra import google_calendar as gc, meeting_calendar_links as mcl
    desc = "Lock Q3 pricing tiers; decide launch date. Focus: the pricing decision."
    monkeypatch.setattr(gc, "get_event", lambda uid, eid: _event(description=desc))
    _persist_session()

    with caplog.at_level(logging.INFO, logger="infra.meeting_calendar_links"):
        link = mcl.link_completed_meeting(
            meet_code=MEET, session_id=MEET, inviter_user_id=user_id)

    assert link is not None  # event resolved + linked
    sess = tstore.load_session(MEET)
    assert sess is not None
    assert sess.metadata.raw_intent == desc  # the description landed as intent

    # Observable signal: applying the description emits a log line (so a silent
    # break in the chain is visible in production logs).
    assert any("applied calendar description as meeting intent" in r.message
               for r in caplog.records)


def test_manual_intent_wins_over_calendar_description(monkeypatch, _setup):
    """A pre-set manual focus must NOT be overwritten by the calendar agenda."""
    user_id = _setup
    from infra import google_calendar as gc, meeting_calendar_links as mcl
    monkeypatch.setattr(gc, "get_event",
                        lambda uid, eid: _event(description="calendar agenda text"))
    _persist_session(raw_intent="MANUAL: only talk about hiring")

    mcl.link_completed_meeting(meet_code=MEET, session_id=MEET, inviter_user_id=user_id)

    sess = tstore.load_session(MEET)
    assert sess.metadata.raw_intent == "MANUAL: only talk about hiring"  # unchanged


def test_empty_description_sets_no_intent(monkeypatch, _setup, caplog):
    """Empty / whitespace-only description → raw_intent stays None, no signal."""
    user_id = _setup
    from infra import google_calendar as gc, meeting_calendar_links as mcl
    monkeypatch.setattr(gc, "get_event", lambda uid, eid: _event(description="   "))
    _persist_session()

    with caplog.at_level(logging.INFO, logger="infra.meeting_calendar_links"):
        link = mcl.link_completed_meeting(
            meet_code=MEET, session_id=MEET, inviter_user_id=user_id)

    assert link is not None  # the link itself still happens (best-effort enrichment)
    sess = tstore.load_session(MEET)
    assert sess.metadata.raw_intent is None  # nothing applied
    assert not any("applied calendar description" in r.message for r in caplog.records)


# --- the full chain: calendar description → <meeting_intent> + version --------

def test_calendar_description_grounds_enrichment_end_to_end(monkeypatch, _setup):
    """raw_intent sourced from the calendar description flows into enrichment:
    the <meeting_intent> block is spliced in and meeting_intent_version stamped."""
    user_id = _setup
    from infra import google_calendar as gc, meeting_calendar_links as mcl
    desc = "Decide the pricing tiers. Pay closest attention to the pricing decision."
    monkeypatch.setattr(gc, "get_event", lambda uid, eid: _event(description=desc))
    _persist_session()

    mcl.link_completed_meeting(meet_code=MEET, session_id=MEET, inviter_user_id=user_id)

    sess = tstore.load_session(MEET)
    assert sess.metadata.raw_intent == desc

    compile_resp = {"focus": "the pricing decision", "agenda_items": ["pricing tiers"],
                    "goal": "decide pricing", "desired_outputs": [], "constraints": []}
    enrich_resp = {"summary": "short", "signals": [], "entities": []}
    fake = FakeLLM(compile_resp, enrich_resp)

    enrich_session(sess, llm=fake)

    # compile_intent ran first (the calendar desc), then enrichment.
    assert len(fake.calls) == 2
    enrich_system = fake.calls[1][0].content
    assert "<meeting_intent>" in enrich_system
    assert "the pricing decision" in enrich_system  # structured field rendered
    # Provenance stamp present → the grounding actually applied.
    assert sess.metadata.meeting_intent_version is not None


# --- observable signal on the API surface ------------------------------------

def test_to_card_exposes_meeting_intent_version():
    """The provenance stamp must reach the API payload so the meeting page can
    render the agenda-grounded signal (guards a silent drop of the field)."""
    from api.transcripts_routes import to_card
    sess = Session(
        session_id="s-card",
        raw_diarization=[RawSegment(speaker="A", text="hi", start=0.0)],
        metadata=SessionMetadata(date="2026-06-08", source="google_meet",
                                  meeting_intent_version="deadbeef"),
        derived=Derived(),
    )
    card = to_card(sess)
    assert card["meeting_intent_version"] == "deadbeef"

    # None when no intent was applied (the badge stays hidden).
    sess.metadata.meeting_intent_version = None
    assert to_card(sess)["meeting_intent_version"] is None
