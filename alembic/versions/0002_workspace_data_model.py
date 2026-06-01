"""Workspace data model — users, workspaces, members, invitations, magic links, shares.

First real Alembic-owned schema (post-baseline). All six tables are fresh —
no data migration; existing 13 historical sessions stay with `workspace_id`
NULL (the `transcript_sessions.workspace_id` column itself lands in 1.6).

Tables created here:
- users               : internal user rows, 1:1 with Supabase users
- workspaces          : top-level meeting container ("Personal", etc.)
- workspace_members   : N:N user↔workspace with roles (v1 uses only 'owner')
- bot_invitations     : tracks Recato bot launches (populated from Phase 2)
- magic_links         : single-use sign-in tokens emailed to attendees (Phase 2)
- meeting_shares      : per-meeting access grants for 'shared' visibility (Phase 2)

Schema rationale lives in BUILD_DOC §9.

Revision ID: 0002_workspace_data_model
Revises: 0001_baseline
Create Date: 2026-06-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_workspace_data_model"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("supabase_id", sa.Text, nullable=False, unique=True),
        sa.Column("email", sa.Text, nullable=False, unique=True),
        sa.Column("display_name", sa.Text, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "workspaces",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("created_by", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
    )
    op.create_index("ix_workspaces_created_by", "workspaces", ["created_by"])

    op.create_table(
        "workspace_members",
        sa.Column("workspace_id", sa.Text, sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "role",
            sa.Text,
            nullable=False,
            # v1 uses only 'owner'; 'member'/'viewer' reserved for v1.5 multi-member.
        ),
        sa.Column("added_at", sa.Text, nullable=False),
        sa.Column("added_by", sa.Text, sa.ForeignKey("users.id"), nullable=True),
        sa.PrimaryKeyConstraint("workspace_id", "user_id"),
        sa.CheckConstraint(
            "role IN ('owner','member','viewer')",
            name="ck_workspace_members_role",
        ),
    )
    op.create_index("ix_workspace_members_user_id", "workspace_members", ["user_id"])

    op.create_table(
        "bot_invitations",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "workspace_id", sa.Text, sa.ForeignKey("workspaces.id"), nullable=False
        ),
        sa.Column("platform", sa.Text, nullable=False),
        sa.Column("native_meeting_id", sa.Text, nullable=False),
        sa.Column("recato_bot_id", sa.Integer, nullable=True),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("bot_name", sa.Text, nullable=False, server_default="Conclave"),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("completed_at", sa.Text, nullable=True),
        sa.CheckConstraint(
            "status IN ('requested','joining','active','completed','failed')",
            name="ck_bot_invitations_status",
        ),
    )
    op.create_index(
        "ix_bot_invitations_workspace_id", "bot_invitations", ["workspace_id"]
    )
    op.create_index("ix_bot_invitations_user_id", "bot_invitations", ["user_id"])

    op.create_table(
        "magic_links",
        sa.Column("token", sa.Text, primary_key=True),
        sa.Column("user_email", sa.Text, nullable=False),
        sa.Column("meeting_session_id", sa.Text, nullable=True),
        sa.Column("expires_at", sa.Text, nullable=False),
        sa.Column("consumed_at", sa.Text, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
        # NOTE: meeting_session_id FK to transcript_sessions(session_id) is NOT
        # declared here. transcript_sessions is owned by storage.sqlite._init_schema
        # (legacy domain); cross-domain FKs are intentionally avoided to keep
        # Alembic's view of the schema self-contained. Integrity is enforced at
        # the application layer.
    )
    op.create_index("ix_magic_links_user_email", "magic_links", ["user_email"])

    op.create_table(
        "meeting_shares",
        sa.Column("session_id", sa.Text, nullable=False),
        sa.Column("user_email", sa.Text, nullable=False),
        sa.Column("granted_by", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("granted_at", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=True),
        sa.PrimaryKeyConstraint("session_id", "user_email"),
        # session_id FK to transcript_sessions skipped — see magic_links note above.
    )
    op.create_index("ix_meeting_shares_user_email", "meeting_shares", ["user_email"])


def downgrade() -> None:
    op.drop_index("ix_meeting_shares_user_email", table_name="meeting_shares")
    op.drop_table("meeting_shares")
    op.drop_index("ix_magic_links_user_email", table_name="magic_links")
    op.drop_table("magic_links")
    op.drop_index("ix_bot_invitations_user_id", table_name="bot_invitations")
    op.drop_index("ix_bot_invitations_workspace_id", table_name="bot_invitations")
    op.drop_table("bot_invitations")
    op.drop_index("ix_workspace_members_user_id", table_name="workspace_members")
    op.drop_table("workspace_members")
    op.drop_index("ix_workspaces_created_by", table_name="workspaces")
    op.drop_table("workspaces")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
