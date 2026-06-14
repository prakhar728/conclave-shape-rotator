#!/usr/bin/env python3
"""Seed a user + workspace + two meetings (sharing one voiceprint) for the P4 gate demo.

Writes directly to the Conclave DB (CONCLAVE_DB_PATH) — no running server needed. Ensures
the schema exists (legacy storage.sqlite tables + alembic-owned tables), mints a session
token, and creates two owner-only sessions whose `resolved_speakers` carry the demo
voiceprint_id (under different labels, on purpose, to prove cross-label re-resolve). The
two meetings share the voiceprint, so confirming once must flip the name in BOTH.

Writes a `gate_env.sh` with the values the gate command consumes. Re-runs are idempotent
(prior demo sessions are deleted first).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root on path


def _prep_schema() -> None:
    """Legacy schema first (alembic 0004 ALTERs transcript_sessions), then alembic head."""
    from storage import sqlite as _sqlite

    _sqlite._get_conn()
    from alembic import command
    from alembic.config import Config

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(repo, "alembic.ini"))
    os.environ["CONCLAVE_DB_URL"] = f"sqlite:///{_sqlite._DB_PATH}"
    command.upgrade(cfg, "head")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", default="you@example.com")
    ap.add_argument("--name", default="Demo User")
    ap.add_argument("--voiceprint-id", default="vp_p4demo")
    ap.add_argument("--label", default="Speaker 2")
    ap.add_argument("--env-out", default=None)
    a = ap.parse_args()

    _prep_schema()

    from auth import session as auth_session
    from config import settings
    from infra import identity, workspaces
    from storage import sqlite as _sqlite
    from transcripts import store
    from transcripts.models import Derived, RawSegment, Session, SessionMetadata, Signal

    user = identity.upsert_user_by_supabase(f"sb-{a.email}", a.email)
    ws = workspaces.ensure_personal_workspace(user["id"])
    token = auth_session.issue_session(user["id"])
    fpm_ws = settings.fpm_workspace_for(ws["id"])

    # m1+m2 share the primary voiceprint (deliberately different labels → cross-label re-resolve);
    # m3 carries a second voiceprint, used by the Phase-2 deny arm.
    vid2 = a.voiceprint_id + "2"
    meetings = {
        "p4demo-m1": (a.label, a.voiceprint_id),
        "p4demo-m2": ("Speaker 1", a.voiceprint_id),
        "p4demo-m3": ("Speaker 1", vid2),
    }
    for sid, (lbl, vid) in meetings.items():
        _sqlite.delete_transcript_session(sid)  # clean slate for re-runs
        sess = Session(
            session_id=sid,
            raw_diarization=[RawSegment(speaker=lbl, text=f"{lbl}: hello from {sid}", start=0.0)],
            metadata=SessionMetadata(
                date="2026-06-14", source="record",
                resolved_speakers={lbl: {"voiceprint_id": vid, "name": None, "confidence": 0.9}},
            ),
            derived=Derived(summary="demo",
                            signals=[Signal(kind="action_item", text="t", said_by=[lbl])]),
        )
        store.save_session(sess)
        store.set_workspace(sid, workspace_id=ws["id"], owner_user_id=user["id"],
                            visibility="owner-only")

    env_out = a.env_out or os.path.join(os.path.dirname(_sqlite._DB_PATH) or ".", "gate_env.sh")
    with open(env_out, "w") as f:
        f.write(f"export CONCLAVE_TOKEN={token}\n")
        f.write(f"export GATE_WORKSPACE={ws['id']}\n")
        f.write(f"export GATE_FPM_WORKSPACE={fpm_ws}\n")
        f.write("export GATE_SESSION=p4demo-m1\n")
        f.write("export GATE_SECOND_SESSION=p4demo-m2\n")
        f.write("export GATE_DENY_SESSION=p4demo-m3\n")
        f.write(f"export GATE_LABEL={a.label!r}\n")
        f.write("export GATE_DENY_LABEL='Speaker 1'\n")
        f.write(f"export GATE_EMAIL={a.email}\n")
        f.write(f"export GATE_NAME={a.name!r}\n")
    print(f"[conclave-seed] user={a.email} ws={ws['id']} fpm_ws={fpm_ws} "
          f"sessions=p4demo-m1,p4demo-m2")
    print(f"[conclave-seed] env written to {env_out}")


if __name__ == "__main__":
    main()
