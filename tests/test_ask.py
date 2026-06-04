"""v1.5 /ask — grounded answer synthesis (fake LLM throughout)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from storage import kb, kb_graph
from storage.sqlite import _get_conn
from storage.vec import vec_available
from transcripts import store
from transcripts.answer import NOT_FOUND_ANSWER, answer_question
from transcripts.kb_chunk import KBChunk
from transcripts.models import Derived, RawSegment, Session, SessionMetadata


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)

        class R:
            content = json.dumps(self.payload)
        R.content = json.dumps(self.payload)
        return R()


CHUNKS = [{"chunk_id": "s1:0", "session_id": "s1",
           "text": "Ada: I'll ship the importer by Friday.", "context_header": ""}]
OBLIGATIONS = [{"id": "ob1", "session_id": "s1", "type": "action",
                "description": "Ada ships importer", "owner_raw_text": "Ada",
                "due_date_raw": "Friday", "status_inferred": "open",
                "ingested_at": "2026-06-04", "importance": 7}]


# ---------------------------------------------------------------------------
# answer_question unit
# ---------------------------------------------------------------------------

def test_answer_happy_path_with_citations():
    llm = FakeLLM({"answer": "Ada ships the importer by Friday.",
                   "citations": ["c1", "o1"]})
    a = answer_question("what is Ada doing?", CHUNKS, OBLIGATIONS, llm=llm)
    assert a.grounded
    assert {c["kind"] for c in a.citations} == {"chunk", "obligation"}
    assert a.citations[0]["session_id"] == "s1"
    # context made it into the prompt
    human = llm.calls[0][1].content
    assert "[c1]" in human and "[o1]" in human and "<context>" in human


def test_hallucinated_citations_dropped():
    llm = FakeLLM({"answer": "Something.", "citations": ["c1", "c9", "o7"]})
    a = answer_question("q?", CHUNKS, OBLIGATIONS, llm=llm)
    assert len(a.citations) == 1  # only c1 is real


def test_assertive_answer_without_citations_degrades():
    llm = FakeLLM({"answer": "Confidently wrong claim.", "citations": []})
    a = answer_question("q?", CHUNKS, OBLIGATIONS, llm=llm)
    assert a.answer == NOT_FOUND_ANSWER and not a.grounded


def test_empty_context_short_circuits_no_llm():
    llm = FakeLLM({"answer": "should never be called"})
    a = answer_question("q?", [], [], llm=llm)
    assert a.answer == NOT_FOUND_ANSWER and llm.calls == []


def test_garbage_output_degrades():
    class Garbage:
        def invoke(self, messages):
            class R:
                content = "no json here"
            return R()
    a = answer_question("q?", CHUNKS, OBLIGATIONS, llm=Garbage())
    assert a.answer == NOT_FOUND_ANSWER


# ---------------------------------------------------------------------------
# /ask route
# ---------------------------------------------------------------------------

pytestmark_db = pytest.mark.skipif(
    not vec_available(_get_conn()), reason="sqlite-vec not loaded",
)


@pytest.fixture(autouse=True)
def _clean():
    from tests.conftest import reset_workspace_domain_tables

    def _purge():
        conn = _get_conn()
        kb.delete_chunks_for_session("kb-ask-1")
        conn.execute("DELETE FROM obligations WHERE session_id = 'kb-ask-1'")
        conn.execute("DELETE FROM transcript_sessions WHERE session_id = 'kb-ask-1'")

    _purge()
    reset_workspace_domain_tables()
    yield
    _purge()


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


def _seed(client, email):
    r = client.post("/auth/v1/verify-otp", json={"email": email, "token": "0"})
    assert r.status_code == 200
    ws = client.get("/api/workspaces").json()["workspaces"][0]
    sid = "kb-ask-1"
    store.save_session(Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="Ada", text="I'll ship the importer by Friday.", start=0.0, end=2.0)],
        metadata=SessionMetadata(date="2026-06-04", source="t", tags=[]),
        derived=Derived(),
    ))
    user_row = _get_conn().execute(
        "SELECT id FROM users WHERE email = ?", (email,)
    ).fetchone()
    store.set_workspace(sid, workspace_id=ws["id"],
                        owner_user_id=user_row["id"], visibility="owner-only")
    kb.save_chunks(sid, [KBChunk(0, [0], "Ada: I'll ship the importer by Friday.", 10)])
    kb_graph.insert_obligation(
        {"type": "action", "description": "Ada ships the importer",
         "turn_ids": [0], "owner_raw_text": "Ada", "due_date_raw": "Friday",
         "status_inferred": "open", "importance": 7},
        session_id=sid, model_version="x1.0",
    )
    return ws["id"]


def test_ask_disabled_404(client, monkeypatch):
    monkeypatch.delenv("ENABLE_ASK", raising=False)
    wsid = _seed(client, "a0@example.com")
    assert client.post(f"/api/workspaces/{wsid}/ask",
                       json={"question": "what is Ada doing?"}).status_code == 404


def test_ask_end_to_end(client, monkeypatch):
    monkeypatch.setenv("ENABLE_ASK", "1")
    wsid = _seed(client, "a1@example.com")
    monkeypatch.setattr(  # no Ollama in tests
        "transcripts.embed.embed_texts",
        lambda texts, **kw: (_ for _ in ()).throw(RuntimeError("no vec")),
    )
    monkeypatch.setattr(
        "transcripts.answer.invoke_json",
        lambda messages, **kw: {"answer": "Ada ships the importer by Friday.",
                                "citations": ["c1", "o1"]},
    )
    r = client.post(f"/api/workspaces/{wsid}/ask",
                    json={"question": "when will the importer ship?"})
    assert r.status_code == 200
    body = r.json()
    assert body["grounded"]
    assert "Friday" in body["answer"]
    kinds = {c["kind"] for c in body["citations"]}
    assert kinds == {"chunk", "obligation"}


def test_ask_auth_and_validation(client, monkeypatch):
    monkeypatch.setenv("ENABLE_ASK", "1")
    assert client.post("/api/workspaces/w/ask",
                       json={"question": "hi there"}).status_code == 401
    wsid = _seed(client, "a2@example.com")
    assert client.post(f"/api/workspaces/{wsid}/ask",
                       json={"question": "hi"}).status_code == 422  # min_length


def test_ask_visibility_empty_workspace(client, monkeypatch):
    monkeypatch.setenv("ENABLE_ASK", "1")
    _seed(client, "owner-ask@example.com")
    client.cookies.clear()
    r = client.post("/auth/v1/verify-otp",
                    json={"email": "other-ask@example.com", "token": "0"})
    assert r.status_code == 200
    other_ws = client.get("/api/workspaces").json()["workspaces"][0]["id"]
    monkeypatch.setattr(
        "transcripts.answer.invoke_json",
        lambda messages, **kw: pytest.fail("LLM must not see another user's data"),
    )
    monkeypatch.setattr(
        "transcripts.embed.embed_texts",
        lambda texts, **kw: (_ for _ in ()).throw(RuntimeError("no vec")),
    )
    r = client.post(f"/api/workspaces/{other_ws}/ask",
                    json={"question": "what is Ada shipping on Friday?"})
    assert r.status_code == 200
    body = r.json()
    # other user's content contributes nothing; demo sessions may exist but
    # don't contain Ada's importer — at minimum the seeded data must not leak
    assert "kb-ask-1" not in json.dumps(body["citations"])
