#!/usr/bin/env bash
# One-command P4 Phase-2 demo (two-actor): host tags someone else → pending → target confirms
# on the FPM dashboard → name flips across transcripts; a parallel deny stays Speaker N.
#
# Autoconfirm is OFF and FPM dev-login is ON (to mint the target's dashboard session). Demo
# ports 8091/8001; both servers killed on exit.
#
#   ./scripts/run_p4_phase2_demo.sh [host_email] [target_email] [name]
#
set -euo pipefail

FPM_WT=/Users/parth/Shape-Rotator/FPM-P4
CONCLAVE_WT=/Users/parth/Shape-Rotator/conclave-P4
FPM_PY=/Users/parth/Shape-Rotator/FPM/.venv/bin/python
CONCLAVE_PY=/Users/parth/Shape-Rotator/conclave-shape-rotator/.venv/bin/python

VID=vp_p4demo
FPM_WS=live-test
TOKEN=conclave-tok
HOST_EMAIL=${1:-you@example.com}
TARGET_EMAIL=${2:-target@example.com}
NAME=${3:-Target Person}
LABEL="Speaker 2"
FPM_PORT=8091
CONCLAVE_PORT=8001

FPM_DATA=$FPM_WT/data-p4demo
CONCLAVE_DATA=$CONCLAVE_WT/data-p4demo
CONCLAVE_DB=$CONCLAVE_DATA/conclave.db
mkdir -p "$FPM_DATA" "$CONCLAVE_DATA"

# autoconfirm OFF (cross-tag stays pending); dev-login ON (target signs in to confirm).
export FPM_DATA_DIR=$FPM_DATA
export FPM_DEV_LOGIN=1
export FPM_AUTH_TOKENS="{\"$TOKEN\":{\"name\":\"conclave\",\"endpoints\":[\"diarize\",\"knowledge\",\"identify\",\"enroll\",\"voiceprints\",\"vocab\"]}}"
export CONCLAVE_DB_PATH=$CONCLAVE_DB
export CONCLAVE_FPM_BASE_URL=http://localhost:$FPM_PORT
export CONCLAVE_FPM_API_TOKEN=$TOKEN
export CONCLAVE_FPM_WORKSPACE=$FPM_WS
export CONCLAVE_CONSENT_TTL_SEC=0   # always-fresh consent at read time so the sub-second gate sees the confirm

rm -f "$FPM_DATA"/*.db "$FPM_DATA"/*.key "$CONCLAVE_DB" 2>/dev/null || true

echo "== seed FPM voiceprints =="
( cd "$FPM_WT" && "$FPM_PY" scripts/seed_p4_demo.py --workspace "$FPM_WS" --voiceprint-id "$VID,${VID}2" )
echo "== seed Conclave host + meetings =="
( cd "$CONCLAVE_WT" && "$CONCLAVE_PY" scripts/seed_p4_demo.py \
    --email "$HOST_EMAIL" --name "$NAME" --voiceprint-id "$VID" --label "$LABEL" \
    --env-out "$CONCLAVE_DATA/gate_env.sh" )

echo "== start FPM :$FPM_PORT =="
( cd "$FPM_WT" && exec "$FPM_PY" -m uvicorn main:app --port "$FPM_PORT" --log-level warning ) &
FPM_PID=$!
echo "== start Conclave :$CONCLAVE_PORT =="
( cd "$CONCLAVE_WT" && exec "$CONCLAVE_PY" -m uvicorn main:app --port "$CONCLAVE_PORT" --log-level warning ) &
CONCLAVE_PID=$!
cleanup() { kill "$FPM_PID" "$CONCLAVE_PID" 2>/dev/null || true; }
trap cleanup EXIT

echo "== wait for health =="
curl -sf --retry-connrefused --retry 60 --retry-delay 1 "http://localhost:$FPM_PORT/health" >/dev/null || { echo "  FPM failed"; exit 1; }
echo "  FPM up"
curl -sf --retry-connrefused --retry 60 --retry-delay 1 "http://localhost:$CONCLAVE_PORT/health" >/dev/null || { echo "  Conclave failed"; exit 1; }
echo "  Conclave up"

# shellcheck disable=SC1090
source "$CONCLAVE_DATA/gate_env.sh"

echo "== run P4 Phase-2 gate =="
cd "$CONCLAVE_WT"
CONCLAVE_TOKEN="$CONCLAVE_TOKEN" FPM_TOKEN="$TOKEN" \
  "$CONCLAVE_PY" scripts/p4_phase2_gate.py \
    --conclave "http://localhost:$CONCLAVE_PORT" --fpm "http://localhost:$FPM_PORT" \
    --workspace "$GATE_WORKSPACE" --fpm-workspace "$GATE_FPM_WORKSPACE" \
    --session "$GATE_SESSION" --second-session "$GATE_SECOND_SESSION" \
    --deny-session "$GATE_DENY_SESSION" --label "$GATE_LABEL" --deny-label "$GATE_DENY_LABEL" \
    --host-email "$GATE_EMAIL" --target-email "$TARGET_EMAIL" --name "$GATE_NAME"
