"""
MCP plugin surface for interview_reflection (Track A v0, Step 9).

Exposes the skill's tools over the Model Context Protocol so any MCP-capable
agent (Claude Code, Claude Desktop, Cursor) can submit transcripts, query
results, and inspect the deployed instance — no web frontend required.

Mounts under /mcp on the main FastAPI app (see main.py). Streamable HTTP
transport, the same transport Claude Code / Desktop speak in production.

Tools (Track A v0):
  - whoami                        — role + instance_id of the calling token
  - instance_info                 — skill version, attestation pointer, public name
  - verify_attestation(nonce)     — TDX quote bound to the supplied nonce
  - submit_interview(...)         — admin only; submit a transcript for digestion
  - get_interview_results(...)    — admin: any slug · user: own slug
  - list_interviewees()           — admin only; per-slug session counts
  - get_team_context(team_slug)   — Shape Rotator OS frontmatter (stubbed in v0)

Auth model:
  Tokens are resolved by a Starlette middleware on the mounted sub-app. It
  reads X-Instance-Token (or Authorization: Bearer <token>), looks the token
  up in `storage`, and stores the resolved info on a contextvar. Each tool
  reads the contextvar to enforce role + instance scoping.

  In tests, the in-memory transport bypasses HTTP middleware entirely. Test
  code sets the contextvar directly via set_caller_token_for_test().

Signing:
  Tool responses include a `signed_payload` field set to None in v0. Step 12
  (deploy) wires the enclave signing key and populates it. The shape of the
  contract is fixed now so downstream agents can rely on it.
"""
from __future__ import annotations

import contextvars
import datetime as _dt
import json
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp


# --- Caller token context ---

_CALLER_TOKEN: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "interview_reflection_caller_token", default=None
)


def _current_caller() -> dict:
    info = _CALLER_TOKEN.get()
    if info is None:
        raise PermissionError(
            "no authenticated token on this MCP request — "
            "send X-Instance-Token or Authorization: Bearer <token>"
        )
    return info


def set_caller_token_for_test(info: Optional[dict]) -> contextvars.Token:
    """Test helper: set the caller-token context and return a reset token.

    Production code paths set this via the auth middleware. Tests using the
    in-memory MCP transport call this directly because there is no HTTP layer
    to run middleware on.
    """
    return _CALLER_TOKEN.set(info)


def reset_caller_token_for_test(reset_token: contextvars.Token) -> None:
    _CALLER_TOKEN.reset(reset_token)


# --- Auth middleware (HTTP transport) ---

class _TokenAuthMiddleware(BaseHTTPMiddleware):
    """Resolve X-Instance-Token / Bearer on the mounted MCP sub-app and stash
    the resolved info on a contextvar that tools read."""

    async def dispatch(self, request: Request, call_next):
        import storage
        token: Optional[str] = None
        auth = request.headers.get("Authorization") or request.headers.get("authorization")
        if auth and auth.startswith("Bearer "):
            token = auth[len("Bearer ") :].strip()
        if not token:
            token = request.headers.get("X-Instance-Token")

        info = storage.get_token(token) if token else None
        if info is None:
            # Allow MCP control-plane requests (initialize etc.) to proceed,
            # but tools that read _CALLER_TOKEN will raise. We don't 401 here
            # because the MCP protocol has its own handshake that we don't
            # want to break before the agent has even tried a tool.
            return await call_next(request)

        info["_raw_token"] = token
        ctx_token = _CALLER_TOKEN.set(info)
        try:
            return await call_next(request)
        finally:
            _CALLER_TOKEN.reset(ctx_token)


# --- FastMCP server ---

SERVER_INSTRUCTIONS = """\
This is a Conclave interview_reflection instance running inside a Phala TDX TEE.

It digests confidential 1:1 interview transcripts on behalf of an interviewer
(typically a cohort organizer like Novel) and returns:

  - themes:                   3-5 short noun phrases per interview
  - attribution_patterns:     internal vs external attribution proportions
  - suggested_next_questions: 2-4 follow-up questions for the interviewer
  - ownership_prompts:        gentle self-awareness prompts (interviewee-facing)
  - session_summary:          1-2 sentences anchored to the team's stated goals

Raw transcripts NEVER leave the enclave. Only the digests above do.

WHEN TO USE WHICH TOOL:

  Setting up / inspecting the instance
    - whoami                       — confirm role + instance_id of your token
    - instance_info                — see the skill version and attestation pointer
    - verify_attestation(nonce)    — get a fresh TDX quote bound to your nonce

  Submitting a new interview
    - submit_interview(transcript, interviewee_slug, notes?, share_with_interviewee=False)
      Admin only. share_with_interviewee=True emits an interviewee-facing
      payload (themes + ownership prompts) alongside the Novel-facing digest.

  Reading results
    - list_interviewees()                                  — admin only
    - get_interview_results(interviewee_slug, time_window?)
      Admin sees any slug. A user-role (per-interviewee) token sees only its
      own submissions.

  Grounding follow-up questions in cohort context
    - get_team_context(team_slug)
      Returns weekly_goals, success_dimensions, graduation_target from the
      Shape Rotator OS team frontmatter. v0 returns a stub; Step 8.1+ wires
      the real lookup.

GUARDRAILS YOU MUST NOT VIOLATE WHEN CONSUMING TOOL OUTPUTS:

  - Never claim a pattern across multiple interviewees without first calling
    list_interviewees() and inspecting per-slug counts.
  - Never paraphrase quotes that did not come back from a tool — the enclave
    redacts long verbatim transcript spans and strips unknown names. If you
    see [REDACTED LONG QUOTE] or [REDACTED NAME], do NOT try to reconstruct.
  - Cite the submission_id when reporting findings to the interviewer.
"""


def build_mcp_server() -> FastMCP:
    """Construct the FastMCP server with all Track A v0 tools registered."""
    mcp = FastMCP(
        name="conclave-interview-reflection",
        instructions=SERVER_INSTRUCTIONS,
        stateless_http=True,
    )
    _register_tools(mcp)
    return mcp


def build_mcp_app() -> ASGIApp:
    """Return the ASGI sub-app to mount under /mcp on the main FastAPI app."""
    mcp = build_mcp_server()
    app = mcp.streamable_http_app()
    app.add_middleware(_TokenAuthMiddleware)
    return app


def _register_tools(mcp: FastMCP) -> None:
    # Local imports keep storage / skill modules out of import-time cycles.
    import storage
    from skills.interview_reflection import run_skill
    from skills.interview_reflection.aggregate import load_digests
    from skills.interview_reflection.models import TranscriptInput

    @mcp.tool()
    def whoami() -> dict:
        """Return the role + instance_id of the calling token."""
        info = _current_caller()
        return _sign({
            "role": info.get("role"),
            "instance_id": info.get("instance_id"),
            "tool": "whoami",
        })

    @mcp.tool()
    def instance_info() -> dict:
        """Return metadata about this Conclave instance and the bound skill."""
        info = _current_caller()
        inst = storage.get_instance(info["instance_id"])
        if inst is None:
            return _sign({"error": "instance not found"})
        from skills.interview_reflection import skill_card
        return _sign({
            "instance_id": inst["instance_id"],
            "name": inst.get("name"),
            "skill": inst["skill_name"],
            "skill_version": skill_card.version,
            "attestation": "call verify_attestation(nonce) for a fresh TDX quote",
            "tool": "instance_info",
        })

    @mcp.tool()
    def verify_attestation(nonce: str = "") -> dict:
        """Return a TDX attestation quote bound to the supplied nonce."""
        from infra.enclave import get_attestation_quote
        try:
            quote = get_attestation_quote(nonce=nonce)
        except Exception as e:
            return _sign({"error": f"attestation unavailable: {e}", "nonce": nonce})
        return _sign({"nonce": nonce, "quote": quote, "tool": "verify_attestation"})

    @mcp.tool()
    def submit_interview(
        transcript: str,
        interviewee_slug: str,
        notes: Optional[str] = None,
        share_with_interviewee: bool = False,
    ) -> dict:
        """Submit one interview transcript for digestion. Admin only.

        Returns the post-guardrail Novel digest (themes, attribution patterns,
        suggested next questions, session summary). Raw transcript never leaves
        the enclave.
        """
        info = _current_caller()
        if info.get("role") != "admin":
            return _sign({"error": "admin role required to submit_interview"})

        sub = TranscriptInput(
            transcript=transcript,
            interviewee_slug=interviewee_slug,
            notes=notes,
            share_with_interviewee=share_with_interviewee,
        )
        # Persist the submission alongside the existing /submit path so
        # /trigger and /results stay consistent with MCP submissions.
        storage.upsert_submission(info["instance_id"], sub.submission_id, sub.model_dump())
        storage.add_submission_to_token(info["_raw_token"], sub.submission_id)

        response = run_skill([sub])
        return _sign({
            "submission_id": sub.submission_id,
            "result": response.results[0],
            "tool": "submit_interview",
        })

    @mcp.tool()
    def get_interview_results(
        interviewee_slug: str,
        time_window: Optional[str] = None,
    ) -> dict:
        """Return the ledger of past digests for an interviewee.

        Admin: any slug.  User: only own submissions (filtered by token-owned
        submission IDs). time_window is informational in v0 — no slicing yet.
        """
        info = _current_caller()
        digests = load_digests(interviewee_slug)

        if info.get("role") != "admin":
            owned = set(info.get("submission_ids") or [])
            digests = [d for d in digests if d.get("submission_id") in owned]

        return _sign({
            "interviewee_slug": interviewee_slug,
            "session_count": len(digests),
            "digests": digests,
            "time_window": time_window,
            "tool": "get_interview_results",
        })

    @mcp.tool()
    def list_interviewees() -> dict:
        """List every interviewee with at least one digest. Admin only."""
        info = _current_caller()
        if info.get("role") != "admin":
            return _sign({"error": "admin role required to list_interviewees"})

        from skills.interview_reflection.aggregate import DEFAULT_STORAGE_ROOT
        rows = []
        if DEFAULT_STORAGE_ROOT.exists():
            for path in sorted(DEFAULT_STORAGE_ROOT.glob("*.jsonl")):
                digests = load_digests(path.stem)
                if not digests:
                    continue
                last_ts = digests[-1].get("ingest_timestamp")
                rows.append({
                    "interviewee_slug": path.stem,
                    "session_count": len(digests),
                    "last_ingest": last_ts,
                })
        return _sign({"interviewees": rows, "tool": "list_interviewees"})

    @mcp.tool()
    def get_team_context(team_slug: str) -> dict:
        """Return Shape Rotator OS team frontmatter for grounding follow-ups.

        v0 returns a stub. Step 8.1 (or a separate Shape Rotator integration
        ticket) wires the real lookup.
        """
        return _sign({
            "team_slug": team_slug,
            "frontmatter": None,
            "note": "Shape Rotator OS team lookup is stubbed in v0",
            "tool": "get_team_context",
        })


def _sign(payload: dict) -> dict:
    """Wrap a tool response with provenance fields.

    `signed_payload` is None in v0. Step 12 (deploy) wires the enclave signing
    key and replaces None with a real signature over the canonical JSON of
    `payload`. Downstream agents can rely on the field's existence today.
    """
    return {
        **payload,
        "_emitted_at": _dt.datetime.now(_dt.UTC).isoformat(),
        "signed_payload": None,
    }
