"""
Step 9 tests — MCP plugin surface for interview_reflection.

Uses the MCP SDK's in-memory transport so tests bypass HTTP entirely. Because
the auth middleware does NOT run on that transport, tests set the caller-token
context directly via `set_caller_token_for_test`.

Coverage:
  - whoami / instance_info / verify_attestation (graceful)
  - submit_interview: admin happy path + user-role denial
  - get_interview_results: admin sees all; user sees only own
  - list_interviewees: admin sees ledger entries; user denied
  - get_team_context: stub returns shape
  - signed_payload field present (None in v0) and timestamp populated
  - server-instructions are populated
"""
from __future__ import annotations

import os
os.environ.setdefault("CONCLAVE_DB_PATH", ":memory:")
os.environ.setdefault("CONCLAVE_DISABLE_SCHEDULER", "1")

import json
import secrets
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import TextContent

import storage
from skills.interview_reflection.mcp_server import (
    build_mcp_server,
    reset_caller_token_for_test,
    set_caller_token_for_test,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "interview_reflection"


# --- Fixtures ---

@pytest.fixture(autouse=True)
def clear_stores():
    storage.reset_all()
    yield


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    import skills.interview_reflection.aggregate as agg_mod
    monkeypatch.setattr(agg_mod, "DEFAULT_STORAGE_ROOT", tmp_path)
    yield


@pytest.fixture(autouse=True)
def mocked_llm(monkeypatch):
    """Stub cycling profile → rubric items across get_llm() invocations."""
    call_count = {"n": 0}

    class _Stub:
        def invoke(self, _messages):
            call_count["n"] += 1
            if call_count["n"] % 2 == 1:
                payload = {
                    "building": "a consumer app",
                    "building_tags": ["consumer-social"],
                    "stage": "early-traction",
                    "offers": [{"text": "frontend help", "tags": ["frontend"],
                                "quote": "benign offer quote"}],
                }
            else:
                payload = {"items": {f"CO{i}": {"score": 4, "quote": "ev"} for i in range(1, 6)}}
            return SimpleNamespace(content=json.dumps(payload))

    monkeypatch.setattr("config.get_llm", lambda *_a, **_k: _Stub())
    yield


def _make_instance_and_tokens() -> tuple[str, dict, dict]:
    """Seed an instance and create admin + user tokens.

    Returns: (instance_id, admin_token_info, user_token_info) where the
    *_token_info dicts are the shape storage.get_token would return — that's
    what the MCP middleware would have stuffed onto the contextvar.
    """
    instance_id = str(uuid.uuid4())
    storage.create_instance(
        instance_id=instance_id,
        skill_name="interview_reflection",
        config={"criteria": {}, "guidelines": "", "instance_id": instance_id},
        threshold=999_999,
        name="MCP Test Cohort",
    )
    admin_raw = secrets.token_urlsafe(16)
    user_raw = secrets.token_urlsafe(16)
    storage.create_token(admin_raw, instance_id, role="admin")
    storage.create_token(user_raw, instance_id, role="user")

    admin_info = storage.get_token(admin_raw)
    admin_info["_raw_token"] = admin_raw
    user_info = storage.get_token(user_raw)
    user_info["_raw_token"] = user_raw

    return instance_id, admin_info, user_info


def _text(result) -> str:
    """Extract the JSON body from a tool result."""
    # FastMCP returns CallToolResult with .content list of TextContent
    parts = []
    for c in result.content:
        if isinstance(c, TextContent):
            parts.append(c.text)
    return "".join(parts)


def _payload(result) -> dict:
    return json.loads(_text(result))


# --- Tests ---

@pytest.mark.asyncio
async def test_whoami_reports_role_and_instance():
    instance_id, admin_info, _ = _make_instance_and_tokens()
    token = set_caller_token_for_test(admin_info)
    try:
        async with create_connected_server_and_client_session(build_mcp_server()) as client:
            await client.initialize()
            result = await client.call_tool("whoami", {})
            data = _payload(result)
            assert data["role"] == "admin"
            assert data["instance_id"] == instance_id
            assert "signed_payload" in data  # contract present, value None in v0
            assert data["signed_payload"] is None
            assert data["_emitted_at"]
    finally:
        reset_caller_token_for_test(token)


@pytest.mark.asyncio
async def test_instance_info_returns_skill_metadata():
    instance_id, admin_info, _ = _make_instance_and_tokens()
    token = set_caller_token_for_test(admin_info)
    try:
        async with create_connected_server_and_client_session(build_mcp_server()) as client:
            await client.initialize()
            result = await client.call_tool("instance_info", {})
            data = _payload(result)
            assert data["instance_id"] == instance_id
            assert data["skill"] == "interview_reflection"
            assert data.get("skill_version")
            assert data["name"] == "MCP Test Cohort"
    finally:
        reset_caller_token_for_test(token)


@pytest.mark.asyncio
async def test_verify_attestation_handles_unavailable_backend():
    _instance_id, admin_info, _ = _make_instance_and_tokens()
    token = set_caller_token_for_test(admin_info)
    try:
        async with create_connected_server_and_client_session(build_mcp_server()) as client:
            await client.initialize()
            result = await client.call_tool("verify_attestation", {"nonce": "deadbeef"})
            data = _payload(result)
            # Either we got a real quote (when running inside a TDX environment)
            # OR we got a graceful error string. We do NOT crash either way.
            assert data.get("nonce") == "deadbeef"
            assert "quote" in data or "error" in data
    finally:
        reset_caller_token_for_test(token)


@pytest.mark.asyncio
async def test_submit_interview_admin_happy_path():
    instance_id, admin_info, _ = _make_instance_and_tokens()
    token = set_caller_token_for_test(admin_info)
    try:
        transcript = (FIXTURE_DIR / "prod_internal.txt").read_text()
        async with create_connected_server_and_client_session(build_mcp_server()) as client:
            await client.initialize()
            result = await client.call_tool("submit_interview", {
                "transcript": transcript,
                "interviewee_slug": "leo",
            })
            data = _payload(result)
            assert data["submission_id"]
            assert data["result"]["interviewee_slug"] == "leo"
            assert "collaboration_profile" in data["result"]
    finally:
        reset_caller_token_for_test(token)


@pytest.mark.asyncio
async def test_submit_interview_user_role_denied():
    _instance_id, _admin, user_info = _make_instance_and_tokens()
    token = set_caller_token_for_test(user_info)
    try:
        async with create_connected_server_and_client_session(build_mcp_server()) as client:
            await client.initialize()
            result = await client.call_tool("submit_interview", {
                "transcript": "x",
                "interviewee_slug": "leo",
            })
            data = _payload(result)
            assert data.get("error") and "admin" in data["error"].lower()
    finally:
        reset_caller_token_for_test(token)


@pytest.mark.asyncio
async def test_get_interview_results_admin_sees_all():
    instance_id, admin_info, _ = _make_instance_and_tokens()
    token = set_caller_token_for_test(admin_info)
    try:
        transcript = (FIXTURE_DIR / "prod_internal.txt").read_text()
        async with create_connected_server_and_client_session(build_mcp_server()) as client:
            await client.initialize()
            await client.call_tool("submit_interview", {
                "transcript": transcript,
                "interviewee_slug": "leo",
            })
            result = await client.call_tool("get_interview_results", {
                "interviewee_slug": "leo",
            })
            data = _payload(result)
            assert data["session_count"] >= 1
            assert data["interviewee_slug"] == "leo"
    finally:
        reset_caller_token_for_test(token)


@pytest.mark.asyncio
async def test_get_interview_results_user_filtered_to_own():
    """User-role token sees only digests linked to its own submissions."""
    instance_id, admin_info, user_info = _make_instance_and_tokens()

    # Admin submits a session for "leo" — user token should NOT see it,
    # since admin owns the submission.
    admin_tok = set_caller_token_for_test(admin_info)
    try:
        transcript = (FIXTURE_DIR / "prod_internal.txt").read_text()
        async with create_connected_server_and_client_session(build_mcp_server()) as client:
            await client.initialize()
            await client.call_tool("submit_interview", {
                "transcript": transcript,
                "interviewee_slug": "leo",
            })
    finally:
        reset_caller_token_for_test(admin_tok)

    user_tok = set_caller_token_for_test(user_info)
    try:
        async with create_connected_server_and_client_session(build_mcp_server()) as client:
            await client.initialize()
            result = await client.call_tool("get_interview_results", {
                "interviewee_slug": "leo",
            })
            data = _payload(result)
            assert data["session_count"] == 0  # admin's submission, user doesn't own it
            assert data["digests"] == []
    finally:
        reset_caller_token_for_test(user_tok)


@pytest.mark.asyncio
async def test_list_interviewees_admin_only():
    _instance_id, admin_info, user_info = _make_instance_and_tokens()

    # Admin submits, then admin lists.
    admin_tok = set_caller_token_for_test(admin_info)
    try:
        transcript = (FIXTURE_DIR / "prod_internal.txt").read_text()
        async with create_connected_server_and_client_session(build_mcp_server()) as client:
            await client.initialize()
            await client.call_tool("submit_interview", {
                "transcript": transcript,
                "interviewee_slug": "leo",
            })
            result = await client.call_tool("list_interviewees", {})
            data = _payload(result)
            slugs = [row["interviewee_slug"] for row in data["interviewees"]]
            assert "leo" in slugs
    finally:
        reset_caller_token_for_test(admin_tok)

    # User-role token cannot list.
    user_tok = set_caller_token_for_test(user_info)
    try:
        async with create_connected_server_and_client_session(build_mcp_server()) as client:
            await client.initialize()
            result = await client.call_tool("list_interviewees", {})
            data = _payload(result)
            assert data.get("error") and "admin" in data["error"].lower()
    finally:
        reset_caller_token_for_test(user_tok)


@pytest.mark.asyncio
async def test_run_cohort_matching_admin_returns_graph():
    instance_id, admin_info, _ = _make_instance_and_tokens()
    token = set_caller_token_for_test(admin_info)
    try:
        transcript = (FIXTURE_DIR / "prod_internal.txt").read_text()
        async with create_connected_server_and_client_session(build_mcp_server()) as client:
            await client.initialize()
            await client.call_tool("submit_interview", {
                "transcript": transcript, "interviewee_slug": "leo",
            })
            result = await client.call_tool("run_cohort_matching", {})
            data = _payload(result)
            assert "matching" in data
            assert "intros" in data["matching"] and "graph" in data["matching"]
    finally:
        reset_caller_token_for_test(token)


@pytest.mark.asyncio
async def test_run_cohort_matching_user_denied():
    _instance_id, _admin, user_info = _make_instance_and_tokens()
    token = set_caller_token_for_test(user_info)
    try:
        async with create_connected_server_and_client_session(build_mcp_server()) as client:
            await client.initialize()
            result = await client.call_tool("run_cohort_matching", {})
            data = _payload(result)
            assert data.get("error") and "admin" in data["error"].lower()
    finally:
        reset_caller_token_for_test(token)


@pytest.mark.asyncio
async def test_get_team_context_returns_v0_stub():
    _instance_id, admin_info, _ = _make_instance_and_tokens()
    token = set_caller_token_for_test(admin_info)
    try:
        async with create_connected_server_and_client_session(build_mcp_server()) as client:
            await client.initialize()
            result = await client.call_tool("get_team_context", {"team_slug": "shape-rotator"})
            data = _payload(result)
            assert data["team_slug"] == "shape-rotator"
            assert data["frontmatter"] is None
            assert "stubbed" in (data.get("note") or "").lower()
    finally:
        reset_caller_token_for_test(token)


@pytest.mark.asyncio
async def test_tool_without_token_returns_permission_error():
    """Calling a tool without setting up auth context should raise (which
    FastMCP surfaces as an error in the tool result)."""
    # Do NOT set the contextvar.
    async with create_connected_server_and_client_session(
        build_mcp_server(), raise_exceptions=False
    ) as client:
        await client.initialize()
        result = await client.call_tool("whoami", {})
        # The tool implementation raises PermissionError; FastMCP turns it
        # into an error response.
        assert result.isError or _payload_safe(result) is None or "no authenticated token" in (
            _text(result).lower()
        )


def _payload_safe(result) -> dict | None:
    try:
        return _payload(result)
    except Exception:
        return None


@pytest.mark.asyncio
async def test_server_instructions_populated():
    """The server-instructions field is what teaches consuming agents about the
    tool surface. It must not be empty."""
    server = build_mcp_server()
    # Pull the instructions string back out of the FastMCP instance
    instructions = server.instructions or ""
    assert "interview_reflection" in instructions
    assert "submit_interview" in instructions
    assert "verify_attestation" in instructions
