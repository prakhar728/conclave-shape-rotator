"""Inspect the full Part-1 persistence trail for one session.

Run from the repo root with the SAME env (DB path) as the running backend:

    python scripts/inspect_session.py <session_id>

After any front-end action this shows exactly what landed where — the v2 correction
layer (corrected tokens + tagged annotations), the per-user vocab, the graduation
stats, and the entity-graph counts. The annotations + vocab + approved v2 ARE the
surface Part 2 consumes (pinned by tests/test_part2_contract.py).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage import sqlite  # noqa: E402


def _doc(v2: dict) -> dict:
    raw = v2.get("doc_json")
    if isinstance(raw, str):
        return json.loads(raw)
    return raw or {}


def main(session_id: str) -> None:
    conn = sqlite._get_conn()

    try:
        v2 = sqlite.get_transcript_v2(session_id)
    except sqlite3.OperationalError as e:
        print(f"\nDB error: {e}")
        print("  → This DB isn't migrated for Part 1. Run `alembic upgrade head` on the")
        print("    DB the backend uses (same env / CONCLAVE_DB_PATH), then retry.\n")
        return
    if not v2:
        print(f"\nNo v2 draft for session {session_id!r}.")
        print("  → Is it ingested? Are you pointed at the right DB (same env as the backend)?\n")
        return
    doc = _doc(v2)

    print(f"\n=== SESSION {session_id} ===")
    print(
        f"v2 status   : {v2['status']}    insights_stale={doc.get('insights_stale')}"
        f"    approved_at={v2.get('approved_at')}    reminded_at={v2.get('reminded_at')}"
    )

    print("\n--- corrected transcript (v2) ---")
    for seg in doc.get("segments", []):
        who = seg.get("speaker_name") or seg.get("speaker_label")
        print(f"  [{who}] {' '.join(seg.get('tokens', []))}")

    anns = doc.get("annotations", [])
    print(f"\n--- annotations ({len(anns)}) — the entity ground truth Part 2 reads ---")
    for a in anns:
        sp = a.get("span", {})
        print(
            f"  '{a.get('surface')}'  state={a.get('state')}  type={a.get('type')}"
            f"  source={a.get('source')}  @seg{sp.get('segment_id')}:{sp.get('token_start')}-{sp.get('token_end')}"
        )

    row = conn.execute(
        "SELECT owner_user_id FROM transcript_sessions WHERE session_id=?", (session_id,)
    ).fetchone()
    owner = row["owner_user_id"] if row else None
    print(f"\n--- owner: {owner} ---")

    if owner:
        vocab = sqlite.list_vocab(owner)
        print(f"\n--- vocab ({len(vocab)}) — the owner's personal dictionary ---")
        for v in vocab:
            print(
                f"  '{v['surface_norm']}'  type={v.get('type')}"
                f"  is_entity={v.get('is_entity')}  provenance={v.get('provenance')}"
            )

        corr = conn.execute(
            "SELECT session_id, correction_count, approved_at FROM meeting_corrections "
            "WHERE user_id=? ORDER BY approved_at DESC NULLS LAST",
            (owner,),
        ).fetchall()
        print(f"\n--- meeting_corrections ({len(corr)}) — graduation stats ---")
        for c in corr:
            print(f"  {c['session_id']}: {c['correction_count']} corrections, approved_at={c['approved_at']}")
        # trust state is derived from these
        try:
            from transcripts import trust
            print(f"  → trust.state_for(owner) = {trust.state_for(owner)}")
        except Exception:  # noqa: BLE001
            pass

    try:
        n_ent = conn.execute("SELECT COUNT(*) AS n FROM entities").fetchone()["n"]
        n_fact = conn.execute("SELECT COUNT(*) AS n FROM facts").fetchone()["n"]
        print(
            f"\n--- entity graph: {n_ent} entities, {n_fact} facts "
            f"(entities grow on APPROVE via existing extraction; facts = Part 2's unbuilt write-path) ---\n"
        )
    except Exception as e:  # noqa: BLE001
        print(f"\n--- entity graph: (could not read: {e}) ---\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/inspect_session.py <session_id>")
        sys.exit(1)
    main(sys.argv[1])
