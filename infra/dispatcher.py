"""Capture dispatcher — Conclave owns meeting concurrency (P1, caps-only).

When Conclave invites a bot it now drives the stateless `capture` microservice
directly, so concurrency control lives HERE (it used to be Recato's per-token
`max_concurrent_bots`). Two caps, both counting *active* invitations
(`requested | joining | active`):

  - per-workspace: `workspaces.max_active_meetings` (Alembic 0015, default 2)
  - global:        `CONCLAVE_GLOBAL_MAX_MEETINGS` env (protects the shared capture CVM)

`check_and_assign()` is called before launch; on breach it raises `CapacityError`
(the route maps it to HTTP 429). On success it returns the warmed account id to
drive the bot with — for now a single shared account (`CONCLAVE_CAPTURE_ACCOUNT_ID`);
a real per-workspace pool is deferred to P6.

Raw sqlite3 via `storage.sqlite._get_conn` for parity with `infra/bot_invitations.py`.
"""
from __future__ import annotations

import os

from storage.sqlite import _get_conn

# Invitation statuses that count as "occupying" a capture slot.
_ACTIVE_STATUSES = ("requested", "joining", "active")

# Single shared warmed account until the P6 pool exists.
SHARED_ACCOUNT_ID = os.environ.get("CONCLAVE_CAPTURE_ACCOUNT_ID", "shared")


def _global_cap() -> int:
    try:
        return int(os.environ.get("CONCLAVE_GLOBAL_MAX_MEETINGS", "16"))
    except ValueError:
        return 16


class CapacityError(Exception):
    """Raised when a concurrency cap is hit. `scope` is 'workspace' or 'global'."""

    def __init__(self, scope: str, limit: int, active: int):
        self.scope = scope
        self.limit = limit
        self.active = active
        super().__init__(
            f"{scope} concurrency cap reached ({active}/{limit} active meetings)"
        )


def _active_count(where_sql: str, params: tuple) -> int:
    placeholders = ",".join("?" for _ in _ACTIVE_STATUSES)
    row = _get_conn().execute(
        f"SELECT COUNT(*) AS n FROM bot_invitations "
        f"WHERE status IN ({placeholders}) AND {where_sql}",
        (*_ACTIVE_STATUSES, *params),
    ).fetchone()
    return int(row["n"]) if row else 0


def _workspace_cap(workspace_id: str) -> int:
    row = _get_conn().execute(
        "SELECT max_active_meetings FROM workspaces WHERE id = ?",
        (workspace_id,),
    ).fetchone()
    # Default mirrors the migration's server_default.
    return int(row["max_active_meetings"]) if row and row["max_active_meetings"] is not None else 2


def check_and_assign(workspace_id: str) -> str:
    """Enforce per-workspace + global caps; return the account id to launch with.

    Raises CapacityError on breach. Call this BEFORE launching the bot. Note: the
    not-yet-created invitation isn't counted, so the effective cap is inclusive
    (e.g. max_active_meetings=2 allows a 3rd check only once one finishes).
    """
    ws_cap = _workspace_cap(workspace_id)
    ws_active = _active_count("workspace_id = ?", (workspace_id,))
    if ws_active >= ws_cap:
        raise CapacityError("workspace", ws_cap, ws_active)

    g_cap = _global_cap()
    g_active = _active_count("1 = 1", ())
    if g_active >= g_cap:
        raise CapacityError("global", g_cap, g_active)

    return SHARED_ACCOUNT_ID
