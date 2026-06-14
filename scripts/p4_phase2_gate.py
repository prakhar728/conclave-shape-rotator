#!/usr/bin/env python3
"""P4 Phase-2 GATE — two-actor host-tag → email → target confirms → flip; deny stays Speaker N.

The human-supervised capstone for Phase 2 (autoconfirm OFF). A host tags a speaker as SOMEONE
ELSE → FPM creates a *pending* proposal (notify fires, log-only) → the target signs into the FPM
consent dashboard, sees their pending inbox, and confirms → the name then surfaces across the
transcripts via the read-time consent backstop. A parallel proposal that the target DENIES leaves
that speaker as `Speaker N`.

Needs FPM with FPM_DEV_LOGIN=1 (to mint the target's dashboard session) and CONSENT_AUTOCONFIRM
OFF. The unit halves are covered by FPM test_propose_api/test_consent_api and Conclave
test_consent_backstop; this wires the two real processes together.

Run via scripts/run_p4_phase2_demo.sh (which seeds + starts both servers), or manually with the
same env the Phase-1 gate uses plus --host-email and --target-email.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request


def _req(method, url, token=None, body=None, opener=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    fn = opener.open if opener else urllib.request.urlopen
    try:
        with fn(req, timeout=30) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return r.status, {}  # e.g. dev-login redirect/HTML — we only need the cookie
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:  # noqa: BLE001
            return e.code, {}


def _ok(m):
    print(f"  \033[32mPASS\033[0m {m}")


def _fail(m):
    print(f"  \033[31mFAIL\033[0m {m}")
    sys.exit(1)


def _names_for_label(conclave, token, sid, label):
    status, body = _req("GET", f"{conclave}/transcripts/sessions/{sid}/transcript", token=token)
    if status != 200:
        _fail(f"GET transcript {sid} → {status}: {body}")
    return [s.get("speaker_name") for s in body.get("segments", []) if s.get("speaker") == label]


def _tag(conclave, token, ws, sid, label, name, email):
    return _req("POST", f"{conclave}/api/workspaces/{ws}/meetings/{sid}/tag-speaker",
                token=token, body={"label": label, "name": name, "email": email})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conclave", default=os.environ.get("CONCLAVE_BASE", "http://localhost:8000"))
    ap.add_argument("--fpm", default=os.environ.get("FPM_BASE", "http://localhost:8090"))
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--fpm-workspace", required=True)
    ap.add_argument("--session", required=True)
    ap.add_argument("--second-session", required=True)
    ap.add_argument("--deny-session", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--deny-label", required=True)
    ap.add_argument("--host-email", required=True, help="the tagging host (logged into Conclave)")
    ap.add_argument("--target-email", required=True, help="the tagged person (≠ host) who confirms")
    ap.add_argument("--name", required=True)
    a = ap.parse_args()

    conclave_token = os.environ.get("CONCLAVE_TOKEN")
    fpm_token = os.environ.get("FPM_TOKEN")
    if not conclave_token or not fpm_token:
        _fail("set CONCLAVE_TOKEN and FPM_TOKEN")
    if a.host_email.lower() == a.target_email.lower():
        _fail("host-email and target-email must differ (this is the two-actor flow)")

    print(f"P4 Phase-2 gate: host {a.host_email} tags '{a.label}' as {a.target_email} (pending)\n")

    # 1) host tags someone else → pending (autoconfirm OFF), no name flip yet.
    status, body = _tag(a.conclave, conclave_token, a.workspace, a.session, a.label, a.name, a.target_email)
    if status != 200:
        _fail(f"tag-speaker → {status}: {body}")
    if body.get("status") != "pending":
        _fail(f"expected pending (autoconfirm off, cross-tag), got: {body}")
    vid = body.get("voiceprint_id")
    _ok(f"host tag created a pending proposal (voiceprint_id={vid})")

    if a.name in _names_for_label(a.conclave, conclave_token, a.session, a.label):
        _fail("name surfaced BEFORE the target confirmed — pending must not flip a name")
    _ok("pre-confirm: speaker is still anonymous in the transcript")

    # 2) target signs into the FPM consent dashboard (dev-login) → pending inbox → confirm.
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    status, _ = _req("GET", f"{a.fpm}/auth/dev-login?email={a.target_email}", opener=opener)
    if status not in (200, 302, 307):
        _fail(f"FPM dev-login for target → {status}")
    status, inbox = _req("GET", f"{a.fpm}/v1/me/pending", opener=opener)
    if status != 200:
        _fail(f"GET /v1/me/pending → {status}: {inbox}")
    pending = [p for p in inbox.get("pending", []) if p.get("voiceprint_id") == vid]
    if not pending:
        _fail(f"target's pending inbox is missing the proposal for {vid}: {inbox}")
    proposal_id = pending[0]["proposal_id"]
    _ok(f"target's inbox shows the pending proposal ({proposal_id})")

    status, conf = _req("POST", f"{a.fpm}/v1/confirm", body={"proposal_id": proposal_id}, opener=opener)
    if status != 200 or conf.get("status") != "confirmed":
        _fail(f"target confirm → {status}: {conf}")
    _ok(f"target confirmed → bound owner_email={conf.get('owner_email')} name={conf.get('name')}")

    # 3) name now surfaces across BOTH transcripts via the read-time consent backstop.
    if a.name not in _names_for_label(a.conclave, conclave_token, a.session, a.label):
        _fail(f"{a.session}: name did not surface after confirm")
    _ok(f"{a.session}: '{a.label}' → {a.name} (post-confirm, via backstop)")
    second = _names_for_label(a.conclave, conclave_token, a.second_session, a.label)
    if a.name not in second:
        status, t2 = _req("GET", f"{a.conclave}/transcripts/sessions/{a.second_session}/transcript",
                          token=conclave_token)
        if a.name not in {s.get("speaker_name") for s in t2.get("segments", [])}:
            _fail(f"{a.second_session}: cross-transcript flip missing")
    _ok(f"{a.second_session}: cross-transcript flip → {a.name}")

    # 4) deny arm: a parallel proposal the target DENIES leaves the speaker as Speaker N.
    status, body = _tag(a.conclave, conclave_token, a.workspace, a.deny_session, a.deny_label,
                        "Should Not Appear", a.target_email)
    if status != 200 or body.get("status") != "pending":
        _fail(f"deny-arm tag → {status}: {body}")
    deny_vid = body.get("voiceprint_id")
    status, inbox = _req("GET", f"{a.fpm}/v1/me/pending", opener=opener)
    dp = [p for p in inbox.get("pending", []) if p.get("voiceprint_id") == deny_vid]
    if not dp:
        _fail(f"deny-arm proposal not in inbox: {inbox}")
    status, _ = _req("POST", f"{a.fpm}/v1/deny", body={"proposal_id": dp[0]["proposal_id"]}, opener=opener)
    if status != 200:
        _fail(f"deny → {status}")
    names = _names_for_label(a.conclave, conclave_token, a.deny_session, a.deny_label)
    if any(n for n in names):
        _fail(f"denied speaker should stay anonymous, but got names: {names}")
    _ok(f"{a.deny_session}: denied → '{a.deny_label}' stays Speaker N")

    print("\n\033[32mP4 Phase-2 GATE PASSED\033[0m — host-tag→target-confirm flips the name across "
          "transcripts; deny leaves Speaker N.")


if __name__ == "__main__":
    main()
