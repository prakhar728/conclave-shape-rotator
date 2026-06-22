"""Live-segment buffer for streaming capture ingest (P1).

The capture microservice publishes transcript segments to a Redis stream as the
meeting happens; Conclave's consumer accumulates them HERE, durably in its own
DB (TEE), keyed by the meeting. This buffer exists because `transcript_sessions.
raw_diarization` is **write-once / immutable** (storage/sqlite.py) — we can't
append into it live. At `meeting.completed` the finalize path aggregates this
buffer into the session's `raw_diarization` exactly once, preserving that
invariant. Live identity/display (P4) reads the buffer while the meeting runs.

`native_meeting_id` is the join key (matches `bot_invitations.native_meeting_id`).
`seq` orders segments within a meeting; `segment_id` (from the capture stream's
`segment-publisher.ts`) dedupes replays after a consumer reconnect.

Revision ID: 0016_live_segments
Revises: 0015_capture_state
Create Date: 2026-06-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_live_segments"
down_revision = "0015_capture_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "live_segments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("native_meeting_id", sa.Text, nullable=False),
        sa.Column("segment_id", sa.Text, nullable=True),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("segment", sa.Text, nullable=False),   # JSON: {speaker,text,start,end,...}
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index(
        "idx_live_segments_meeting", "live_segments", ["native_meeting_id", "seq"]
    )
    # Dedupe replays: same (meeting, segment_id) only once when segment_id is present.
    op.create_index(
        "idx_live_segments_dedupe",
        "live_segments",
        ["native_meeting_id", "segment_id"],
        unique=True,
        sqlite_where=sa.text("segment_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_live_segments_dedupe", table_name="live_segments")
    op.drop_index("idx_live_segments_meeting", table_name="live_segments")
    op.drop_table("live_segments")
