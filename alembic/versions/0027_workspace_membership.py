"""Workspace multi-membership (Task #32).

Adds the plumbing for real multi-member Conclave workspaces:

- ``workspace_invites`` — an owner invites an email; the recipient accepts (via
  the emailed link, or auto-accepted on first sign-in) → a ``workspace_members``
  row. Mirrors the ``meeting_shares`` "grant-by-email, hydrate user_id on signup"
  precedent. ``workspace_members`` itself already exists (Alembic 0002).
- ``meeting_workspace_shares`` — the "share this meeting with the WHOLE workspace"
  grant (covers current + future members, one row per meeting). Composes with the
  per-recipient ``meeting_shares`` (an email / a specific member) rather than
  overloading the ``visibility`` enum, so a whole-workspace share and an
  outside-email share can coexist on one meeting.
- ``transcript_sessions.recorder_user_id`` — the member who actually recorded a
  meeting (the finalize webhook has no request user). Passed to VFTE as the
  ``host_user`` on identify so #2's per-adder overlay resolves under the recorder,
  not the workspace owner (the #2 stopgap this replaces).
- ``transcript_sessions.owner_only`` — the confidential escape hatch (§0.4 /
  §0b-D): when set, the meeting can't be shared to the workspace/members even by
  the owner. NULL/0 = normal (still owner-private by default, but shareable).
- ``inperson_recorder`` — a tiny record-start stash keyed by the meeting ``uid``
  (capture is untouched, so the recorder identity can't ride the WS). The
  finalize webhook pops it and writes ``recorder_user_id`` onto the session.

Revision ID: 0027_workspace_membership
Revises: 0026_drop_fpm_workspace_id
Create Date: 2026-07-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_workspace_membership"
down_revision = "0026_drop_fpm_workspace_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_invites",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False, server_default="member"),
        sa.Column("token", sa.Text, nullable=False, unique=True),
        sa.Column("invited_by", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("accepted_at", sa.Text, nullable=True),
        sa.Column("accepted_user_id", sa.Text, nullable=True),
    )
    op.create_index("ix_workspace_invites_ws", "workspace_invites", ["workspace_id"])
    op.create_index("ix_workspace_invites_email", "workspace_invites", ["email"])

    op.create_table(
        "meeting_workspace_shares",
        sa.Column("session_id", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("granted_by", sa.Text, nullable=False),
        sa.Column("granted_at", sa.Text, nullable=False),
    )

    op.create_table(
        "inperson_recorder",
        sa.Column("uid", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, nullable=True),
        sa.Column("recorder_user_id", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )

    with op.batch_alter_table("transcript_sessions") as batch:
        batch.add_column(sa.Column("recorder_user_id", sa.Text, nullable=True))
        batch.add_column(sa.Column("owner_only", sa.Integer, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("transcript_sessions") as batch:
        batch.drop_column("owner_only")
        batch.drop_column("recorder_user_id")
    op.drop_table("inperson_recorder")
    op.drop_table("meeting_workspace_shares")
    op.drop_index("ix_workspace_invites_email", table_name="workspace_invites")
    op.drop_index("ix_workspace_invites_ws", table_name="workspace_invites")
    op.drop_table("workspace_invites")
