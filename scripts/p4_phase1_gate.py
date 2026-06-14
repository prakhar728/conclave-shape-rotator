#!/usr/bin/env python3
"""P4 Phase-1 GATE — self-identification auto-confirm, end-to-end, on two live processes.

This is the human-supervised checkpoint for Phase 1 (NOT a CI unit test — the unit halves
are locked by the FPM `test_propose_api`/`test_proposals` suites and Conclave's
`test_reresolve`/`test_tag_speaker`). It drives the *real* FPM + Conclave servers and
asserts the full spine: a host tags a speaker as themselves → FPM auto-confirms (self-tag)
→ `owner_email`+`name` bind on the voiceprint → the name re-resolves across EVERY transcript
carrying that voiceprint.

## Setup (see the local-test-topology)
- FPM on :8090 from the diarizen venv, with `FPM_CONSENT_AUTOCONFIRM=1` (or rely on the
  self-tag path, which auto-confirms regardless) and an auth token carrying the `knowledge`
  scope on the test workspace.
- Conclave on :8000, logged in as the self user (a Bearer session token).
- TWO recorded meetings in the same workspace that share one voiceprint for `--label`
  (record the same person twice, or re-run the record path on two clips of the same voice).

## Run
    CONCLAVE_TOKEN=... FPM_TOKEN=... \
    python scripts/p4_phase1_gate.py \
      --workspace <conclave_ws> --session <sid1> --second-session <sid2> \
      --label "Speaker 2" --email you@example.com --name "Your Name" \
      --fpm-workspace <fpm_ws> [--fpm-db /path/to/voiceprints.db]

Exits non-zero (loudly) on the first failed assertion.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request


def _req(method: str, url: str, token: str | None = None, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:  # noqa: BLE001
            return e.code, {}


def _ok(msg: str) -> None:
    print(f"  \033[32mPASS\033[0m {msg}")


def _fail(msg: str) -> None:
    print(f"  \033[31mFAIL\033[0m {msg}")
    sys.exit(1)


def _transcript_names_for_label(conclave: str, token: str, sid: str, label: str) -> list:
    """speaker_name(s) projected for `label` in a session's transcript (owner-gated read)."""
    status, body = _req("GET", f"{conclave}/transcripts/sessions/{sid}/transcript", token=token)
    if status != 200:
        _fail(f"GET transcript {sid} → {status}: {body}")
    return [s.get("speaker_name") for s in body.get("segments", []) if s.get("speaker") == label]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conclave", default=os.environ.get("CONCLAVE_BASE", "http://localhost:8000"))
    ap.add_argument("--fpm", default=os.environ.get("FPM_BASE", "http://localhost:8090"))
    ap.add_argument("--workspace", required=True, help="Conclave workspace id")
    ap.add_argument("--fpm-workspace", required=True, help="FPM workspace id (fpm_workspace_for)")
    ap.add_argument("--session", required=True, help="the meeting to tag in")
    ap.add_argument("--second-session", required=True, help="another meeting sharing the voiceprint")
    ap.add_argument("--label", required=True, help='display label to tag, e.g. "Speaker 2"')
    ap.add_argument("--email", required=True, help="self email (== logged-in user → self-tag)")
    ap.add_argument("--name", required=True, help="the name to bind")
    ap.add_argument("--fpm-db", default=os.environ.get("FPM_DB_PATH"), help="optional: assert binding_audit")
    args = ap.parse_args()

    conclave_token = os.environ.get("CONCLAVE_TOKEN")
    fpm_token = os.environ.get("FPM_TOKEN")
    if not conclave_token:
        _fail("set CONCLAVE_TOKEN (Bearer session for the self user)")
    if not fpm_token:
        _fail("set FPM_TOKEN (Bearer, knowledge scope)")

    print(f"P4 Phase-1 gate: tag '{args.label}' as {args.email} (self) in {args.session}\n")

    # 1) host tags the speaker as themselves → FPM auto-confirms (self-tag).
    status, body = _req(
        "POST",
        f"{args.conclave}/api/workspaces/{args.workspace}/meetings/{args.session}/tag-speaker",
        token=conclave_token,
        body={"label": args.label, "name": args.name, "email": args.email},
    )
    if status != 200:
        _fail(f"tag-speaker → {status}: {body}")
    vid = body.get("voiceprint_id")
    if body.get("status") != "confirmed" or not vid:
        _fail(f"expected self-tag to auto-confirm, got: {body}")
    _ok(f"tag-speaker auto-confirmed (voiceprint_id={vid})")

    # 2) FPM read side: owner_email + name bound, identify gate passes (visibility=named).
    status, res = _req(
        "GET", f"{args.fpm}/v1/consent/resolve/{args.fpm_workspace}/{vid}", token=fpm_token,
    )
    if status != 200:
        _fail(f"FPM consent-resolve → {status}: {res}")
    if res.get("visibility") != "named":
        _fail(f"expected visibility=named, got: {res}")
    if res.get("name") != args.name:
        _fail(f"expected name={args.name!r}, got {res.get('name')!r}")
    if (res.get("owner_email") or "").lower() != args.email.lower():
        _fail(f"expected owner_email={args.email!r}, got {res.get('owner_email')!r}")
    _ok(f"FPM bound owner_email={res['owner_email']} name={res['name']} (visibility=named)")

    # 3) cross-transcript projection: the name shows in BOTH meetings for this voiceprint.
    here = _transcript_names_for_label(args.conclave, conclave_token, args.session, args.label)
    if args.name not in here:
        _fail(f"tagged meeting {args.session} label {args.label!r} did not project {args.name!r}: {here}")
    _ok(f"{args.session}: '{args.label}' → {args.name}")

    second = _transcript_names_for_label(args.conclave, conclave_token, args.second_session, args.label)
    if args.name not in second:
        # the second meeting may number the voiceprint under a different label — accept any
        status, t2 = _req("GET", f"{args.conclave}/transcripts/sessions/{args.second_session}/transcript",
                          token=conclave_token)
        all_names = {s.get("speaker_name") for s in t2.get("segments", [])}
        if args.name not in all_names:
            _fail(f"second meeting {args.second_session} never projects {args.name!r} "
                  f"(names seen: {sorted(n for n in all_names if n)})")
    _ok(f"{args.second_session}: cross-transcript name flip → {args.name}")

    # 4) optional: binding_audit proof trail (reads the FPM sqlite directly; plaintext column).
    if args.fpm_db:
        conn = sqlite3.connect(args.fpm_db)
        rows = conn.execute(
            "SELECT new_name, actor FROM binding_audit WHERE workspace_id=? AND voiceprint_id=? "
            "AND new_name=?", (args.fpm_workspace, vid, args.name),
        ).fetchall()
        conn.close()
        if not rows:
            _fail(f"no binding_audit row for vid={vid} new_name={args.name!r}")
        _ok(f"binding_audit row present ({len(rows)}) — bind is reversible + traceable")
    else:
        print("  note: binding_audit assertion skipped (pass --fpm-db to enable)")

    print("\n\033[32mP4 Phase-1 GATE PASSED\033[0m — self-id auto-confirm flips the name across "
          "all transcripts with that voiceprint.")


if __name__ == "__main__":
    main()
