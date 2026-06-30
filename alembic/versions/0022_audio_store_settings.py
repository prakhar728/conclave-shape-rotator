"""Audio store/no-store settings (Task #30).

Two new nullable columns backing the per-meeting + per-workspace store-audio toggle:
- `workspaces.audio_store_default` — workspace-level default the gMeet invite path
  falls back to (NULL / missing ⇒ True, keep, in infra.workspaces.get_audio_store_default).
- `bot_invitations.store_audio` — the per-meeting gMeet decision resolved against that
  default at invite time (NULL ⇒ the audio write defaults to keep — back-compat).

In-person's per-meeting decision rides the WS connect param → session metadata JSON, so
it needs no column here. No data is back-filled and existing audio is untouched (the
encrypt-new-meetings-only invariant).

Revision ID: 0022_audio_store_settings
Revises: 0021_feedback
Create Date: 2026-06-30

Re-chained onto 0021_feedback (#19, merged first) — #30 and #19 were both authored as
0021 off 0020; per the locked merge order #19 lands first, so this becomes 0022 with
down_revision = 0021_feedback to keep a single alembic head.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_audio_store_settings"
down_revision = "0021_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        batch.add_column(sa.Column("audio_store_default", sa.Integer, nullable=True))
    with op.batch_alter_table("bot_invitations") as batch:
        batch.add_column(sa.Column("store_audio", sa.Integer, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("bot_invitations") as batch:
        batch.drop_column("store_audio")
    with op.batch_alter_table("workspaces") as batch:
        batch.drop_column("audio_store_default")
