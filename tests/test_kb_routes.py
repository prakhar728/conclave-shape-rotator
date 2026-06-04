"""HTTP tests for /api/workspaces/{id}/entities + /obligations (C18/C19).

Auth via the real verify-otp flow (Supabase monkeypatched), mirroring
test_workspaces_routes.py. KB rows seeded directly via storage.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storage import kb_graph
from storage.sqlite import _get_conn
from transcripts import store
from transcripts.models import Derived, RawSegment, Session, SessionMetadata


@pytest.fixture(autouse=True)
def _clean_tables():
    from tests.conftest import reset_workspace_domain_tables
    conn = _get_conn()
    conn.execute("DELETE FROM ingest_metrics")
    conn.execute("DELETE FROM obligations")
    conn.execute("DELETE FROM entity_mentions")
    conn.execute("DELETE FROM embeddings WHERE source_kind IN ('entity','obligation')")
    conn.execute("DELETE FROM entities")
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


def _seed_world(client: TestClient, email: str):
    """Login; bind one session to the user's personal workspace; seed
    one entity (2 mentions) + one current obligation owned by it."""
    _login(client, email)
    ws = client.get("/api/workspaces").json()["workspaces"][0]
    wsid = ws["id"]

    sid = f"kb-rt-{email.split('@')[0]}"
    store.save_session(Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="Ada", text="hello", start=0.0, end=1.0)],
        metadata=SessionMetadata(date="2026-06-04", source="test", tags=[]),
        derived=Derived(),
    ))
    user_row = _get_conn().execute(
        "SELECT id FROM users WHERE email = ?", (email,)
    ).fetchone()
    store.set_workspace(sid, workspace_id=wsid,
                        owner_user_id=user_row["id"], visibility="owner-only")

    eid = kb_graph.insert_entity("person", "Ada Lovelace", ["Ada"])
    kb_graph.add_mentions(eid, sid, [0, 1], "Ada")
    oid = kb_graph.insert_obligation(
        {"type": "action", "description": "Ada ships importer",
         "turn_ids": [0], "owner_entity_id": eid,
         "owner_raw_text": "Ada", "status_inferred": "open", "importance": 7},
        session_id=sid, model_version="x1.0",
    )
    return wsid, sid, eid, oid


def test_unauthenticated_401(client: TestClient):
    assert client.get("/api/workspaces/w/entities").status_code == 401
    assert client.get("/api/workspaces/w/obligations").status_code == 401


def test_nonmember_404(client: TestClient):
    wsid, *_ = _seed_world(client, "owner@example.com")
    client.cookies.clear()
    _login(client, "intruder@example.com")
    assert client.get(f"/api/workspaces/{wsid}/entities").status_code == 404
    assert client.get(f"/api/workspaces/{wsid}/obligations").status_code == 404


def test_entities_list_with_counts_and_type_filter(client: TestClient):
    wsid, sid, eid, _ = _seed_world(client, "alice@example.com")
    r = client.get(f"/api/workspaces/{wsid}/entities")
    assert r.status_code == 200
    ents = r.json()["entities"]
    assert len(ents) == 1
    assert ents[0]["canonical_name"] == "Ada Lovelace"
    assert ents[0]["mention_count"] == 2
    assert ents[0]["meeting_count"] == 1
    # type filter
    assert client.get(
        f"/api/workspaces/{wsid}/entities", params={"type": "tool"}
    ).json()["entities"] == []


def test_entity_detail_case_insensitive_and_url_encoded(client: TestClient):
    wsid, sid, eid, oid = _seed_world(client, "bob@example.com")
    r = client.get(f"/api/workspaces/{wsid}/entities/ada%20lovelace")
    assert r.status_code == 200
    body = r.json()
    assert body["entity"]["id"] == eid
    assert body["meetings"][0]["session_id"] == sid
    assert body["meetings"][0]["turn_ids"] == [0, 1]
    assert body["obligations"][0]["id"] == oid


def test_entity_detail_404_unknown(client: TestClient):
    wsid, *_ = _seed_world(client, "carol@example.com")
    assert client.get(
        f"/api/workspaces/{wsid}/entities/Nobody"
    ).status_code == 404


def test_obligations_list_and_filters(client: TestClient):
    wsid, sid, eid, oid = _seed_world(client, "dave@example.com")
    r = client.get(f"/api/workspaces/{wsid}/obligations")
    assert r.status_code == 200
    obs = r.json()["obligations"]
    assert [o["id"] for o in obs] == [oid]
    # filters: matching + excluding
    assert client.get(
        f"/api/workspaces/{wsid}/obligations",
        params={"type": "action", "status": "open", "owner_entity_id": eid},
    ).json()["obligations"]
    assert client.get(
        f"/api/workspaces/{wsid}/obligations", params={"type": "blocker"}
    ).json()["obligations"] == []
    assert client.get(
        f"/api/workspaces/{wsid}/obligations", params={"status": "resolved"}
    ).json()["obligations"] == []


def test_obligation_detail_and_visibility_404(client: TestClient):
    wsid, sid, eid, oid = _seed_world(client, "erin@example.com")
    r = client.get(f"/api/workspaces/{wsid}/obligations/{oid}")
    assert r.status_code == 200
    assert r.json()["obligation"]["description"] == "Ada ships importer"

    # another user's workspace can't see it — 404, not 403 (no existence leak)
    client.cookies.clear()
    _login(client, "frank@example.com")
    other_ws = client.get("/api/workspaces").json()["workspaces"][0]["id"]
    assert client.get(
        f"/api/workspaces/{other_ws}/obligations/{oid}"
    ).status_code == 404


def test_invalidated_obligation_not_listed(client: TestClient):
    wsid, sid, eid, oid = _seed_world(client, "grace@example.com")
    kb_graph.invalidate_obligation(oid)
    assert client.get(
        f"/api/workspaces/{wsid}/obligations"
    ).json()["obligations"] == []
