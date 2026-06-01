"""SQLite-backed persistent storage.

Single connection, JSON `data` columns for variant payloads, typed columns
for the fields routes.py queries against (instance_id, submission_id, token,
role, etc.).

Schema includes evaluation_runs and attestations tables that aren't yet used
by the API — they're stubbed here so phases 5 (scheduler) and 8 (Solana
attestation) don't need a migration step.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any

_DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "conclave.db")
_DB_PATH = os.environ.get("CONCLAVE_DB_PATH", _DEFAULT_PATH)

# Shared connection used only for `:memory:` databases, which cannot be shared
# across separate connections (each connect() to ":memory:" gets its own empty
# DB). File-backed databases instead use one connection per thread (`_local`).
_conn: sqlite3.Connection | None = None
_local = threading.local()
_lock = threading.Lock()


def _new_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(
        _DB_PATH,
        check_same_thread=False,
        isolation_level=None,  # autocommit
    )
    conn.row_factory = sqlite3.Row
    if _DB_PATH != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
        # Wait (rather than erroring) when another connection holds the write
        # lock, instead of raising "database is locked" immediately.
        conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    _init_schema(conn)
    return conn


def _get_conn() -> sqlite3.Connection:
    """Return a SQLite connection safe to use from the current thread.

    FastAPI runs sync endpoints in a threadpool, so a single connection shared
    across threads would race on its in-memory WAL index — surfacing as the
    spurious "database disk image is malformed". Giving each thread its own
    connection lets WAL mode do what it's built for: concurrent readers plus a
    single serialized writer, with no shared mutable connection state.
    """
    global _conn
    if _DB_PATH == ":memory:":
        if _conn is None:
            with _lock:
                if _conn is None:
                    _conn = _new_conn()
        return _conn
    conn = getattr(_local, "conn", None)
    # Reopen if this thread has no connection yet, or if _DB_PATH was swapped
    # out from under us (tests monkeypatch it / reset `_conn` to None between
    # cases). Comparing the cached path keeps that reset working now that
    # connections live on the thread-local rather than the `_conn` global.
    if conn is None or getattr(_local, "path", None) != _DB_PATH:
        if conn is not None:
            conn.close()
        os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
        conn = _new_conn()
        _local.conn = conn
        _local.path = _DB_PATH
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS instances (
            instance_id TEXT PRIMARY KEY,
            skill_name TEXT NOT NULL,
            data TEXT NOT NULL,         -- JSON: {config, threshold, triggered, ...}
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS submissions (
            instance_id TEXT NOT NULL,
            submission_id TEXT NOT NULL,
            data TEXT NOT NULL,         -- JSON: full submission dict
            submitted_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (instance_id, submission_id)
        );

        CREATE TABLE IF NOT EXISTS results (
            instance_id TEXT NOT NULL,
            submission_id TEXT NOT NULL,
            data TEXT NOT NULL,         -- JSON: full result dict
            computed_at TEXT NOT NULL,
            PRIMARY KEY (instance_id, submission_id)
        );

        CREATE TABLE IF NOT EXISTS tokens (
            token TEXT PRIMARY KEY,
            instance_id TEXT NOT NULL,
            role TEXT NOT NULL,         -- 'admin' or 'user'
            data TEXT NOT NULL,         -- JSON: {submission_ids: [...], supabase_user_id?}
            created_at TEXT NOT NULL,
            expires_at TEXT
        );

        CREATE TABLE IF NOT EXISTS registrations (
            instance_id TEXT NOT NULL,
            supabase_user_id TEXT NOT NULL,
            token TEXT NOT NULL,
            PRIMARY KEY (instance_id, supabase_user_id)
        );

        CREATE TABLE IF NOT EXISTS evaluation_runs (
            run_id TEXT PRIMARY KEY,
            instance_id TEXT NOT NULL,
            ran_at TEXT NOT NULL,
            submission_count INTEGER NOT NULL,
            data TEXT                   -- JSON: aggregate snapshot for this tick
        );

        CREATE TABLE IF NOT EXISTS attestations (
            instance_id TEXT NOT NULL,
            report_hash TEXT NOT NULL,
            tx_sig TEXT,
            chain TEXT NOT NULL DEFAULT 'solana-devnet',
            published_at TEXT NOT NULL,
            data TEXT,
            PRIMARY KEY (instance_id, report_hash)
        );

        -- Transcript pipeline (Layer 1). One row per diarized session.
        -- `raw_diarization` is written once and never mutated; every future
        -- pipeline stage (speaker resolution, graph matching, cross-transcript
        -- relations) reads here and writes back only to `metadata`/`derived`.
        -- `source` and `session_date` are typed columns so Layer-2 organizer
        -- queries can filter by source / date range without parsing JSON.
        CREATE TABLE IF NOT EXISTS transcript_sessions (
            session_id      TEXT PRIMARY KEY,
            source          TEXT NOT NULL,   -- 'voxterm', 'whisper', 'assemblyai', ...
            session_date    TEXT NOT NULL,   -- ISO date (YYYY-MM-DD) for range queries
            raw_diarization TEXT NOT NULL,   -- JSON array — IMMUTABLE after first insert
            metadata        TEXT NOT NULL,   -- JSON: resolved_speakers, tags, pipeline_version, provenance
            derived         TEXT NOT NULL,   -- JSON: {summary, signals, entities, graph_nodes}
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_transcript_sessions_date
            ON transcript_sessions (session_date);
        CREATE INDEX IF NOT EXISTS idx_transcript_sessions_source
            ON transcript_sessions (source);
        """
    )


def init_db() -> None:
    """Initialize the schema. Called at app startup."""
    _get_conn()


def reset_all() -> None:
    """Wipe every table. Used by test fixtures."""
    conn = _get_conn()
    conn.executescript(
        """
        DELETE FROM instances;
        DELETE FROM submissions;
        DELETE FROM results;
        DELETE FROM tokens;
        DELETE FROM registrations;
        DELETE FROM evaluation_runs;
        DELETE FROM attestations;
        DELETE FROM transcript_sessions;
        """
    )


def _now() -> str:
    from datetime import datetime
    return datetime.utcnow().isoformat() + "Z"


def _to_jsonable(value: Any) -> Any:
    """Convert pydantic models, sets, etc. into JSON-serializable structures."""
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, set):
        return list(value)
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    return value


# --- Instances ---

def create_instance(instance_id: str, skill_name: str, **fields: Any) -> None:
    """Insert a new instance. All `fields` are stored in the JSON `data` column.

    Conventional fields used by routes.py: config (dict), threshold (int),
    triggered (bool), name, end_date, evaluation_frequency_seconds, tracks.
    """
    payload = {k: _to_jsonable(v) for k, v in fields.items()}
    payload.setdefault("triggered", False)
    now = _now()
    _get_conn().execute(
        "INSERT INTO instances (instance_id, skill_name, data, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (instance_id, skill_name, json.dumps(payload), now, now),
    )


def get_instance(instance_id: str) -> dict | None:
    """Return {instance_id, skill_name, **stored_fields} or None if not found."""
    row = _get_conn().execute(
        "SELECT skill_name, data FROM instances WHERE instance_id = ?", (instance_id,)
    ).fetchone()
    if row is None:
        return None
    payload = json.loads(row["data"])
    return {"instance_id": instance_id, "skill_name": row["skill_name"], **payload}


def has_instance(instance_id: str) -> bool:
    row = _get_conn().execute(
        "SELECT 1 FROM instances WHERE instance_id = ?", (instance_id,)
    ).fetchone()
    return row is not None


def set_instance_triggered(instance_id: str, triggered: bool = True) -> None:
    inst = get_instance(instance_id)
    if inst is None:
        raise KeyError(f"Instance {instance_id} not found")
    payload = {k: v for k, v in inst.items() if k not in ("instance_id", "skill_name")}
    payload["triggered"] = triggered
    _get_conn().execute(
        "UPDATE instances SET data = ?, updated_at = ? WHERE instance_id = ?",
        (json.dumps(payload), _now(), instance_id),
    )


def list_instances() -> list[dict]:
    rows = _get_conn().execute(
        "SELECT instance_id, skill_name, data FROM instances"
    ).fetchall()
    out = []
    for row in rows:
        payload = json.loads(row["data"])
        out.append({"instance_id": row["instance_id"], "skill_name": row["skill_name"], **payload})
    return out


def count_instances() -> int:
    return _get_conn().execute("SELECT COUNT(*) FROM instances").fetchone()[0]


# --- Submissions ---

def upsert_submission(instance_id: str, submission_id: str, data: dict) -> None:
    """Insert or update a submission. _submitted_at is preserved on update; updated_at always advances."""
    serialized = json.dumps(_to_jsonable(data))
    submitted_at = data.get("_submitted_at") or _now()
    now = _now()
    _get_conn().execute(
        """
        INSERT INTO submissions (instance_id, submission_id, data, submitted_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(instance_id, submission_id) DO UPDATE SET
            data = excluded.data,
            updated_at = excluded.updated_at
        """,
        (instance_id, submission_id, serialized, submitted_at, now),
    )


def get_submission(instance_id: str, submission_id: str) -> dict | None:
    row = _get_conn().execute(
        "SELECT data FROM submissions WHERE instance_id = ? AND submission_id = ?",
        (instance_id, submission_id),
    ).fetchone()
    if row is None:
        return None
    return json.loads(row["data"])


def list_submissions(instance_id: str) -> dict[str, dict]:
    rows = _get_conn().execute(
        "SELECT submission_id, data FROM submissions WHERE instance_id = ?",
        (instance_id,),
    ).fetchall()
    return {row["submission_id"]: json.loads(row["data"]) for row in rows}


def count_submissions(instance_id: str | None = None) -> int:
    if instance_id is None:
        return _get_conn().execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
    return _get_conn().execute(
        "SELECT COUNT(*) FROM submissions WHERE instance_id = ?", (instance_id,)
    ).fetchone()[0]


# --- Results ---

def upsert_result(instance_id: str, submission_id: str, data: dict) -> None:
    serialized = json.dumps(_to_jsonable(data))
    _get_conn().execute(
        """
        INSERT INTO results (instance_id, submission_id, data, computed_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(instance_id, submission_id) DO UPDATE SET
            data = excluded.data,
            computed_at = excluded.computed_at
        """,
        (instance_id, submission_id, serialized, _now()),
    )


def get_result(instance_id: str, submission_id: str) -> dict | None:
    row = _get_conn().execute(
        "SELECT data FROM results WHERE instance_id = ? AND submission_id = ?",
        (instance_id, submission_id),
    ).fetchone()
    if row is None:
        return None
    return json.loads(row["data"])


def list_results(instance_id: str) -> list[dict]:
    rows = _get_conn().execute(
        "SELECT data FROM results WHERE instance_id = ?", (instance_id,)
    ).fetchall()
    return [json.loads(row["data"]) for row in rows]


# --- Tokens ---

def create_token(token: str, instance_id: str, role: str, supabase_user_id: str | None = None) -> None:
    payload: dict = {"submission_ids": []}
    if supabase_user_id:
        payload["supabase_user_id"] = supabase_user_id
    _get_conn().execute(
        "INSERT INTO tokens (token, instance_id, role, data, created_at) VALUES (?, ?, ?, ?, ?)",
        (token, instance_id, role, json.dumps(payload), _now()),
    )


def get_token(token: str) -> dict | None:
    row = _get_conn().execute(
        "SELECT instance_id, role, data FROM tokens WHERE token = ?", (token,)
    ).fetchone()
    if row is None:
        return None
    payload = json.loads(row["data"])
    return {
        "instance_id": row["instance_id"],
        "role": row["role"],
        "submission_ids": set(payload.get("submission_ids", [])),
        "supabase_user_id": payload.get("supabase_user_id"),
    }


def has_token(token: str) -> bool:
    row = _get_conn().execute(
        "SELECT 1 FROM tokens WHERE token = ?", (token,)
    ).fetchone()
    return row is not None


def add_submission_to_token(token: str, submission_id: str) -> None:
    info = get_token(token)
    if info is None:
        raise KeyError(f"Token {token} not found")
    sids = info["submission_ids"]
    sids.add(submission_id)
    payload = {
        "submission_ids": sorted(sids),
    }
    if info.get("supabase_user_id"):
        payload["supabase_user_id"] = info["supabase_user_id"]
    _get_conn().execute(
        "UPDATE tokens SET data = ? WHERE token = ?", (json.dumps(payload), token)
    )


# --- Registrations ---

def get_registration_token(instance_id: str, supabase_user_id: str) -> str | None:
    row = _get_conn().execute(
        "SELECT token FROM registrations WHERE instance_id = ? AND supabase_user_id = ?",
        (instance_id, supabase_user_id),
    ).fetchone()
    return row["token"] if row else None


def set_registration_token(instance_id: str, supabase_user_id: str, token: str) -> None:
    _get_conn().execute(
        """
        INSERT INTO registrations (instance_id, supabase_user_id, token) VALUES (?, ?, ?)
        ON CONFLICT(instance_id, supabase_user_id) DO UPDATE SET token = excluded.token
        """,
        (instance_id, supabase_user_id, token),
    )


# --- Evaluation runs ---

def record_evaluation_run(instance_id: str, submission_count: int, snapshot: dict | None = None) -> str:
    """Record one pipeline tick. Returns the run_id."""
    import uuid as _uuid
    run_id = str(_uuid.uuid4())
    _get_conn().execute(
        "INSERT INTO evaluation_runs (run_id, instance_id, ran_at, submission_count, data) VALUES (?, ?, ?, ?, ?)",
        (run_id, instance_id, _now(), int(submission_count), json.dumps(_to_jsonable(snapshot)) if snapshot else None),
    )
    return run_id


def list_evaluation_runs(instance_id: str) -> list[dict]:
    """Return history of pipeline ticks for an instance, oldest-first."""
    rows = _get_conn().execute(
        "SELECT run_id, ran_at, submission_count, data FROM evaluation_runs "
        "WHERE instance_id = ? ORDER BY ran_at ASC",
        (instance_id,),
    ).fetchall()
    out = []
    for row in rows:
        out.append({
            "run_id": row["run_id"],
            "ran_at": row["ran_at"],
            "submission_count": row["submission_count"],
            "snapshot": json.loads(row["data"]) if row["data"] else None,
        })
    return out


# --- Attestations ---

def record_attestation(
    instance_id: str,
    report_hash: str,
    tx_sig: str | None,
    chain: str,
    extra: dict | None = None,
) -> None:
    """Persist one attestation. report_hash is hex-encoded SHA-256."""
    extras_json = json.dumps(_to_jsonable(extra)) if extra else None
    _get_conn().execute(
        """
        INSERT INTO attestations (instance_id, report_hash, tx_sig, chain, published_at, data)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(instance_id, report_hash) DO UPDATE SET
            tx_sig = excluded.tx_sig,
            chain = excluded.chain,
            published_at = excluded.published_at,
            data = excluded.data
        """,
        (instance_id, report_hash, tx_sig, chain, _now(), extras_json),
    )


def list_attestations(instance_id: str) -> list[dict]:
    rows = _get_conn().execute(
        "SELECT report_hash, tx_sig, chain, published_at, data FROM attestations "
        "WHERE instance_id = ? ORDER BY published_at ASC",
        (instance_id,),
    ).fetchall()
    out = []
    for row in rows:
        extras = json.loads(row["data"]) if row["data"] else {}
        out.append({
            "report_hash": row["report_hash"],
            "tx_sig": row["tx_sig"],
            "chain": row["chain"],
            "published_at": row["published_at"],
            **extras,
        })
    return out


# --- Transcript sessions (Layer 1 pipeline) ---

def save_transcript_session(
    session_id: str,
    source: str,
    session_date: str,
    raw_diarization: list,
    metadata: dict,
    derived: dict,
) -> None:
    """Insert a session, or update only its `metadata`/`derived` if it exists.

    Enforces the pipeline's core invariant: `raw_diarization` (and the
    `source`/`session_date` provenance) are written once on first insert and
    are never overwritten on re-save. Re-running enrichment, speaker
    resolution, or graph matching updates `metadata`/`derived` only.
    """
    now = _now()
    _get_conn().execute(
        """
        INSERT INTO transcript_sessions
            (session_id, source, session_date, raw_diarization, metadata, derived, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            metadata = excluded.metadata,
            derived = excluded.derived,
            updated_at = excluded.updated_at
        """,
        (
            session_id,
            source,
            session_date,
            json.dumps(_to_jsonable(raw_diarization)),
            json.dumps(_to_jsonable(metadata)),
            json.dumps(_to_jsonable(derived)),
            now,
            now,
        ),
    )


def get_transcript_session(session_id: str) -> dict | None:
    row = _get_conn().execute(
        "SELECT session_id, source, session_date, raw_diarization, metadata, derived, "
        "created_at, updated_at FROM transcript_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "session_id": row["session_id"],
        "source": row["source"],
        "session_date": row["session_date"],
        "raw_diarization": json.loads(row["raw_diarization"]),
        "metadata": json.loads(row["metadata"]),
        "derived": json.loads(row["derived"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_transcript_sessions(
    source: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """List sessions, newest-first, optionally filtered by source / date range.

    `date_from` / `date_to` are inclusive ISO dates (YYYY-MM-DD). This is the
    query surface Layer-2 organizer prompts fan out over.
    """
    clauses, params = [], []
    if source is not None:
        clauses.append("source = ?")
        params.append(source)
    if date_from is not None:
        clauses.append("session_date >= ?")
        params.append(date_from)
    if date_to is not None:
        clauses.append("session_date <= ?")
        params.append(date_to)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = _get_conn().execute(
        "SELECT session_id, source, session_date, raw_diarization, metadata, derived, "
        f"created_at, updated_at FROM transcript_sessions{where} "
        "ORDER BY session_date DESC, created_at DESC",
        tuple(params),
    ).fetchall()
    out = []
    for row in rows:
        out.append({
            "session_id": row["session_id"],
            "source": row["source"],
            "session_date": row["session_date"],
            "raw_diarization": json.loads(row["raw_diarization"]),
            "metadata": json.loads(row["metadata"]),
            "derived": json.loads(row["derived"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        })
    return out


def update_transcript_derived(session_id: str, derived: dict) -> None:
    """Replace the `derived` block for a session (raw stays untouched)."""
    _get_conn().execute(
        "UPDATE transcript_sessions SET derived = ?, updated_at = ? WHERE session_id = ?",
        (json.dumps(_to_jsonable(derived)), _now(), session_id),
    )


def update_transcript_metadata(session_id: str, metadata: dict) -> None:
    """Replace the `metadata` block for a session (raw stays untouched)."""
    _get_conn().execute(
        "UPDATE transcript_sessions SET metadata = ?, updated_at = ? WHERE session_id = ?",
        (json.dumps(_to_jsonable(metadata)), _now(), session_id),
    )


def set_transcript_workspace(
    session_id: str,
    workspace_id: str | None,
    owner_user_id: str | None,
    visibility: str | None = None,
) -> None:
    """Set the workspace/owner/visibility typed columns added in Alembic 0004.

    Use this when promoting a legacy NULL-workspace session into a real
    workspace, or when wiring a freshly-ingested webhook session to its
    inviting user (Phase 2). Leaves the existing JSON metadata column
    alone — `can_see` (Phase 1.7) reads the typed columns, not the JSON.
    """
    fields, params = ["updated_at = ?"], [_now()]
    fields.insert(0, "workspace_id = ?")
    params.insert(0, workspace_id)
    fields.insert(1, "owner_user_id = ?")
    params.insert(1, owner_user_id)
    if visibility is not None:
        fields.insert(2, "visibility = ?")
        params.insert(2, visibility)
    params.append(session_id)
    _get_conn().execute(
        f"UPDATE transcript_sessions SET {', '.join(fields)} WHERE session_id = ?",
        tuple(params),
    )


def get_transcript_workspace_fields(session_id: str) -> dict | None:
    """Read the typed workspace columns for a session (None if row missing)."""
    row = _get_conn().execute(
        "SELECT workspace_id, owner_user_id, visibility "
        "FROM transcript_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return dict(row) if row else None


def list_workspace_transcript_sessions(workspace_id: str) -> list[dict]:
    """List sessions belonging to a workspace, newest-first.

    Returns the same row shape as `list_transcript_sessions`. Phase 1.7
    layers the visibility check on top via `can_see`; this helper is
    the workspace-scoped fetch the meetings list endpoint will use.
    """
    rows = _get_conn().execute(
        "SELECT session_id, source, session_date, raw_diarization, metadata, "
        "derived, created_at, updated_at, workspace_id, owner_user_id, visibility "
        "FROM transcript_sessions WHERE workspace_id = ? "
        "ORDER BY session_date DESC, created_at DESC",
        (workspace_id,),
    ).fetchall()
    return [
        {
            "session_id": r["session_id"],
            "source": r["source"],
            "session_date": r["session_date"],
            "raw_diarization": json.loads(r["raw_diarization"]),
            "metadata": json.loads(r["metadata"]),
            "derived": json.loads(r["derived"]),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "workspace_id": r["workspace_id"],
            "owner_user_id": r["owner_user_id"],
            "visibility": r["visibility"],
        }
        for r in rows
    ]


def delete_transcript_session(session_id: str) -> None:
    """Hard-delete a session row. Only the `--force` replace path uses this;
    the normal write path is `save_transcript_session` (raw-write-once)."""
    _get_conn().execute(
        "DELETE FROM transcript_sessions WHERE session_id = ?",
        (session_id,),
    )
