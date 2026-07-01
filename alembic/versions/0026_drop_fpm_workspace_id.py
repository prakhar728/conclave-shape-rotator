"""Drop the dead ``workspaces.fpm_workspace_id`` column (Task #2).

Added in 0015 to map a Conclave workspace → its FPM/VFTE identity scope, but nothing
ever read it: the live mapping is ``settings.fpm_workspace_for(workspace_id)`` (env
``CONCLAVE_FPM_WORKSPACE`` or the workspace_id verbatim). The permission-scoping work
(#2) makes the VFTE scope model explicit, so this vestigial column is removed to avoid a
second, divergent source of truth for the workspace→scope mapping.

Reversible: ``downgrade`` re-adds the nullable column (values are not restored — there
were none in use).

Revision ID: 0026_drop_fpm_workspace_id
Revises: 0025_user_tnc
Create Date: 2026-07-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_drop_fpm_workspace_id"
down_revision = "0025_user_tnc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        batch.drop_column("fpm_workspace_id")


def downgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        batch.add_column(sa.Column("fpm_workspace_id", sa.Text, nullable=True))
