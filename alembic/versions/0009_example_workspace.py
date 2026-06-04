"""Seed demo sessions from the 3 ground-truth transcripts (3.5e C35).

Extends the 0005 example-session pattern (NULL workspace, visibility
'shared', allowlisted to any authenticated user) to the three Phase
3.5.0 eval transcripts, so a fresh signup sees a populated dashboard,
entities, obligations, search results, and graph.

Raw transcript content is read from ``tests/fixtures/transcripts/``
at migration time — those files are deliberately NOT in git (privacy
carve, C1). On machines without them the migration no-ops per missing
file with a warning; demo seeding is a deploy-time concern and the
deploying machine has the content.

KB artifacts (chunks/embeddings/extraction) are NOT built here —
migrations must not call Ollama/LLMs. Run ``scripts/seed_demo.py``
after migrating.

Revision ID: 0009_example_workspace
Revises: 0008_ingest_metrics
Create Date: 2026-06-04
"""
from __future__ import annotations

import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0009_example_workspace"
down_revision = "0008_ingest_metrics"
branch_labels = None
depends_on = None

REPO = Path(__file__).resolve().parent.parent.parent
FIXTURE_DIR = REPO / "tests" / "fixtures" / "transcripts"

#: demo session id → fixture transcript filename
DEMO_SESSIONS = {
    "demo-elocute": "Elocute Transcript May 26.txt",
    "demo-dstack-intro-salon": "Dstack Intro Salon Session Transcript_May_20.txt",
    "demo-project-intros-agents-day3": "Project Intros Agents Day 3 Transcript_May_21.txt",
}

_DATES = {
    "demo-elocute": "2026-05-26",
    "demo-dstack-intro-salon": "2026-05-20",
    "demo-project-intros-agents-day3": "2026-05-21",
}


def upgrade() -> None:
    import sys
    sys.path.insert(0, str(REPO))
    from transcripts.sources import read_file

    conn = op.get_bind()
    for sid, filename in DEMO_SESSIONS.items():
        existing = conn.execute(
            sa.text("SELECT 1 FROM transcript_sessions WHERE session_id = :sid"),
            {"sid": sid},
        ).fetchone()
        if existing:
            continue
        path = FIXTURE_DIR / filename
        if not path.exists():
            print(f"[0009] fixture {filename!r} not present — skipping {sid}")
            continue
        ni = read_file(path)
        raw = [
            {"speaker": s["speaker"], "text": s["text"],
             "start": s["start"], "end": s["end"]}
            for s in ni.segments
        ]
        metadata = {
            "date": _DATES[sid],
            "source": "demo",
            "resolved_speakers": {},
            "tags": ["demo"],
            "visibility": "shared",
            "owner": None,
            "participants": ni.provenance.get("members") or [],
        }
        conn.execute(
            sa.text(
                "INSERT INTO transcript_sessions "
                "(session_id, source, session_date, raw_diarization, metadata, "
                " derived, created_at, updated_at, workspace_id, owner_user_id, "
                " visibility) "
                "VALUES (:sid, 'demo', :date, :raw, :meta, :derived, :now, :now, "
                "        NULL, NULL, 'shared')"
            ),
            {
                "sid": sid,
                "date": _DATES[sid],
                "raw": json.dumps(raw),
                "meta": json.dumps(metadata),
                "derived": json.dumps({}),
                "now": "2026-06-04T00:00:00Z",
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    for sid in DEMO_SESSIONS:
        # KB artifacts for the demo sessions ride along.
        for table, col in (
            ("entity_mentions", "session_id"),
            ("obligations", "session_id"),
            ("chunks", "session_id"),
            ("ingest_metrics", "session_id"),
        ):
            try:
                conn.execute(
                    sa.text(f"DELETE FROM {table} WHERE {col} = :sid"),
                    {"sid": sid},
                )
            except Exception:  # noqa: BLE001 — table may not exist mid-downgrade
                pass
        conn.execute(
            sa.text("DELETE FROM transcript_sessions WHERE session_id = :sid"),
            {"sid": sid},
        )
