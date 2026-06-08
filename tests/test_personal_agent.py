"""Phase 2 — PersonalMemory permission-boundary tests.

The core property under test: a person's personal agent reads ONLY what
that person is permitted to see, by construction. Disjoint-visibility users
get disjoint scope / entities / obligations / search results; shared and
workspace visibility resolve correctly; an empty scope returns nothing.

Seeded directly via storage (no HTTP), mirroring tests/test_kb_routes.py.
Search is exercised FTS-only (no Ollama dependency) — the permission scope
is identical on both retrieval legs (both take ``session_ids``).
"""
from __future__ import annotations

import pytest

from companion.personal_agent import PersonalMemory
from infra import identity, workspaces
from storage import kb, kb_graph
from storage.sqlite import _get_conn, _now
from transcripts import store
from transcripts.kb_chunk import chunk_transcript
from transcripts.models import Derived, RawSegment, Session, SessionMetadata


@pytest.fixture(autouse=True)
def _clean_tables():
    from tests.conftest import reset_workspace_domain_tables

    conn = _get_conn()
    conn.execute("DELETE FROM obligations")
    conn.execute("DELETE FROM entity_mentions")
    conn.execute("DELETE FROM entities")
    conn.execute("DELETE FROM chunks")
    reset_workspace_domain_tables()
    yield


def _seed_session(sid, *, owner_id, visibility, wsid, entity, oblig_desc, chunk_text):
    """One workspace-bound session + an entity (2 mentions) + an obligation
    + an FTS-indexed chunk, all attributable to a single owner/visibility."""
    store.save_session(Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="Spk", text=chunk_text, start=0.0, end=1.0)],
        metadata=SessionMetadata(date="2026-06-08", source="test", tags=[]),
        derived=Derived(),
    ))
    store.set_workspace(sid, workspace_id=wsid, owner_user_id=owner_id, visibility=visibility)
    eid = kb_graph.insert_entity("project", entity, [entity])
    kb_graph.add_mentions(eid, sid, [0], entity)
    kb_graph.add_mentions(eid, sid, [0], entity)
    kb_graph.insert_obligation(
        {"type": "action", "description": oblig_desc, "turn_ids": [0],
         "owner_entity_id": eid, "owner_raw_text": "Spk",
         "status_inferred": "open", "importance": 5},
        session_id=sid, model_version="t1.0",
    )
    kb.save_chunks(sid, chunk_transcript([{"speaker": "Spk", "text": chunk_text}]))
    return eid


@pytest.fixture
def world():
    """alice + bob, both members of one workspace, with four sessions:
    alice-private, bob-private, shared(alice→bob), workspace-visible."""
    alice = identity.upsert_user_by_supabase("sb-alice", "alice@ex.com", "Alice")
    bob = identity.upsert_user_by_supabase("sb-bob", "bob@ex.com", "Bob")
    ws = workspaces.create_workspace("Team", alice["id"])
    wsid = ws["id"]
    # bob is a member too (needed for workspace-visibility sessions).
    _get_conn().execute(
        "INSERT INTO workspace_members (workspace_id, user_id, role, added_at, added_by)"
        " VALUES (?, ?, 'member', ?, ?)",
        (wsid, bob["id"], _now(), alice["id"]),
    )

    _seed_session("s-alice", owner_id=alice["id"], visibility="owner-only", wsid=wsid,
                  entity="AliceProj", oblig_desc="alice ships importer",
                  chunk_text="alice private roadmap secret")
    _seed_session("s-bob", owner_id=bob["id"], visibility="owner-only", wsid=wsid,
                  entity="BobProj", oblig_desc="bob ships exporter",
                  chunk_text="bob private roadmap secret")
    _seed_session("s-shared", owner_id=alice["id"], visibility="shared", wsid=wsid,
                  entity="SharedTopic", oblig_desc="ship the shared design",
                  chunk_text="shared design notes roadmap")
    workspaces.add_meeting_share("s-shared", bob["email"], alice["id"])
    _seed_session("s-ws", owner_id=alice["id"], visibility="workspace", wsid=wsid,
                  entity="WsTopic", oblig_desc="workspace wide action",
                  chunk_text="workspace visible roadmap")
    return {"alice": alice, "bob": bob, "wsid": wsid}


# ---------------------------------------------------------------------------
# Scope boundary
# ---------------------------------------------------------------------------

def test_scope_excludes_other_users_private_sessions(world):
    alice = PersonalMemory(world["alice"], world["wsid"])
    bob = PersonalMemory(world["bob"], world["wsid"])

    assert "s-alice" in alice.session_ids
    assert "s-shared" in alice.session_ids   # alice owns it
    assert "s-ws" in alice.session_ids        # workspace-visible
    assert "s-bob" not in alice.session_ids   # bob's private — never

    assert "s-bob" in bob.session_ids
    assert "s-shared" in bob.session_ids       # shared with bob's email
    assert "s-ws" in bob.session_ids           # bob is a member
    assert "s-alice" not in bob.session_ids    # alice's private — never


# ---------------------------------------------------------------------------
# Entities / obligations isolation
# ---------------------------------------------------------------------------

def test_entities_respect_scope(world):
    alice = PersonalMemory(world["alice"], world["wsid"])
    bob = PersonalMemory(world["bob"], world["wsid"])
    a_names = {e["canonical_name"] for e in alice.entities()}
    b_names = {e["canonical_name"] for e in bob.entities()}

    assert "AliceProj" in a_names and "BobProj" not in a_names
    assert "BobProj" in b_names and "AliceProj" not in b_names
    # both see shared + workspace entities
    assert {"SharedTopic", "WsTopic"} <= a_names
    assert {"SharedTopic", "WsTopic"} <= b_names


def test_entities_mention_counts_reuse_route_projection(world):
    alice = PersonalMemory(world["alice"], world["wsid"])
    proj = next(e for e in alice.entities() if e["canonical_name"] == "AliceProj")
    assert proj["mention_count"] == 2      # two add_mentions calls
    assert proj["meeting_count"] == 1


def test_obligations_respect_scope(world):
    alice = PersonalMemory(world["alice"], world["wsid"])
    bob = PersonalMemory(world["bob"], world["wsid"])
    a_descs = {o["description"] for o in alice.obligations()}
    b_descs = {o["description"] for o in bob.obligations()}

    assert "alice ships importer" in a_descs
    assert "bob ships exporter" not in a_descs
    assert "bob ships exporter" in b_descs
    assert "alice ships importer" not in b_descs


# ---------------------------------------------------------------------------
# Search isolation (FTS-only; identical term across two private sessions)
# ---------------------------------------------------------------------------

def test_search_never_crosses_scope(world):
    alice = PersonalMemory(world["alice"], world["wsid"])
    # "secret" appears in BOTH s-alice and s-bob private chunks.
    hits = alice.search("secret roadmap", top_k=10)
    sids = {h["session_id"] for h in hits}
    assert sids, "expected at least alice's own chunk to match"
    assert "s-bob" not in sids                       # the key assertion
    assert sids <= set(alice.session_ids)            # never outside scope


# ---------------------------------------------------------------------------
# Empty scope + non-member
# ---------------------------------------------------------------------------

def test_empty_scope_returns_nothing(world):
    pm = PersonalMemory(world["alice"], world["wsid"], session_ids=[])
    assert pm.has_scope is False
    assert pm.entities() == []
    assert pm.obligations() == []
    assert pm.search("anything") == []
    prof = pm.profile()
    assert prof["session_count"] == 0 and prof["top_entities"] == []


def test_nonmember_cannot_see_private_entities(world):
    carol = identity.upsert_user_by_supabase("sb-carol", "carol@ex.com", "Carol")
    pm = PersonalMemory(carol, world["wsid"])
    names = {e["canonical_name"] for e in pm.entities()}
    # Carol is not owner/shared/member of the private sessions.
    assert "AliceProj" not in names
    assert "BobProj" not in names


# ---------------------------------------------------------------------------
# Profile (Phase-3 substrate) is scope-bounded
# ---------------------------------------------------------------------------

def test_profile_is_scope_bounded(world):
    alice = PersonalMemory(world["alice"], world["wsid"])
    prof = alice.profile()
    names = {e["canonical_name"] for e in prof["top_entities"]}
    assert "BobProj" not in names
    assert prof["email"] == "alice@ex.com"
    assert prof["obligation_counts"].get("action", 0) >= 1
