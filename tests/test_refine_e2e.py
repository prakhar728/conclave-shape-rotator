"""Part 1 — end-to-end smoke over the REAL HTTP stack (auth → routes → DB).

One flow exercises the whole editor: login → draft → GET v2 → edit a word → tag an
entity → assign a speaker → GET v2 (all persisted) → approve → GET v2 (frozen). This
is the live-wire proof the manual checklist (docs/plans/transcript-refine-verify.md)
walks in the browser. Run `pytest -s tests/test_refine_e2e.py` to see before/after.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from infra import identity
from transcripts import candidate, store
from transcripts.models import RawSegment, Session, SessionMetadata


@pytest.fixture(autouse=True)
def _clean():
    from storage.sqlite import _get_conn
    from tests.conftest import reset_workspace_domain_tables
    _get_conn().execute("DELETE FROM transcript_sessions")
    reset_workspace_domain_tables()
    yield


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    # deterministic detection + no LLM on approve (we're testing the wire, not models)
    monkeypatch.setattr(candidate, "detect", lambda text, user_id: (text.split(), []))
    monkeypatch.setattr(candidate, "classify_correction", lambda t: "promote")
    import api.transcripts_routes as routes
    monkeypatch.setattr(routes, "_build_kb", lambda sid: None)
    monkeypatch.setattr(routes, "_rederive_insights_from_v2", lambda sid: None)


@pytest.fixture
def client(monkeypatch) -> TestClient:
    import auth.routes as ar
    from infra import supabase_auth as sb
    for mod in (sb, ar):
        monkeypatch.setattr(mod, "supabase_enabled", lambda: True)
    monkeypatch.setattr(sb, "send_otp", lambda email: None)
    monkeypatch.setattr(sb, "verify_otp", lambda email, token: f"sb-{email}")
    monkeypatch.setattr(ar, "_supabase_send_otp", lambda email: None)
    monkeypatch.setattr(ar, "_supabase_verify_otp", lambda email, token: f"sb-{email}")
    from main import app
    return TestClient(app)


def test_full_refine_roundtrip_over_http(client):
    # --- login (real OTP route, mocked provider) ---
    r = client.post("/auth/v1/verify-otp", json={"email": "alice@example.com", "token": "000000"})
    assert r.status_code == 200, r.text
    user = identity.upsert_user_by_supabase("sb-alice@example.com", "alice@example.com")
    wsid = client.get("/api/workspaces").json()["workspaces"][0]["id"]

    # --- a meeting with a draft ---
    sid = "e2e-1"
    store.save_session(Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="speaker_1", text="we use the DStack protocol")],
        metadata=SessionMetadata(date="2026-06-22", source="test"),
    ))
    store.set_workspace(sid, workspace_id=wsid, owner_user_id=user["id"], visibility="owner-only")
    store.create_v2_draft(sid)

    def get_v2():
        resp = client.get(f"/transcripts/sessions/{sid}/v2")
        assert resp.status_code == 200, resp.text
        return resp.json()

    before = get_v2()
    print("\nBEFORE:", before["status"], "| tokens:", before["segments"][0]["tokens"],
          "| annotations:", len(before["annotations"]), "| stale:", before["insights_stale"])
    assert before["status"] == "draft"
    assert before["segments"][0]["tokens"][3] == "DStack"

    # --- edit a word (case 1) ---
    r = client.post(f"/transcripts/sessions/{sid}/v2/edit-token",
                    json={"segment_id": 0, "token_idx": 3, "new_text": "Dstack"})
    assert r.status_code == 200, r.text

    # --- tag an entity (case 3) ---
    r = client.post(f"/transcripts/sessions/{sid}/v2/tag-entity",
                    json={"segment_id": 0, "token_start": 3, "token_end": 5, "surface": "Dstack protocol", "type": "project"})
    assert r.status_code == 200, r.text

    # --- assign a speaker (case 4) ---
    r = client.post(f"/transcripts/sessions/{sid}/v2/assign-speaker",
                    json={"segment_id": 0, "name": "Alice"})
    assert r.status_code == 200, r.text

    after = get_v2()
    print("AFTER :", after["status"], "| tokens:", after["segments"][0]["tokens"],
          "| speaker:", after["segments"][0]["speaker_name"],
          "| annotations:", [(a["surface"], a["type"], a["state"]) for a in after["annotations"]],
          "| stale:", after["insights_stale"])
    # case 1: the edit persisted; case 2: every OTHER word is identical
    assert after["segments"][0]["tokens"] == ["we", "use", "the", "Dstack", "protocol"]
    # case 4: speaker persisted
    assert after["segments"][0]["speaker_name"] == "Alice"
    # case 3: the tag is now a known annotation Part 2 will read
    assert any(a["surface"] == "Dstack protocol" and a["type"] == "project" and a["state"] == "known"
               for a in after["annotations"])
    # case 9: edits marked insights stale
    assert after["insights_stale"] is True

    # --- approve (case 7) ---
    r = client.post(f"/transcripts/sessions/{sid}/approve")
    assert r.status_code == 200, r.text
    final = get_v2()
    print("FINAL :", final["status"], "(frozen)\n")
    assert final["status"] == "approved"

    # case 8: edits after approve are blocked
    blocked = client.post(f"/transcripts/sessions/{sid}/v2/edit-token",
                          json={"segment_id": 0, "token_idx": 0, "new_text": "nope"})
    assert blocked.status_code == 409, blocked.text

    # case 6: raw transcript was never mutated
    raw = store.load_session(sid).raw_diarization[0].text
    assert raw == "we use the DStack protocol"
