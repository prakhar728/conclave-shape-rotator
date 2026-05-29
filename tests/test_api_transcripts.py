"""C10 gate — derived-only read API.

Asserts the contract documented in IMPLEMENTATION_PLAN.md §G12 / §H C10:

- ``GET /transcripts/sessions``      → newest-first list of card dicts.
- ``GET /transcripts/sessions/{id}`` → derived + metadata for one session.
- **`raw_diarization` never appears in any response.** This is the
  highest-blast-radius privacy assertion in the pipeline (`§I "two
  assertions worth never losing"`); even the per-segment text strings
  must not bleed through.
- ``can_see`` stub allows everyone in Phase 1; the 403 path will go live
  at 1.5 without an endpoint signature change.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.transcripts_routes import router, to_card, to_view
from storage import sqlite
from transcripts import store
from transcripts.models import Derived, Entity, RawSegment, Session, SessionMetadata, Signal
from transcripts.prompts import ENRICH_PROMPT_VERSION


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(sqlite, "_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(sqlite, "_conn", None)
    sqlite.init_db()
    yield
    monkeypatch.setattr(sqlite, "_conn", None)


@pytest.fixture()
def client(tmp_db):
    """Fresh FastAPI app with just the transcripts router mounted."""
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


_SECRET_RAW_TEXT = "PRIVATE-RAW-DIARIZATION-TEXT-SHOULD-NEVER-LEAK"


def _store_session(sid: str = "demo", *, enriched: bool = True, date: str = "2026-05-20"):
    raw = [
        RawSegment(speaker="Shaw", text=_SECRET_RAW_TEXT + "-1", start=0.0),
        RawSegment(speaker="Speaker 1", text=_SECRET_RAW_TEXT + "-2", start=3.0),
    ]
    meta = SessionMetadata(
        date=date, source="otter",
        resolved_speakers={"Shaw": {"record_id": "shaw-walters", "name": "Shaw", "mock": True}},
        model_id="qwen2.5-conclave",
        enrich_prompt_version=ENRICH_PROMPT_VERSION,
        chunk_count=1,
    )
    derived = Derived(
        summary="They locked the hybrid matcher.",
        signals=[Signal(
            kind="decision", text="ship matcher",
            said_by=["Shaw"], about_person=[],
            source_quote="we should ship the matcher first",
        )],
        entities=[Entity(name="matcher", type="project", evidence="main topic")],
    ) if enriched else Derived()
    sess = Session(session_id=sid, raw_diarization=raw, metadata=meta, derived=derived)
    store.save_session(sess)
    return sess


# ---------------------------------------------------------------------------
# Endpoint shapes
# ---------------------------------------------------------------------------

def test_list_returns_newest_first_cards(client):
    _store_session("old", date="2026-05-15")
    _store_session("new", date="2026-05-25")
    _store_session("mid", date="2026-05-20")

    r = client.get("/transcripts/sessions")
    assert r.status_code == 200
    ids = [c["session_id"] for c in r.json()]
    assert ids == ["new", "mid", "old"]


def test_card_shape_has_expected_fields(client):
    _store_session("demo")
    r = client.get("/transcripts/sessions")
    card = r.json()[0]
    # Pre-v1 fields.
    for k in ("session_id", "date", "source", "summary",
              "signal_count", "entity_count", "chunk_count",
              "model_id", "enrich_prompt_version", "resolved_speakers", "seed"):
        assert k in card
    # v1 additions.
    for k in ("topics", "participants", "participants_count", "team_context_version"):
        assert k in card
    assert card["seed"] == card["session_id"]
    assert card["resolved_speakers"]["Shaw"]["record_id"] == "shaw-walters"


def test_card_includes_v1_topics_and_participants(client):
    """v1: topics + participants_count flow through to the list endpoint."""
    sess = _store_session("demo")
    # Patch in a v1 derived shape with topics + participants set.
    sess.derived.topics = ["attestation", "rag"]
    sess.metadata.participants = ["Shaw", "Alex (flashbots?)", "LSDan", "Andrew Forman"]
    store.save_session(sess)
    card = client.get("/transcripts/sessions").json()[0]
    assert card["topics"] == ["attestation", "rag"]
    assert card["participants_count"] == 4
    assert "Alex (flashbots?)" in card["participants"]


def test_detail_view_groups_signals_by_kind(client):
    """v1.1: ``signals_by_kind`` is a server-side convenience grouping so
    the dashboard can render distinct DECISIONS / ACTION ITEMS / OPEN
    QUESTIONS / INSIGHTS / IMPACTFUL POINTS sections without re-filtering
    the flat ``signals[]`` array. The flat array is still served too — both
    shapes coexist."""
    from transcripts.models import Signal as _Signal
    sess = _store_session("demo")
    sess.derived.signals = [
        _Signal(kind="decision", text="ship matcher", said_by=["Shaw"]),
        _Signal(kind="action_item", text="send link", said_by=["Alex"], about_person=["Shaw"]),
        _Signal(kind="action_item", text="give email IF needed", said_by=["Alex"], about_person=["Shaw"]),
        _Signal(kind="open_question", text="how does X work?", said_by=["Speaker 1"]),
        _Signal(kind="insight", text="Y is hard", said_by=["Shaw"]),
        _Signal(kind="impactful_point", text="Z happens", said_by=["Shaw"]),
    ]
    store.save_session(sess)

    view = client.get("/transcripts/sessions/demo").json()

    # Flat list still served.
    assert "signals" in view
    assert len(view["signals"]) == 6

    # Grouping under a stable set of pluralized keys.
    grouped = view["signals_by_kind"]
    assert set(grouped) == {"decisions", "action_items", "open_questions", "insights", "impactful_points"}
    assert len(grouped["decisions"]) == 1
    assert len(grouped["action_items"]) == 2
    assert len(grouped["open_questions"]) == 1
    assert len(grouped["insights"]) == 1
    assert len(grouped["impactful_points"]) == 1
    # Each grouped signal preserves the v1 schema fields.
    assert grouped["action_items"][0]["text"] == "send link"
    assert grouped["action_items"][0]["said_by"] == ["Alex"]
    assert grouped["action_items"][0]["about_person"] == ["Shaw"]
    # An empty group is an empty list, not missing — frontend can iterate safely.
    sess.derived.signals = [_Signal(kind="insight", text="only insight")]
    store.save_session(sess)
    view2 = client.get("/transcripts/sessions/demo").json()
    assert view2["signals_by_kind"]["decisions"] == []
    assert view2["signals_by_kind"]["open_questions"] == []


def test_signals_by_kind_preserves_demo_priority_order(client):
    """§D.4: section render order is decision → action_item → open_question
    → impactful_point → insight. The frontend trusts ``signals_by_kind`` key
    insertion order (Python 3.7+ dicts preserve it); JSON also preserves
    object key order in practice. Locking this here prevents accidental
    reorders from rearranging the dashboard."""
    sess = _store_session("demo")
    sess.derived.signals = []  # empty is fine — keys still present
    store.save_session(sess)
    grouped = client.get("/transcripts/sessions/demo").json()["signals_by_kind"]
    assert list(grouped.keys()) == [
        "decisions",
        "action_items",
        "open_questions",
        "impactful_points",
        "insights",
    ]


def test_detail_view_includes_v1_signal_fields(client):
    """v1 schema additions surface through the detail endpoint:
    said_by/about_person/source_quote on signals; cohort_status/affiliation
    on entities; topics on the session card."""
    sess = _store_session("demo")
    # Add a v1-shaped signal + entity to the existing fixture.
    from transcripts.models import Entity as _Entity, Signal as _Signal
    sess.derived.signals = [_Signal(
        kind="action_item",
        text="LSDan will reach out to Andrew",
        said_by=["LSDan"],
        about_person=["Andrew"],
        source_quote="Yeah I'll reach out to Andrew this week",
    )]
    sess.derived.entities = [
        _Entity(name="Andrew", type="person", cohort_status="member"),
        _Entity(name="Alex (flashbots?)", type="person",
                cohort_status="external", affiliation="flashbots"),
    ]
    sess.derived.topics = ["coordination"]
    store.save_session(sess)

    view = client.get("/transcripts/sessions/demo").json()
    sig = view["signals"][0]
    assert sig["said_by"] == ["LSDan"]
    assert sig["about_person"] == ["Andrew"]
    assert sig["source_quote"].startswith("Yeah I'll reach out")
    # No legacy "speakers" key on the response — the rename is observable.
    assert "speakers" not in sig

    ent_by_name = {e["name"]: e for e in view["entities"]}
    assert ent_by_name["Andrew"]["cohort_status"] == "member"
    assert ent_by_name["Alex (flashbots?)"]["cohort_status"] == "external"
    assert ent_by_name["Alex (flashbots?)"]["affiliation"] == "flashbots"
    assert view["topics"] == ["coordination"]


def test_detail_returns_signals_and_entities(client):
    _store_session("demo")
    r = client.get("/transcripts/sessions/demo")
    assert r.status_code == 200
    view = r.json()
    assert view["summary"].startswith("They locked")
    assert view["signals"][0]["kind"] == "decision"
    assert view["entities"][0]["name"] == "matcher"


def test_detail_404_for_unknown_session(client):
    r = client.get("/transcripts/sessions/does-not-exist")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"]


# ---------------------------------------------------------------------------
# The privacy guard — every endpoint, every shape: raw_diarization OUT.
# ---------------------------------------------------------------------------

def test_raw_diarization_never_appears_in_list_response(client):
    _store_session("demo")
    body = client.get("/transcripts/sessions").text
    assert "raw_diarization" not in body
    assert _SECRET_RAW_TEXT not in body, "raw segment text leaked through the list endpoint"


def test_raw_diarization_never_appears_in_detail_response(client):
    _store_session("demo")
    body = client.get("/transcripts/sessions/demo").text
    assert "raw_diarization" not in body
    assert _SECRET_RAW_TEXT not in body, "raw segment text leaked through the detail endpoint"


def test_source_quote_is_intentionally_served(client):
    """v1: ``source_quote`` is API-served alongside the rest of derived.

    The privacy posture treats the TEE as the boundary, not field-level
    stripping. ``raw_diarization`` remains the only stripped field. A 120-
    char quote chip per signal is no more sensitive than ``signals[].text``
    which is already returned.
    """
    sess = _store_session("demo")
    sess.derived.signals[0].source_quote = "DELIBERATELY-SERVED-QUOTE-12345"
    store.save_session(sess)
    body = client.get("/transcripts/sessions/demo").text
    assert "source_quote" in body
    assert "DELIBERATELY-SERVED-QUOTE-12345" in body


def test_to_card_and_to_view_helpers_omit_raw_directly():
    """Guard against a future refactor that bypasses the HTTP layer."""
    sess = Session(
        session_id="x",
        raw_diarization=[RawSegment(speaker="Shaw", text=_SECRET_RAW_TEXT, start=0.0)],
        metadata=SessionMetadata(date="2026-05-20", source="otter"),
        derived=Derived(summary="ok"),
    )
    for payload in (to_card(sess), to_view(sess)):
        # No raw key, no raw text content anywhere — recursive scan.
        blob = json.dumps(payload)
        assert "raw_diarization" not in blob
        assert _SECRET_RAW_TEXT not in blob


# ---------------------------------------------------------------------------
# can_see — demo-hardcoded permission rule (§D.1)
# Default visibility is "cohort" → everyone (incl. anonymous) sees the
# session. Switching a session to "owner-only" engages the owner +
# speaker branches.
# ---------------------------------------------------------------------------

def test_can_see_visibility_cohort_returns_true_for_everyone(client):
    """Default-visibility ("cohort") is the unchanged-from-stub branch:
    anonymous AND any viewer both see the session. This is the path the
    existing dashboard (no picker yet) walks."""
    from api.transcripts_routes import can_see
    sess = _store_session("demo")
    assert sess.metadata.visibility == "cohort"
    assert can_see(None, sess) is True
    assert can_see("any-viewer", sess) is True


def _make_owner_only_session(sid: str = "private", owner: str | None = None):
    """Build a private session with arbitrary visibility/owner."""
    sess = _store_session(sid)
    md = sess.metadata.model_copy(update={"visibility": "owner-only", "owner": owner})
    sess = sess.model_copy(update={"metadata": md})
    store.save_session(sess)
    return sess


def test_can_see_owner_only_blocks_anonymous_viewer(client):
    from api.transcripts_routes import can_see
    sess = _make_owner_only_session(owner="shaw-walters")
    assert can_see(None, sess) is False


def test_can_see_owner_only_allows_owner(client):
    from api.transcripts_routes import can_see
    sess = _make_owner_only_session(owner="shaw-walters")
    assert can_see("shaw-walters", sess) is True


def test_can_see_owner_only_allows_speaker_via_resolved_speakers(client):
    """The fixture's resolved_speakers maps `Shaw → shaw-walters`, so
    even without owner == viewer, a viewer matching a speaker's
    record_id sees the session."""
    from api.transcripts_routes import can_see
    sess = _make_owner_only_session(owner=None)
    assert can_see("shaw-walters", sess) is True


def test_can_see_owner_only_blocks_unrelated_viewer(client):
    from api.transcripts_routes import can_see
    sess = _make_owner_only_session(owner="shaw-walters")
    assert can_see("someone-else", sess) is False


def test_list_sessions_filters_by_viewer_query_param(client):
    """The list endpoint accepts ?viewer=<rid> and only returns sessions
    `can_see` allows. Anonymous callers still see the default-cohort
    sessions; owner-only sessions are hidden from them."""
    _store_session("public", date="2026-05-20")  # visibility=cohort
    _make_owner_only_session("private")          # visibility=owner-only, owner=None
    # Anonymous: only the public session is returned.
    ids_anon = [c["session_id"] for c in client.get("/transcripts/sessions").json()]
    assert "public" in ids_anon and "private" not in ids_anon
    # Viewer who spoke in private (Shaw) sees both.
    ids_speaker = [
        c["session_id"]
        for c in client.get("/transcripts/sessions?viewer=shaw-walters").json()
    ]
    assert "public" in ids_speaker and "private" in ids_speaker


def test_get_session_403s_when_viewer_cannot_see(client):
    """The detail endpoint enforces can_see — anonymous viewer + an
    owner-only session → 403 (not 404)."""
    _make_owner_only_session("private", owner="shaw-walters")
    r = client.get("/transcripts/sessions/private")
    assert r.status_code == 403


def test_list_filtering_by_source_and_date_works(client):
    _store_session("a", date="2026-05-10")
    _store_session("b", date="2026-05-20")
    r = client.get("/transcripts/sessions?date_from=2026-05-15")
    ids = [c["session_id"] for c in r.json()]
    assert ids == ["b"]


# ---------------------------------------------------------------------------
# Unenriched session still renders (derived is empty but no crash)
# ---------------------------------------------------------------------------

def test_unenriched_session_returns_card_with_nulls(client):
    _store_session("unenr", enriched=False)
    r = client.get("/transcripts/sessions/unenr")
    assert r.status_code == 200
    v = r.json()
    assert v["summary"] is None
    assert v["signals"] == []
    assert v["entities"] == []
