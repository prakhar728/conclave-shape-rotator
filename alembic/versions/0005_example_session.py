"""Seed the canonical example transcript_session for new-user empty state.

One row in `transcript_sessions`, session_id = 'example-conclave-demo',
workspace_id NULL, owner_user_id NULL, visibility 'shared'. Visible to
any authenticated user via the allowlist in `api/transcripts_routes.py`
(see `_EXAMPLE_SESSION_ID`). Bypasses the full meeting_shares mechanism
because it's the same row for every user; per-user shares would be
fan-out writes for zero gain in v1.

Phase 2.x ingest never writes to this row (idempotency dedup is by
session_id; the seed lives forever unless this migration is rolled back).

Revision ID: 0005_example_session
Revises: 0004_transcript_sessions_workspace_columns
Create Date: 2026-06-01
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0005_example_session"
down_revision = "0004_transcript_sessions_workspace_columns"
branch_labels = None
depends_on = None


_EXAMPLE_SESSION_ID = "example-conclave-demo"

_METADATA = {
    "date": "2026-05-15",
    "source": "example",
    "resolved_speakers": {},
    "tags": ["example"],
    "pipeline_version": "v2.2",
    "visibility": "shared",
    "owner": None,
    "model_id": "example",
    "enrich_prompt_version": "v2.2",
    "chunk_count": 1,
    "team_context_version": "v1",
    "participants": ["Alice", "Bob"],
}

_DERIVED = {
    "summary": (
        "Walkthrough of how a Conclave meeting card looks once your bot has "
        "joined a Meet. Action items, open questions, and insights below are "
        "from a fictional product review."
    ),
    "topics": ["product review", "onboarding"],
    "signals": [
        {
            "kind": "action_item",
            "text": "Send Conclave the production Meet URL for next week's review.",
            "said_by": ["Alice"],
            "about_person": [],
            "source_quote": "Let's get the bot into the Wed review.",
        },
        {
            "kind": "action_item",
            "text": "Decide visibility default — keep owner-only or open to workspace.",
            "said_by": ["Bob"],
            "about_person": [],
            "source_quote": "Owner-only feels safe but we'll lose the shared context.",
        },
        {
            "kind": "open_question",
            "text": "When the bot is in TEE, do we still need per-user attestation?",
            "said_by": ["Alice"],
            "about_person": [],
            "source_quote": None,
        },
        {
            "kind": "insight",
            "text": "Action items grouped by speaker make the readout 3x faster.",
            "said_by": ["Bob"],
            "about_person": [],
            "source_quote": None,
        },
    ],
    "entities": [
        {"name": "Conclave bot", "type": "system", "evidence": "central topic"},
        {"name": "TEE", "type": "concept", "evidence": "raised in open question"},
    ],
    "graph_nodes": [],
}


def upgrade() -> None:
    conn = op.get_bind()
    # Skip if already present (idempotent across re-runs on the same DB).
    existing = conn.execute(
        sa.text("SELECT 1 FROM transcript_sessions WHERE session_id = :sid"),
        {"sid": _EXAMPLE_SESSION_ID},
    ).fetchone()
    if existing:
        return

    conn.execute(
        sa.text(
            "INSERT INTO transcript_sessions "
            "(session_id, source, session_date, raw_diarization, metadata, "
            " derived, created_at, updated_at, workspace_id, owner_user_id, "
            " visibility) "
            "VALUES (:sid, :source, :date, :raw, :meta, :derived, :now, :now, "
            "        NULL, NULL, 'shared')"
        ),
        {
            "sid": _EXAMPLE_SESSION_ID,
            "source": "example",
            "date": _METADATA["date"],
            "raw": json.dumps([]),  # no raw transcript for the demo
            "meta": json.dumps(_METADATA),
            "derived": json.dumps(_DERIVED),
            "now": "2026-06-01T00:00:00Z",
        },
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM transcript_sessions WHERE session_id = :sid"),
        {"sid": _EXAMPLE_SESSION_ID},
    )
