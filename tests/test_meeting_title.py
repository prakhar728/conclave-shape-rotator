"""Task #40 — short meeting title (distinct from the summary body).

Covers: `_sanitize_title`, title fold-in on both enrich shapes (single + reduce),
back-compat when the model emits no title, DTO exposure with the manual-override
precedence, and the owner-gated rename endpoint (incl. clear + auth gating).
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api.transcripts_routes import to_card, to_view
from transcripts import store
from transcripts.enrich import _sanitize_title, enrich_session
from transcripts.models import Derived, RawSegment, Session, SessionMetadata


class FakeLLM:
    model_name = "fake-llm"

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls: list = []

    def invoke(self, messages):
        self.calls.append(list(messages))
        item = self._responses.pop(0)
        return type("Resp", (), {"content": json.dumps(item)})()


# --- _sanitize_title -------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Live diarization debugging", "Live diarization debugging"),
        ('"Live diarization debugging!"', "Live diarization debugging"),
        ("Shipping the matcher.", "Shipping the matcher"),
        ("  extra   whitespace  ", "extra whitespace"),
        ("one two three four five six seven eight", "one two three four five six seven"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_sanitize_title(raw, expected):
    assert _sanitize_title(raw) == expected


# --- fold-in on both enrich shapes -----------------------------------------

def _short() -> Session:
    return Session(
        session_id="t-short",
        raw_diarization=[RawSegment(speaker="A", text="we shipped the matcher", start=0.0)],
        metadata=SessionMetadata(date="2026-07-02", source="otter"),
    )


def test_title_folds_into_single_chunk_call_without_an_extra_llm_call():
    sess = _short()
    fake = FakeLLM({"title": "Shipping the matcher", "summary": "They shipped it.",
                    "signals": [], "entities": [], "topics": []})
    enrich_session(sess, llm=fake)
    assert len(fake.calls) == 1  # title rides the same call, not a new one
    assert sess.derived.title == "Shipping the matcher"
    assert sess.derived.summary == "They shipped it."


def test_title_is_none_when_model_omits_it_backcompat():
    sess = _short()
    fake = FakeLLM({"summary": "no title here", "signals": [], "entities": [], "topics": []})
    enrich_session(sess, llm=fake)
    assert sess.derived.title is None
    assert sess.derived.summary == "no title here"


def test_title_is_sanitized_from_the_model_output():
    sess = _short()
    fake = FakeLLM({"title": '"Way too many words in this title indeed here now"',
                    "summary": "s", "signals": [], "entities": [], "topics": []})
    enrich_session(sess, llm=fake)
    # 7-word cap + quote strip.
    assert sess.derived.title == "Way too many words in this title"


# --- DTO exposure + manual-override precedence -----------------------------

def test_to_card_exposes_title_and_manual_wins():
    sess = Session(
        session_id="t-dto",
        raw_diarization=[RawSegment(speaker="A", text="hi", start=0.0)],
        metadata=SessionMetadata(date="2026-07-02", source="otter"),
        derived=Derived(title="Auto title", summary="body"),
    )
    assert to_card(sess)["title"] == "Auto title"
    assert to_view(sess)["title"] == "Auto title"
    # An owner rename wins over the auto title.
    sess.metadata.manual_title = "Owner's name"
    assert to_card(sess)["title"] == "Owner's name"


def test_manual_title_survives_regeneration():
    """A regen (re-enrich) refreshes derived.title but must NOT clobber the
    owner's manual_title — the DTO keeps showing the manual one."""
    sess = _short()
    sess.metadata.manual_title = "Owner pinned"
    fake = FakeLLM({"title": "Fresh auto title", "summary": "s2",
                    "signals": [], "entities": [], "topics": []})
    enrich_session(sess, llm=fake)
    assert sess.derived.title == "Fresh auto title"      # auto refreshed
    assert sess.metadata.manual_title == "Owner pinned"  # override untouched
    assert to_card(sess)["title"] == "Owner pinned"      # manual wins on read


# --- rename endpoint (owner-gated) -----------------------------------------

@pytest.fixture(autouse=True)
def _clean():
    from storage.sqlite import _get_conn
    from tests.conftest import reset_workspace_domain_tables
    _get_conn().execute("DELETE FROM transcript_sessions")
    reset_workspace_domain_tables()
    yield


@pytest.fixture
def client(monkeypatch) -> TestClient:
    from infra import supabase_auth as sb
    monkeypatch.setattr(sb, "supabase_enabled", lambda: True)
    monkeypatch.setattr(sb, "send_otp", lambda email: None)
    monkeypatch.setattr(sb, "verify_otp", lambda email, token: f"sb-{email}")
    import auth.routes as ar
    monkeypatch.setattr(ar, "supabase_enabled", lambda: True)
    monkeypatch.setattr(ar, "_supabase_send_otp", lambda email: None)
    monkeypatch.setattr(ar, "_supabase_verify_otp", lambda email, token: f"sb-{email}")
    from main import app
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict:
    r = client.post("/auth/v1/verify-otp", json={"email": email, "token": "000000"})
    assert r.status_code == 200, r.text
    return r.json()


def _owned(client: TestClient, email: str, sid: str) -> dict:
    me = _login(client, email)
    uid, ws_id = me["user"]["id"], me["workspace"]["id"]
    sess = Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="A", text="hi", start=0.0)],
        metadata=SessionMetadata(date="2026-07-02", source="otter"),
        derived=Derived(title="Auto title", summary="body"),
    )
    store.save_session(sess)
    store.set_workspace(sid, ws_id, uid, visibility="owner-only")
    return me


def test_owner_can_rename(client):
    _owned(client, "owner@x.com", "s-ren")
    r = client.patch("/transcripts/sessions/s-ren/title", json={"title": "Board sync notes"})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Board sync notes"
    assert r.json()["manual"] is True
    # Persisted as manual_title (survives reload, wins over auto).
    assert store.load_session("s-ren").metadata.manual_title == "Board sync notes"


def test_blank_title_clears_the_override(client):
    _owned(client, "owner@x.com", "s-clr")
    client.patch("/transcripts/sessions/s-clr/title", json={"title": "temp"})
    r = client.patch("/transcripts/sessions/s-clr/title", json={"title": "   "})
    assert r.status_code == 200, r.text
    assert r.json()["manual"] is False
    # Reverts to the auto title.
    assert r.json()["title"] == "Auto title"
    assert store.load_session("s-clr").metadata.manual_title is None


def test_non_owner_cannot_rename(client):
    _owned(client, "owner@x.com", "s-403")
    # A different logged-in user.
    _login(client, "intruder@x.com")
    r = client.patch("/transcripts/sessions/s-403/title", json={"title": "hijack"})
    assert r.status_code == 403
    assert store.load_session("s-403").metadata.manual_title is None


def test_rename_unknown_session_404(client):
    _login(client, "owner@x.com")
    r = client.patch("/transcripts/sessions/nope/title", json={"title": "x"})
    assert r.status_code == 404
