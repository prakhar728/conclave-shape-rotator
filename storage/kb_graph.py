"""Entity/obligation graph storage + ingest metrics (3.5b C17).

Write/read layer over migration 0007's tables + 0008's ingest_metrics.
Same seam as storage/kb.py (``storage.sqlite._get_conn``). All writes
parameterized; ids are uuid4 hex; "current" rows are valid_to IS NULL.

Bi-temporal execution of C16 decisions lives here (execute_upsert) so
the LLM-decision module stays pure and every superseded_by write goes
through one audited code path.
"""
from __future__ import annotations

import json
import math
import uuid
from typing import Any, Iterable, Optional

from storage.sqlite import _get_conn, _now
from transcripts.embed import deserialize_f32, serialize_f32


def _new_id() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Entities + mentions
# ---------------------------------------------------------------------------

def get_entity(entity_id: str) -> Optional[dict]:
    row = _get_conn().execute(
        "SELECT id, type, canonical_name, props_json, created_at"
        " FROM entities WHERE id = ?", (entity_id,)
    ).fetchone()
    return _entity_row(row) if row else None


def find_entity(etype: str, canonical_name: str) -> Optional[dict]:
    row = _get_conn().execute(
        "SELECT id, type, canonical_name, props_json, created_at FROM entities"
        " WHERE type = ? AND canonical_name = ? COLLATE NOCASE",
        (etype, canonical_name),
    ).fetchone()
    return _entity_row(row) if row else None


# --- Derived 3-category view (no stored-type migration; see OI-7 / EVAL.md E1) --
#: Coarse category derived from the fine 5-value `type`. Used for resolution
#: pooling + UI grouping. A true 3-type column is deferred debt.
_CATEGORY_TYPES = {
    "person": ("person",),
    "affiliation": ("company",),
    "tech": ("tool", "project", "topic"),
}


def category_of(etype: str) -> str:
    """person→person, company→affiliation, {tool,project,topic}→tech."""
    if etype == "person":
        return "person"
    if etype == "company":
        return "affiliation"
    return "tech"


def types_in_category(category: str) -> tuple[str, ...]:
    return _CATEGORY_TYPES.get(category, ("tool", "project", "topic"))


def insert_entity(
    etype: str, canonical_name: str, raw_mentions: list[str],
    *, definition: Optional[str] = None, role: Optional[str] = None,
) -> str:
    eid = _new_id()
    props: dict = {"raw_mentions": raw_mentions}
    if definition:
        props["definition"] = definition
    if role:
        props["role"] = role
    _get_conn().execute(
        "INSERT INTO entities (id, type, canonical_name, props_json, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (eid, etype, canonical_name, json.dumps(props), _now()),
    )
    return eid


def merge_mentions_into_entity(entity_id: str, raw_mentions: list[str]) -> None:
    """Union new surface forms into props_json.raw_mentions."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT props_json FROM entities WHERE id = ?", (entity_id,)
    ).fetchone()
    if row is None:
        return
    props = json.loads(row["props_json"] or "{}")
    have = props.get("raw_mentions") or []
    for m in raw_mentions:
        if m not in have:
            have.append(m)
    props["raw_mentions"] = have
    conn.execute(
        "UPDATE entities SET props_json = ? WHERE id = ?",
        (json.dumps(props), entity_id),
    )


def add_mentions(
    entity_id: str, session_id: str, turn_ids: Iterable[int], raw_text: str,
) -> int:
    conn = _get_conn()
    now = _now()
    n = 0
    for tid in turn_ids:
        conn.execute(
            "INSERT INTO entity_mentions"
            " (id, entity_id, session_id, turn_id, raw_text, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (_new_id(), entity_id, session_id, int(tid), raw_text, now),
        )
        n += 1
    return n


def entities_for_er(etype: str, *, model_id: str) -> list[dict]:
    """ER candidate pool: all entities in the candidate's CATEGORY (person /
    tech / affiliation) + cached definition-embeddings. Category-pooling lets a
    `tool` and a `project` that name the same tech resolve together (fixes the
    old cross-type under-merge). Each dict also carries `definition` (from
    props) so the resolver + LLM tiebreak can use it as context."""
    conn = _get_conn()
    cats = types_in_category(category_of(etype))
    placeholders = ",".join("?" * len(cats))
    rows = conn.execute(
        "SELECT e.id, e.type, e.canonical_name, e.props_json, emb.vec AS vec"
        " FROM entities e"
        " LEFT JOIN embeddings emb ON emb.source_kind = 'entity'"
        "   AND emb.source_id = e.id AND emb.model_id = ?"
        f" WHERE e.type IN ({placeholders})",
        (model_id, *cats),
    ).fetchall()
    out = []
    for r in rows:
        d = _entity_row(r)
        d["embedding"] = deserialize_f32(r["vec"]) if r["vec"] else None
        d["definition"] = (d.get("props") or {}).get("definition")
        out.append(d)
    return out


def save_source_embedding(
    source_kind: str, source_id: str, vec: list[float], *, model_id: str,
) -> None:
    _get_conn().execute(
        """
        INSERT INTO embeddings (id, source_kind, source_id, model_id, dim, vec, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_kind, source_id, model_id) DO UPDATE SET
            dim = excluded.dim, vec = excluded.vec, created_at = excluded.created_at
        """,
        (f"emb:{source_kind}:{source_id}:{model_id}", source_kind, source_id,
         model_id, len(vec), serialize_f32(vec), _now()),
    )


def _entity_row(row: Any) -> dict:
    return {
        "id": row["id"],
        "type": row["type"],
        "canonical_name": row["canonical_name"],
        "props": json.loads(row["props_json"] or "{}"),
        "created_at": row["created_at"] if "created_at" in row.keys() else None,
    }


# ---------------------------------------------------------------------------
# Obligations (bi-temporal)
# ---------------------------------------------------------------------------

def insert_obligation(row: dict, *, session_id: str, model_version: str) -> str:
    oid = _new_id()
    now = _now()
    _get_conn().execute(
        """
        INSERT INTO obligations
            (id, session_id, turn_ids, type, description, source_quote,
             owner_entity_id, owner_raw_text, due_date_raw, status_inferred,
             valid_from, importance, model_version, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            oid, session_id, json.dumps(row.get("turn_ids") or []),
            row["type"], row["description"], row.get("source_quote") or "",
            row.get("owner_entity_id"), row.get("owner_raw_text"),
            row.get("due_date_raw"), row.get("status_inferred") or "unclear",
            now, row.get("importance"), model_version, now,
        ),
    )
    return oid


def invalidate_obligation(
    obligation_id: str, *, superseded_by: Optional[str] = None,
) -> None:
    """Bi-temporal soft-invalidate. NEVER a hard delete."""
    _get_conn().execute(
        "UPDATE obligations SET valid_to = ?, superseded_by = ?"
        " WHERE id = ? AND valid_to IS NULL",
        (_now(), superseded_by, obligation_id),
    )


def current_obligations(
    *, otype: Optional[str] = None, session_ids: Optional[Iterable[str]] = None,
) -> list[dict]:
    sql = (
        "SELECT id, session_id, turn_ids, type, description, source_quote,"
        " owner_entity_id, owner_raw_text, due_date_raw, status_inferred,"
        " valid_from, valid_to, superseded_by, importance, model_version,"
        " ingested_at FROM obligations WHERE valid_to IS NULL"
    )
    params: list = []
    if otype:
        sql += " AND type = ?"
        params.append(otype)
    if session_ids is not None:
        ids = list(session_ids)
        if not ids:
            return []
        sql += f" AND session_id IN ({','.join('?' * len(ids))})"
        params.extend(ids)
    rows = _get_conn().execute(sql, params).fetchall()
    return [_obligation_row(r) for r in rows]


def entities_for_sessions(
    session_ids: Iterable[str], *, etype: Optional[str] = None, limit: int = 100,
) -> list[dict]:
    """Entities mentioned in the given sessions, ranked by mention count.

    Single source of truth for the workspace "entities" projection (the
    query api.kb_routes.list_entities builds inline; ScopedCorpus reuses
    this so the two can't drift). Returns ``[]`` for an empty session set so
    no caller can accidentally trigger an unscoped, permission-blind scan.
    """
    ids = list(session_ids)
    if not ids:
        return []
    qs = ",".join("?" * len(ids))
    sql = (
        "SELECT e.id, e.type, e.canonical_name, e.props_json,"
        " COUNT(m.id) AS mention_count,"
        " COUNT(DISTINCT m.session_id) AS meeting_count"
        " FROM entities e JOIN entity_mentions m ON m.entity_id = e.id"
        f" WHERE m.session_id IN ({qs})"
    )
    params: list = list(ids)
    if etype:
        sql += " AND e.type = ?"
        params.append(etype)
    sql += " GROUP BY e.id ORDER BY mention_count DESC, e.canonical_name LIMIT ?"
    params.append(limit)
    rows = _get_conn().execute(sql, params).fetchall()
    return [
        {
            "id": r["id"],
            "type": r["type"],
            "canonical_name": r["canonical_name"],
            "raw_mentions": (json.loads(r["props_json"] or "{}").get("raw_mentions") or []),
            "mention_count": r["mention_count"],
            "meeting_count": r["meeting_count"],
        }
        for r in rows
    ]


def similar_obligations(
    query_vec: list[float], *, otype: str, k: int = 5, model_id: str,
) -> list[dict]:
    """Top-K current same-type obligations by cosine over stored embeddings.

    Python cosine over the (small) current set — obligations aren't in
    sqlite-vec; at v1 scale a linear scan is microseconds and avoids a
    second ANN index to keep in sync with bi-temporal invalidation.
    """
    conn = _get_conn()
    rows = conn.execute(
        "SELECT o.id, o.session_id, o.turn_ids, o.type, o.description,"
        " o.source_quote, o.owner_entity_id, o.owner_raw_text, o.due_date_raw,"
        " o.status_inferred, o.valid_from, o.valid_to, o.superseded_by,"
        " o.importance, o.model_version, o.ingested_at, emb.vec AS vec"
        " FROM obligations o"
        " JOIN embeddings emb ON emb.source_kind = 'obligation'"
        "   AND emb.source_id = o.id AND emb.model_id = ?"
        " WHERE o.valid_to IS NULL AND o.type = ?",
        (model_id, otype),
    ).fetchall()
    scored = []
    qn = math.sqrt(sum(x * x for x in query_vec)) or 1.0
    for r in rows:
        vec = deserialize_f32(r["vec"])
        num = sum(a * b for a, b in zip(query_vec, vec))
        dn = math.sqrt(sum(x * x for x in vec)) or 1.0
        scored.append((num / (qn * dn), r))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [dict(_obligation_row(r), similarity=s) for s, r in scored[:k]]


def _obligation_row(row: Any) -> dict:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "turn_ids": json.loads(row["turn_ids"] or "[]"),
        "type": row["type"],
        "description": row["description"],
        "source_quote": row["source_quote"],
        "owner_entity_id": row["owner_entity_id"],
        "owner_raw_text": row["owner_raw_text"],
        "due_date_raw": row["due_date_raw"],
        "status_inferred": row["status_inferred"],
        "valid_from": row["valid_from"],
        "valid_to": row["valid_to"],
        "superseded_by": row["superseded_by"],
        "importance": row["importance"],
        "model_version": row["model_version"],
        "ingested_at": row["ingested_at"],
    }


# ---------------------------------------------------------------------------
# Upsert execution (C16 decisions → bi-temporal writes)
# ---------------------------------------------------------------------------

def execute_upsert(
    decision: Any, new_row: dict, *, session_id: str, model_version: str,
) -> Optional[str]:
    """Apply an UpsertDecision. Returns the inserted obligation id (or None).

    ADD    → insert
    UPDATE → insert new; old.valid_to = now, old.superseded_by = new id
    DELETE → invalidate old; new row NOT inserted (the new info's only
             content is that the old row stopped being true)
    NOOP   → nothing
    """
    action = decision.action
    if action == "NOOP":
        return None
    if action == "DELETE":
        if decision.target_id:
            invalidate_obligation(decision.target_id)
        return None
    new_id = insert_obligation(new_row, session_id=session_id, model_version=model_version)
    if action == "UPDATE" and decision.target_id:
        invalidate_obligation(decision.target_id, superseded_by=new_id)
    return new_id


# ---------------------------------------------------------------------------
# Ingest metrics
# ---------------------------------------------------------------------------

def record_metric(
    session_id: str, stage: str, *, llm_calls: int = 0, ms: int = 0,
    items_in: Optional[int] = None, items_out: Optional[int] = None,
) -> None:
    _get_conn().execute(
        "INSERT INTO ingest_metrics"
        " (session_id, stage, llm_call_count, ms_elapsed, items_in, items_out, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session_id, stage, llm_calls, ms, items_in, items_out, _now()),
    )
