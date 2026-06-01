#!/usr/bin/env bash
# Stamp an existing data/conclave.db as up-to-date through 0001_baseline.
# Use this ONCE on the live DB so Alembic knows the legacy tables already exist
# and the next migration (0002, Phase 1.3) can run cleanly.
#
# For fresh DBs, you don't need this — `alembic upgrade head` does the right
# thing on its own.
#
# Usage: ./alembic/scripts/db_stamp_baseline.sh
set -euo pipefail

# cd to repo root (this script lives at alembic/scripts/, two levels deep).
cd "$(dirname "$0")/../.."

DB_PATH="${CONCLAVE_DB_URL:-data/conclave.db}"
# Strip sqlite:// prefix if present so the backup path resolves.
DB_PATH="${DB_PATH#sqlite:///}"
DB_PATH="${DB_PATH#sqlite://}"

if [ -f "$DB_PATH" ]; then
  BACKUP="${DB_PATH}.pre-alembic-$(date +%Y%m%d-%H%M%S).bak"
  echo "→ backing up $DB_PATH → $BACKUP"
  cp "$DB_PATH" "$BACKUP"
else
  echo "→ no existing DB at $DB_PATH; alembic will treat it as fresh"
fi

echo "→ stamping baseline revision"
alembic stamp 0001_baseline

echo "→ current alembic head:"
alembic current
