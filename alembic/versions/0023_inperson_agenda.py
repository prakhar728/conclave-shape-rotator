"""In-person agenda stash (Task #12).

A tiny key-value stash that carries the agenda/intent typed in the record modal
from record-start to the finalize webhook. The in-person live path streams the
mic straight to the capture microservice — capture is untouched — so the agenda
can't ride the WS. Instead the modal POSTs it to Conclave keyed by the meeting
`uid`; the `meeting.completed` webhook (which fires on Stop, possibly minutes
later) reads it back and sets `session.metadata.raw_intent` before enrichment is
enqueued. A table (not in-memory) so it survives a worker restart between
record-start and finalize, and so multiple workers share it.

`uid` is the in-person meeting id minted client-side (`inperson-<ts>-<rand>`),
which becomes `native_meeting_id` in the webhook — the join key. `workspace_id`
is stored for provenance/auth-at-write only (no FK, so conftest's workspace
teardown never trips on it, and a transient stash row never blocks a delete).

Revision ID: 0023_inperson_agenda
Revises: 0022_audio_store_settings
Create Date: 2026-06-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_inperson_agenda"
down_revision = "0022_audio_store_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inperson_agenda",
        sa.Column("uid", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, nullable=True),
        sa.Column("agenda", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("inperson_agenda")
