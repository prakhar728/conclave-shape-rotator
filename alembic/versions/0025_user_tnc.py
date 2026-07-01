"""Record Terms & Conditions acceptance on the user (Task #18).

The early-access product ships a BLOCKING first-login T&C gate: a user must
accept the placeholder terms (version ``tnc-v0``) before using the app. We
record the acceptance so the gate stays satisfied on later logins and can be
re-triggered when the terms version bumps.

Two nullable columns on ``users``:

- ``tnc_accepted_at`` — ISO timestamp of the acceptance (NULL = never accepted).
- ``tnc_version``     — the terms version accepted (e.g. ``tnc-v0``). When this
                        differs from the current version the gate re-fires.

Both nullable so every existing row back-fills to "not yet accepted" — those
users see the gate on their next visit, which is the intended behavior.

Revision ID: 0025_user_tnc
Revises: 0024_meeting_share_artifact_flags
Create Date: 2026-06-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_user_tnc"
down_revision = "0024_meeting_share_artifact_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("tnc_accepted_at", sa.Text, nullable=True))
        batch.add_column(sa.Column("tnc_version", sa.Text, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("tnc_version")
        batch.drop_column("tnc_accepted_at")
