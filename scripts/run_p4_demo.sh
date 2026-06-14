#!/usr/bin/env bash
# One-command P4 Phase-1 demo: start FPM + Conclave from the P4 worktrees against throwaway
# demo DBs, seed a voiceprint + two meetings sharing it, run the gate, tear down.
#
# No real audio, no clicking around. Uses demo ports 8091/8001 so it won't collide with any
# servers you already run on 8090/8000. Both servers are killed on exit (trap).
#
#   ./scripts/run_p4_demo.sh [email] [name]
#
set -euo pipefail

# --- paths (worktrees hold the P4 code; main checkouts don't yet) ---
FPM_WT=/Users/parth/Shape-Rotator/FPM-P4
CONCLAVE_WT=/Users/parth/Shape-Rotator/conclave-P4
# Launch servers via `python -m uvicorn` (the venvs' uvicorn console-scripts can carry a
# stale shebang; the python binaries are the reliable entrypoint).
FPM_PY=/Users/parth/Shape-Rotator/FPM/.venv/bin/python
CONCLAVE_PY=/Users/parth/Shape-Rotator/conclave-shape-rotator/.venv/bin/python

# --- demo config ---
VID=vp_p4demo
FPM_WS=live-test
TOKEN=conclave-tok
EMAIL=${1:-you@example.com}
NAME=${2:-Demo User}
LABEL="Speaker 2"
FPM_PORT=8091
CONCLAVE_PORT=8001

FPM_DATA=$FPM_WT/data-p4demo
CONCLAVE_DATA=$CONCLAVE_WT/data-p4demo
CONCLAVE_DB=$CONCLAVE_DATA/conclave.db
mkdir -p "$FPM_DATA" "$CONCLAVE_DATA"

# --- env shared by seeds + servers ---
export FPM_DATA_DIR=$FPM_DATA
export FPM_CONSENT_AUTOCONFIRM=1
export FPM_AUTH_TOKENS="{\"$TOKEN\":{\"name\":\"conclave\",\"endpoints\":[\"diarize\",\"knowledge\",\"identify\",\"enroll\",\"voiceprints\",\"vocab\"]}}"
export CONCLAVE_DB_PATH=$CONCLAVE_DB
export CONCLAVE_FPM_BASE_URL=http://localhost:$FPM_PORT
export CONCLAVE_FPM_API_TOKEN=$TOKEN
export CONCLAVE_FPM_WORKSPACE=$FPM_WS

# --- fresh slate ---
rm -f "$FPM_DATA"/*.db "$FPM_DATA"/*.key "$CONCLAVE_DB" 2>/dev/null || true

echo "== seed FPM voiceprint =="
( cd "$FPM_WT" && "$FPM_PY" scripts/seed_p4_demo.py --workspace "$FPM_WS" --voiceprint-id "$VID" )
echo "== seed Conclave user + 2 meetings =="
( cd "$CONCLAVE_WT" && "$CONCLAVE_PY" scripts/seed_p4_demo.py \
    --email "$EMAIL" --name "$NAME" --voiceprint-id "$VID" --label "$LABEL" \
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
if ! curl -sf --retry-connrefused --retry 60 --retry-delay 1 "http://localhost:$FPM_PORT/health" >/dev/null; then
  echo "  FPM failed to start"; exit 1
fi
echo "  FPM up"
if ! curl -sf --retry-connrefused --retry 60 --retry-delay 1 "http://localhost:$CONCLAVE_PORT/health" >/dev/null; then
  echo "  Conclave failed to start"; exit 1
fi
echo "  Conclave up"

# shellcheck disable=SC1090
source "$CONCLAVE_DATA/gate_env.sh"

echo "== run P4 Phase-1 gate =="
cd "$CONCLAVE_WT"
CONCLAVE_TOKEN="$CONCLAVE_TOKEN" FPM_TOKEN="$TOKEN" FPM_DB_PATH="$FPM_DATA/voiceprints.db" \
  "$CONCLAVE_PY" scripts/p4_phase1_gate.py \
    --conclave "http://localhost:$CONCLAVE_PORT" --fpm "http://localhost:$FPM_PORT" \
    --workspace "$GATE_WORKSPACE" --fpm-workspace "$GATE_FPM_WORKSPACE" \
    --session "$GATE_SESSION" --second-session "$GATE_SECOND_SESSION" \
    --label "$GATE_LABEL" --email "$GATE_EMAIL" --name "$GATE_NAME"
