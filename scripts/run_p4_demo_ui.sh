#!/usr/bin/env bash
# One-command P4 demo with the REAL UI: boots FPM backend, Conclave backend, and the Conclave
# Next.js frontend from the worktrees, seeds a sample meeting, and prints the URLs to click.
# Demo ports 8091 (FPM) / 8001 (Conclave API) / 3001 (frontend) so it won't collide with
# anything you run on 8090/8000/3000. Leaves everything running until Ctrl-C.
#
#   ./scripts/run_p4_demo_ui.sh [host_email] [target_email]
#
# Real email (optional): export FPM_NOTIFY_EMAIL=1 + FPM_SMTP_HOST/PORT/USER/PASS + FPM_NOTIFY_FROM
# before running and a real confirmation email is sent when you tag someone else (Deliverable 2).
set -euo pipefail

FPM_WT=/Users/parth/Shape-Rotator/FPM-P4
CONCLAVE_WT=/Users/parth/Shape-Rotator/conclave-P4
MAIN_CONCLAVE=/Users/parth/Shape-Rotator/conclave-shape-rotator
FPM_PY=/Users/parth/Shape-Rotator/FPM/.venv/bin/python
CONCLAVE_PY=$MAIN_CONCLAVE/.venv/bin/python

HOST_EMAIL=${1:-you@example.com}
TARGET_EMAIL=${2:-target@example.com}
VID=vp_p4demo
FPM_WS=live-test
TOKEN=conclave-tok
FPM_PORT=8091
CONCLAVE_PORT=8001
WEB_PORT=3009   # dedicated demo port so it can't clash with your real frontend on :3001

FPM_DATA=$FPM_WT/data-p4demo
CONCLAVE_DATA=$CONCLAVE_WT/data-p4demo
CONCLAVE_DB=$CONCLAVE_DATA/conclave.db
mkdir -p "$FPM_DATA" "$CONCLAVE_DATA"

export FPM_DATA_DIR=$FPM_DATA
export FPM_CONSENT_AUTOCONFIRM=1   # self-tag confirms instantly in the demo
export FPM_DEV_LOGIN=1
export FPM_AUTH_TOKENS="{\"$TOKEN\":{\"name\":\"conclave\",\"endpoints\":[\"diarize\",\"knowledge\",\"identify\",\"enroll\",\"voiceprints\",\"vocab\"]}}"
export CONCLAVE_DB_PATH=$CONCLAVE_DB
export CONCLAVE_DEV_LOGIN=1
export CONCLAVE_FPM_BASE_URL=http://localhost:$FPM_PORT
export CONCLAVE_FPM_API_TOKEN=$TOKEN
export CONCLAVE_FPM_WORKSPACE=$FPM_WS
export CONCLAVE_CONSENT_TTL_SEC=0  # always-fresh consent so confirms show on reload immediately

rm -f "$FPM_DATA"/*.db "$FPM_DATA"/*.key "$CONCLAVE_DB" 2>/dev/null || true

echo "== seed FPM voiceprints =="
( cd "$FPM_WT" && "$FPM_PY" scripts/seed_p4_demo.py --workspace "$FPM_WS" --voiceprint-id "$VID,${VID}2" )
echo "== seed Conclave host + meetings =="
( cd "$CONCLAVE_WT" && "$CONCLAVE_PY" scripts/seed_p4_demo.py \
    --email "$HOST_EMAIL" --voiceprint-id "$VID" --label "Speaker 2" \
    --env-out "$CONCLAVE_DATA/gate_env.sh" )

# frontend deps: reuse the main checkout's node_modules (same lockfile) if the worktree lacks them
if [ ! -e "$CONCLAVE_WT/frontend/node_modules" ]; then
  if [ -d "$MAIN_CONCLAVE/frontend/node_modules" ]; then
    ln -s "$MAIN_CONCLAVE/frontend/node_modules" "$CONCLAVE_WT/frontend/node_modules"
  else
    ( cd "$CONCLAVE_WT/frontend" && npm install )
  fi
fi

echo "== start FPM :$FPM_PORT =="
( cd "$FPM_WT" && exec "$FPM_PY" -m uvicorn main:app --port "$FPM_PORT" --log-level warning ) &
FPM_PID=$!
echo "== start Conclave API :$CONCLAVE_PORT =="
( cd "$CONCLAVE_WT" && exec "$CONCLAVE_PY" -m uvicorn main:app --port "$CONCLAVE_PORT" --log-level warning ) &
CONCLAVE_PID=$!
echo "== start Conclave frontend :$WEB_PORT =="
( cd "$CONCLAVE_WT/frontend" && NEXT_PUBLIC_API_BASE="http://localhost:$CONCLAVE_PORT" exec ./node_modules/.bin/next dev -p "$WEB_PORT" ) &
WEB_PID=$!

cleanup() { kill "$FPM_PID" "$CONCLAVE_PID" "$WEB_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "== wait for health =="
curl -sf --retry-connrefused --retry 60 --retry-delay 1 "http://localhost:$FPM_PORT/health" >/dev/null && echo "  FPM up"
curl -sf --retry-connrefused --retry 60 --retry-delay 1 "http://localhost:$CONCLAVE_PORT/health" >/dev/null && echo "  Conclave API up"
curl -sf --retry-connrefused --retry 120 --retry-delay 1 "http://localhost:$WEB_PORT/" >/dev/null && echo "  frontend up"

cat <<EOF

────────────────────────────────────────────────────────────────────
P4 demo is live. Click through:

 1. ONE CLICK — sign in as the host AND open the meeting (use a fresh/incognito window):
      http://localhost:$WEB_PORT/api/auth/v1/dev-login?email=$HOST_EMAIL&next=/meeting/p4demo-m1
 2. In the meeting, click a speaker name to tag them:
      - tag a speaker as YOURSELF ($HOST_EMAIL) -> name fills in instantly everywhere
      - tag a speaker as $TARGET_EMAIL -> shows "pending"$( [ "${FPM_NOTIFY_EMAIL:-}" = "1" ] && echo " + sends a real email" )
 3. Confirm as the target (their dashboard):
      http://localhost:$FPM_PORT/auth/dev-login?email=$TARGET_EMAIL  then  http://localhost:$FPM_PORT/dashboard
 4. Back on the meeting, refresh -> the target's name is now in place too.

Ctrl-C to stop everything.
────────────────────────────────────────────────────────────────────
EOF

wait
