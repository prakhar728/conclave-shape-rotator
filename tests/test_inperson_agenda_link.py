"""Task #12 — in-person agenda → meeting intent → insights, end-to-end.

A regression guard for the chain that gives in-person recordings the same agenda
grounding online + upload meetings already have (Task #11):

    record modal agenda  (POST /record/agenda, stashed by uid)
      → meeting.completed webhook reads the stash by uid (== native_meeting_id)
        → session.metadata.raw_intent set BEFORE enrichment is enqueued
          → enrich_session compiles it into the <meeting_intent> prompt block
            → session.metadata.meeting_intent_version is stamped (provenance probe)

The capture microservice is untouched (Option B): the agenda rides a small Conclave
stash, not the WS. identify/enrich are stubbed (no LLM / no FPM) and the LLM in the
behavioral half is a canned FakeLLM. The point is to make a future refactor that
silently drops any link in this chain go RED here. Mirrors
tests/test_calendar_intent_link.py (the online equivalent).

Covers spec §7:
  * stashed agenda → raw_intent on the finalized in-person session (consumed once);
  * raw_intent is set on the session by the time finalize returns — i.e. BEFORE the
    background identify→enrich task runs (that task is only scheduled at the end of
    the handler);
  * manual-intent-wins: a pre-set raw_intent is never overwritten by the stash;
  * no stash → raw_intent stays None (control);
  * FakeLLM enrich with agenda → <meeting_intent> present + meeting_intent_version set;
  * no agenda → no compile call, no <meeting_intent>, version stays None.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from infra import identity, inperson_agenda, workspaces
from storage.sqlite import _get_conn
from transcripts import store as tstore
from transcripts.enrich import enrich_session
from transcripts.models import Derived, RawSegment, Session, SessionMetadata

UID = "inperson-1700000000000-abc123"


class FakeLLM:
    """One canned response per .invoke(); mirrors test_calendar_intent_link.py."""

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
def _clean():
    from tests.conftest import reset_workspace_domain_tables
    c = _get_conn()
    c.execute("DELETE FROM transcript_sessions")
    c.execute("DELETE FROM bot_invitations")
    c.execute("DELETE FROM live_segments")
    c.execute("DELETE FROM inperson_agenda")
    reset_workspace_domain_tables()
    yield


@pytest.fixture
def app_client(monkeypatch) -> TestClient:
    """No LLM, no FPM: stub post-meeting identity (inline, not deferred) and enrich."""
    import api.transcripts_routes as tr
    monkeypatch.setattr(tr, "_enrich_in_background", lambda sid: None)

    import connectors.capture.identify as cid

    async def _no_identify(*a, **k):
        return False  # inline path; we don't exercise the diarize queue here

    monkeypatch.setattr(cid, "identify_meeting", _no_identify)
    monkeypatch.delenv("CAPTURE_WEBHOOK_SECRET", raising=False)

    from main import app
    return TestClient(app)


def _seed_live(uid: str = UID) -> None:
    """Buffer a couple of in-person live segments so finalize materializes a session."""
    tstore.append_segment(uid, 0, {"start": 0.0, "end": 2.0, "speaker": "Speaker 1",
                                    "text": "Let's lock the Q3 pricing tiers."})
    tstore.append_segment(uid, 1, {"start": 2.0, "end": 4.0, "speaker": "Speaker 2",
                                   "text": "Agreed, and we should decide the launch date."})


def _inperson_event(uid: str, workspace_id: str) -> dict:
    """An in-person finalize event: no bot_invitation, workspace rides the payload."""
    return {
        "event_id": "evt_ip",
        "event_type": "meeting.completed",
        "api_version": "v1",
        "created_at": "2026-06-30T10:05:00Z",
        "data": {
            "meeting": {
                "id": 1234,
                "platform": "inperson",
                "native_meeting_id": uid,
                "status": "completed",
                "workspace_id": workspace_id,
            },
        },
    }


def _ws() -> tuple[str, str]:
    user = identity.upsert_user_by_supabase("sb-ip", "host@example.com")
    ws = workspaces.create_workspace("WS", user["id"])
    return user["id"], ws["id"]


# --- the webhook step: stashed agenda → raw_intent ---------------------------

def test_inperson_agenda_becomes_raw_intent(app_client: TestClient):
    """The stash, keyed by uid, lands on the finalized session's raw_intent and is
    consumed (so it can't linger or re-apply)."""
    _user, wsid = _ws()
    agenda = "Decide Q3 pricing tiers and the launch date. Focus: the pricing call."
    inperson_agenda.set_agenda(UID, agenda, workspace_id=wsid)
    _seed_live()

    r = app_client.post("/api/webhooks/capture/meeting-completed",
                        json=_inperson_event(UID, wsid))
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "accepted"
    sid = r.json()["session_id"]

    # raw_intent is set on the session by the time finalize returns — i.e. before the
    # background identify→enrich task (scheduled only at the very end of the handler)
    # could ever run. This IS the "set before enrich" guarantee.
    sess = tstore.load_session(sid)
    assert sess is not None
    assert sess.metadata.raw_intent == agenda

    # consume-once: the stash row is gone.
    assert inperson_agenda.pop_agenda(UID) is None


def test_inperson_manual_intent_wins(app_client: TestClient, monkeypatch):
    """A raw_intent already on the freshly-built session must NOT be overwritten by
    the stash (mirrors #11's manual-intent-wins guard)."""
    _user, wsid = _ws()
    inperson_agenda.set_agenda(UID, "STASH: talk about pricing", workspace_id=wsid)
    _seed_live()

    # Simulate a session that already carries an intent when finalize builds it.
    import api.transcripts_routes as tr
    real_build = tr._build_and_save_session

    def _build_with_intent(payload_dict):
        sess = real_build(payload_dict)
        sess.metadata.raw_intent = "MANUAL: only talk about hiring"
        tstore.set_metadata(sess.session_id, sess.metadata)
        return sess

    monkeypatch.setattr(tr, "_build_and_save_session", _build_with_intent)

    r = app_client.post("/api/webhooks/capture/meeting-completed",
                        json=_inperson_event(UID, wsid))
    assert r.status_code == 202, r.text
    sid = r.json()["session_id"]

    sess = tstore.load_session(sid)
    assert sess.metadata.raw_intent == "MANUAL: only talk about hiring"  # unchanged


def test_inperson_no_agenda_sets_no_intent(app_client: TestClient):
    """No stash → raw_intent stays None (the prior, ungrounded behavior)."""
    _user, wsid = _ws()
    _seed_live()

    r = app_client.post("/api/webhooks/capture/meeting-completed",
                        json=_inperson_event(UID, wsid))
    assert r.status_code == 202, r.text
    sid = r.json()["session_id"]

    sess = tstore.load_session(sid)
    assert sess is not None
    assert sess.metadata.raw_intent is None


# --- the full chain: agenda → <meeting_intent> + version ---------------------

def _persist_session(session_id: str, *, raw_intent=None) -> Session:
    sess = Session(
        session_id=session_id,
        raw_diarization=[RawSegment(speaker="Speaker 1", text="hi", start=0.0)],
        metadata=SessionMetadata(date="2026-06-30", source="inperson",
                                 raw_intent=raw_intent),
        derived=Derived(),
    )
    tstore.save_session(sess)
    return sess


def test_inperson_agenda_grounds_enrichment_end_to_end():
    """raw_intent sourced from the in-person agenda flows into enrichment: the
    <meeting_intent> block is spliced in and meeting_intent_version stamped."""
    agenda = "Decide the pricing tiers. Pay closest attention to the pricing decision."
    sess = _persist_session("ip-grounded", raw_intent=agenda)

    compile_resp = {"focus": "the pricing decision", "agenda_items": ["pricing tiers"],
                    "goal": "decide pricing", "desired_outputs": [], "constraints": []}
    enrich_resp = {"summary": "short", "signals": [], "entities": []}
    fake = FakeLLM(compile_resp, enrich_resp)

    enrich_session(sess, llm=fake)

    # compile_intent ran first (the agenda), then enrichment.
    assert len(fake.calls) == 2
    enrich_system = fake.calls[1][0].content
    assert "<meeting_intent>" in enrich_system
    assert "the pricing decision" in enrich_system  # structured field rendered
    assert sess.metadata.meeting_intent_version is not None  # provenance stamp applied


def test_inperson_no_agenda_no_meeting_intent():
    """No raw_intent → no compile_intent call, no <meeting_intent>, version stays None.
    The contrast that makes a broken stash-read observable end-to-end."""
    sess = _persist_session("ip-ungrounded", raw_intent=None)

    enrich_resp = {"summary": "short", "signals": [], "entities": []}
    fake = FakeLLM(enrich_resp)

    enrich_session(sess, llm=fake)

    assert len(fake.calls) == 1  # only enrichment ran, no intent compile
    enrich_system = fake.calls[0][0].content
    assert "<meeting_intent>" not in enrich_system
    assert sess.metadata.meeting_intent_version is None
