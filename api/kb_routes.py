"""KB HTTP surface — entities + obligations (Phase 3.5b C18/C19).

All routes: authenticated user (require_current_user) + workspace
membership (_require_member) + per-meeting can_user_see filtering.
Entities are global rows (ER merges across workspaces is impossible
because mentions carry session ids and sessions carry workspaces —
an entity only "appears" in a workspace through mentions in sessions
the caller can see; everything here is filtered through that lens).

Read-only router: no mutations, no LLM, nothing on the query path
but SQL — operator-blind table holds.
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from auth.session import require_current_user
from api.workspaces_routes import _require_member

router = APIRouter(prefix="/api/workspaces", tags=["kb"])


# ---------------------------------------------------------------------------
# Shared: visible sessions for caller in workspace
# ---------------------------------------------------------------------------

def _visible_session_ids(workspace_id: str, user: dict) -> list[str]:
    """Session ids in this workspace the caller may see (can_user_see)."""
    from api.transcripts_routes import can_user_see
    from transcripts import store as _store

    out: list[str] = []
    for s in _store.list_workspace_sessions(workspace_id):
        fields = _store.get_workspace_fields(s.session_id)
        if not fields or not fields.get("workspace_id"):
            continue  # defensive: don't leak half-bound sessions
        row = {"session_id": s.session_id, **fields}
        if can_user_see(user, row):
            out.append(s.session_id)
    return out


# ---------------------------------------------------------------------------
# C18 — entities
# ---------------------------------------------------------------------------

@router.get("/{workspace_id}/entities")
def list_entities(
    workspace_id: str,
    type: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    user: dict = Depends(require_current_user),
):
    """Entities mentioned in sessions the caller can see, by mention count."""
    _require_member(workspace_id, user["id"])
    sids = _visible_session_ids(workspace_id, user)
    if not sids:
        return {"entities": []}

    from storage.sqlite import _get_conn
    qs = ",".join("?" * len(sids))
    sql = (
        "SELECT e.id, e.type, e.canonical_name, e.props_json,"
        " COUNT(m.id) AS mention_count,"
        " COUNT(DISTINCT m.session_id) AS meeting_count"
        f" FROM entities e JOIN entity_mentions m ON m.entity_id = e.id"
        f" WHERE m.session_id IN ({qs})"
    )
    params: list = list(sids)
    if type:
        sql += " AND e.type = ?"
        params.append(type)
    sql += " GROUP BY e.id ORDER BY mention_count DESC, e.canonical_name LIMIT ?"
    params.append(limit)
    rows = _get_conn().execute(sql, params).fetchall()
    return {
        "entities": [
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
    }


@router.get("/{workspace_id}/entities/{name}")
def entity_detail(
    workspace_id: str,
    name: str,
    user: dict = Depends(require_current_user),
):
    """Entity detail: meetings (visible only), mention turns, related
    current obligations. ``name`` is the URL-encoded canonical name,
    matched case-insensitively across types (most-mentioned wins)."""
    _require_member(workspace_id, user["id"])
    sids = _visible_session_ids(workspace_id, user)
    if not sids:
        raise HTTPException(status_code=404, detail="Entity not found")

    from storage.sqlite import _get_conn
    conn = _get_conn()
    qs = ",".join("?" * len(sids))
    # Resolve name → entity, restricted to entities visible in this workspace.
    ent = conn.execute(
        "SELECT e.id, e.type, e.canonical_name, e.props_json,"
        " COUNT(m.id) AS mention_count"
        f" FROM entities e JOIN entity_mentions m ON m.entity_id = e.id"
        f" WHERE m.session_id IN ({qs})"
        " AND e.canonical_name = ? COLLATE NOCASE"
        " GROUP BY e.id ORDER BY mention_count DESC LIMIT 1",
        (*sids, name),
    ).fetchone()
    if ent is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    mentions = conn.execute(
        "SELECT session_id, turn_id, raw_text FROM entity_mentions"
        f" WHERE entity_id = ? AND session_id IN ({qs})"
        " ORDER BY session_id, turn_id",
        (ent["id"], *sids),
    ).fetchall()

    by_session: dict[str, dict] = {}
    from transcripts import store as _store
    for m in mentions:
        sid = m["session_id"]
        if sid not in by_session:
            sess = _store.load_session(sid)
            by_session[sid] = {
                "session_id": sid,
                "date": sess.metadata.date if sess else None,
                "summary": (sess.derived.summary if sess and sess.derived else None),
                "turn_ids": [],
            }
        if m["turn_id"] is not None:
            by_session[sid]["turn_ids"].append(m["turn_id"])

    from storage import kb_graph
    related = [
        o for o in kb_graph.current_obligations(session_ids=sids)
        if o.get("owner_entity_id") == ent["id"]
    ]

    return {
        "entity": {
            "id": ent["id"],
            "type": ent["type"],
            "canonical_name": ent["canonical_name"],
            "raw_mentions": (json.loads(ent["props_json"] or "{}").get("raw_mentions") or []),
            "mention_count": ent["mention_count"],
        },
        "meetings": sorted(
            by_session.values(), key=lambda d: d["date"] or "", reverse=True,
        ),
        "obligations": related,
    }


# ---------------------------------------------------------------------------
# C19 — obligations
# ---------------------------------------------------------------------------

@router.get("/{workspace_id}/obligations")
def list_obligations(
    workspace_id: str,
    type: Optional[str] = Query(default=None),
    owner_entity_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None, description="ISO date lower bound on ingested_at"),
    until: Optional[str] = Query(default=None, description="ISO date upper bound on ingested_at"),
    user: dict = Depends(require_current_user),
):
    """Current (valid_to IS NULL) obligations across visible sessions."""
    _require_member(workspace_id, user["id"])
    sids = _visible_session_ids(workspace_id, user)
    if not sids:
        return {"obligations": []}

    from storage import kb_graph
    rows = kb_graph.current_obligations(otype=type, session_ids=sids)
    if owner_entity_id:
        rows = [r for r in rows if r.get("owner_entity_id") == owner_entity_id]
    if status:
        rows = [r for r in rows if r.get("status_inferred") == status]
    if since:
        rows = [r for r in rows if (r.get("ingested_at") or "") >= since]
    if until:
        rows = [r for r in rows if (r.get("ingested_at") or "") <= until]
    rows.sort(key=lambda r: (-(r.get("importance") or 0), r.get("ingested_at") or ""))
    return {"obligations": rows}


# ---------------------------------------------------------------------------
# C28 — knowledge graph (3.5d)
# ---------------------------------------------------------------------------

#: Render caps (3.5d.13) — the filter panel lets users dig past these.
GRAPH_MAX_ENTITIES = 100
GRAPH_MAX_SPEAKERS = 50


@router.get("/{workspace_id}/graph")
def workspace_graph(
    workspace_id: str,
    as_of: Optional[str] = Query(default=None, description="ISO date — include meetings on/before"),
    types: Optional[str] = Query(default=None, description="comma-separated entity types"),
    min_mentions: int = Query(default=1, ge=1),
    user: dict = Depends(require_current_user),
):
    """Force-directed graph data: {nodes, edges}.

    Node kinds: meeting, entity, speaker. Edges: entity—meeting
    (weight = mention count in that meeting), speaker—meeting
    (weight = turn count). ``as_of`` is the bi-temporal lens applied at
    meeting granularity (meetings dated after as_of drop out, taking
    their edges with them); obligations/facts validity windows refine
    this further in v1.5 when facts land on the graph.

    Caps: top 100 entities / top 50 speakers by weight (3.5d.13).
    Computed per-request — corpus is small; cache when it isn't.
    """
    _require_member(workspace_id, user["id"])
    sids = _visible_session_ids(workspace_id, user)
    if not sids:
        return {"nodes": [], "edges": []}

    from transcripts import store as _store
    sessions = []
    for sid in sids:
        s = _store.load_session(sid)
        if s is None:
            continue
        if as_of and (s.metadata.date or "") > as_of:
            continue
        sessions.append(s)
    if not sessions:
        return {"nodes": [], "edges": []}
    kept_sids = [s.session_id for s in sessions]

    type_filter = None
    if types:
        type_filter = {t.strip() for t in types.split(",") if t.strip()}

    from storage.sqlite import _get_conn
    conn = _get_conn()
    qs = ",".join("?" * len(kept_sids))
    rows = conn.execute(
        "SELECT e.id, e.type, e.canonical_name, m.session_id,"
        " COUNT(m.id) AS cnt"
        f" FROM entities e JOIN entity_mentions m ON m.entity_id = e.id"
        f" WHERE m.session_id IN ({qs})"
        " GROUP BY e.id, m.session_id",
        kept_sids,
    ).fetchall()

    # entity totals for cap + min_mentions
    totals: dict[str, int] = {}
    meta: dict[str, dict] = {}
    per_meeting: dict[tuple[str, str], int] = {}
    for r in rows:
        if type_filter and r["type"] not in type_filter:
            continue
        totals[r["id"]] = totals.get(r["id"], 0) + r["cnt"]
        meta[r["id"]] = {"type": r["type"], "name": r["canonical_name"]}
        per_meeting[(r["id"], r["session_id"])] = r["cnt"]
    kept_entities = {
        eid for eid, total in sorted(
            totals.items(), key=lambda t: -t[1]
        )[:GRAPH_MAX_ENTITIES]
        if total >= min_mentions
    }

    from infra.speakers import aggregate_speakers
    speakers = aggregate_speakers(sessions)
    kept_speakers = dict(sorted(
        speakers.items(), key=lambda kv: -kv[1]["turn_count"],
    )[:GRAPH_MAX_SPEAKERS])

    nodes = []
    for s in sessions:
        nodes.append({
            "id": f"meeting:{s.session_id}",
            "kind": "meeting",
            "label": (s.derived.summary[:60] if s.derived and s.derived.summary
                      else s.session_id),
            "date": s.metadata.date,
        })
    for eid in kept_entities:
        nodes.append({
            "id": f"entity:{eid}",
            "kind": "entity",
            "label": meta[eid]["name"],
            "entity_type": meta[eid]["type"],
            "weight": totals[eid],
        })
    for key, rec in kept_speakers.items():
        nodes.append({
            "id": f"speaker:{key}",
            "kind": "speaker",
            "label": rec["name"],
            "weight": rec["turn_count"],
        })

    edges = []
    for (eid, sid), cnt in per_meeting.items():
        if eid in kept_entities and sid in kept_sids:
            edges.append({
                "source": f"entity:{eid}",
                "target": f"meeting:{sid}",
                "weight": cnt,
            })
    for key, rec in kept_speakers.items():
        for sid in rec["session_ids"]:
            if sid in kept_sids:
                edges.append({
                    "source": f"speaker:{key}",
                    "target": f"meeting:{sid}",
                    "weight": 1,
                })
    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# C23 — hybrid search (BM25 + dense, RRF-fused)
# ---------------------------------------------------------------------------

from pydantic import BaseModel, Field


class SearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=20, ge=1, le=200)


@router.post("/{workspace_id}/search")
def search_workspace(
    workspace_id: str,
    body: SearchBody,
    user: dict = Depends(require_current_user),
):
    """Hybrid chunk search: FTS5 BM25 + sqlite-vec dense, fused via RRF.

    Query path is LLM-free (operator-blind): one local nomic embedding
    of the query + two SQLite index scans + ~20 lines of fusion math.
    Dense degrades gracefully to BM25-only when the embedder is down.
    """
    _require_member(workspace_id, user["id"])
    sids = _visible_session_ids(workspace_id, user)
    if not sids:
        return {"results": []}

    from infra.rrf import rrf_fuse
    from storage import kb

    fetch_k = max(body.top_k * 3, 50)
    fts_hits = kb.fts_search_chunks(body.query, limit=fetch_k, session_ids=sids)

    vec_hits: list[dict] = []
    try:
        from transcripts.embed import embed_texts
        qvec = embed_texts([body.query], kind="query")[0]
        vec_hits = kb.vec_search_chunks(qvec, k=fetch_k, session_ids=sids)
    except Exception:  # noqa: BLE001 — embedder down → BM25-only
        pass

    fused = rrf_fuse([
        [h["chunk_id"] for h in fts_hits],
        [h["chunk_id"] for h in vec_hits],
    ])[: body.top_k]
    if not fused:
        return {"results": []}

    from storage.sqlite import _get_conn
    ids = [cid for cid, _ in fused]
    qs = ",".join("?" * len(ids))
    rows = _get_conn().execute(
        "SELECT id, session_id, turn_ids, text, context_header"
        f" FROM chunks WHERE id IN ({qs})",
        ids,
    ).fetchall()
    by_id = {r["id"]: r for r in rows}

    from transcripts import store as _store
    session_meta: dict[str, dict] = {}
    results = []
    for cid, score in fused:
        r = by_id.get(cid)
        if r is None:
            continue
        sid = r["session_id"]
        if sid not in session_meta:
            sess = _store.load_session(sid)
            session_meta[sid] = {
                "date": sess.metadata.date if sess else None,
                "summary": (sess.derived.summary if sess and sess.derived else None),
            }
        text = r["text"]
        results.append({
            "chunk_id": cid,
            "session_id": sid,
            "score": score,
            "snippet": text[:400] + ("…" if len(text) > 400 else ""),
            "context_header": r["context_header"] or None,
            "turn_ids": json.loads(r["turn_ids"] or "[]"),
            "meeting": {"session_id": sid, **session_meta[sid]},
        })
    return {"results": results}


@router.get("/{workspace_id}/obligations/{obligation_id}")
def obligation_detail(
    workspace_id: str,
    obligation_id: str,
    user: dict = Depends(require_current_user),
):
    _require_member(workspace_id, user["id"])
    sids = set(_visible_session_ids(workspace_id, user))

    from storage.sqlite import _get_conn
    from storage.kb_graph import _obligation_row
    row = _get_conn().execute(
        "SELECT id, session_id, turn_ids, type, description, source_quote,"
        " owner_entity_id, owner_raw_text, due_date_raw, status_inferred,"
        " valid_from, valid_to, superseded_by, importance, model_version,"
        " ingested_at FROM obligations WHERE id = ?",
        (obligation_id,),
    ).fetchone()
    if row is None or row["session_id"] not in sids:
        # 404 for both not-found and not-visible — don't leak existence.
        raise HTTPException(status_code=404, detail="Obligation not found")
    return {"obligation": _obligation_row(row)}
