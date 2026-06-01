"""Baseline anchor — legacy schema owned by storage.sqlite._init_schema.

This migration is intentionally a no-op. As of Phase 1.2 (2026-06-01) the
existing eight tables are still created by ``storage/sqlite.py::_init_schema``
on app boot; Alembic only takes ownership of NEW tables introduced from 1.3
onward (users, workspaces, workspace_members, bot_invitations, magic_links,
meeting_shares).

Tables created by ``_init_schema`` and therefore NOT touched here:
    - instances
    - submissions
    - results
    - tokens
    - registrations
    - evaluation_runs
    - attestations
    - transcript_sessions

For an existing DB (``data/conclave.db`` with 13 historical sessions): run
``alembic stamp 0001`` once to mark this revision applied without executing
it. ``scripts/db_stamp.sh`` automates this and backs up the DB first.

For a fresh DB: ``_init_schema`` runs at boot and creates the legacy tables;
``alembic upgrade head`` then applies 0001 (no-op) plus everything after it.

The two-domain split is documented in BUILD_DOC §4 and is a deliberate Phase 1
choice — consolidating everything under Alembic is deferred to v1.5 cleanup.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-01
"""
from __future__ import annotations

# revision identifiers, used by Alembic.
revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op: legacy tables are owned by storage.sqlite._init_schema."""
    pass


def downgrade() -> None:
    """No-op: legacy tables are owned by storage.sqlite._init_schema."""
    pass
