"""Google Calendar integration tables.

Three tables backing the dedicated-OAuth calendar feature:

- google_oauth_tokens: one row per user holding their *encrypted* Google
  access + refresh tokens (Fernet via CONCLAVE_TOKEN_ENC_KEY — never
  plaintext). Keyed by our internal user id so a user disconnecting just
  deletes their row.
- calendar_auto_record: per-event opt-in for the auto-dispatch poller. A
  row with enabled=1 means "send the bot to this Google Meet when it's
  about to start". meet_code lets the poller dedup against bot_invitations
  without re-fetching the event.
- meeting_calendar_links: maps a recorded meeting (meet_code / session_id)
  back to the calendar event it came from, so a transcript carries the
  event's title, organizer, attendees and scheduled time. Populated by the
  Recato meeting.completed webhook.

FKs to `users` use ON DELETE CASCADE — these rows are meaningless once the
user is gone, matching the cascade discipline established in 0010.

Revision ID: 0011_google_calendar
Revises: 0010_kb_fk_cascade
Create Date: 2026-06-08
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_google_calendar"
down_revision = "0010_kb_fk_cascade"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    x = conn.execute

    x(sa.text(
        """
        CREATE TABLE IF NOT EXISTS google_oauth_tokens (
            user_id TEXT PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
            access_token_enc TEXT,
            refresh_token_enc TEXT,
            expiry TEXT,
            scopes TEXT NOT NULL DEFAULT '',
            connected_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    ))

    x(sa.text(
        """
        CREATE TABLE IF NOT EXISTS calendar_auto_record (
            user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            google_event_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            meet_code TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, google_event_id)
        )
        """
    ))
    x(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_auto_record_meet "
        "ON calendar_auto_record (meet_code)"
    ))
    x(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_auto_record_enabled "
        "ON calendar_auto_record (enabled)"
    ))

    x(sa.text(
        """
        CREATE TABLE IF NOT EXISTS meeting_calendar_links (
            meet_code TEXT PRIMARY KEY,
            session_id TEXT,
            google_event_id TEXT,
            title TEXT,
            organizer_email TEXT,
            attendees_json TEXT NOT NULL DEFAULT '[]',
            start_at TEXT,
            end_at TEXT,
            linked_at TEXT NOT NULL
        )
        """
    ))
    x(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_calendar_links_session "
        "ON meeting_calendar_links (session_id)"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    x = conn.execute
    x(sa.text("DROP TABLE IF EXISTS meeting_calendar_links"))
    x(sa.text("DROP TABLE IF EXISTS calendar_auto_record"))
    x(sa.text("DROP TABLE IF EXISTS google_oauth_tokens"))
