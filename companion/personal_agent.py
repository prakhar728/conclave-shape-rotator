"""Personal memory — a permission-scoped lens over the KB for one user.

A :class:`PersonalMemory` binds to ``(user, workspace)`` and answers
questions using ONLY the sessions that user is permitted to see. The
visible set is computed once, via the canonical resolver
``api.kb_routes._visible_session_ids`` — the *same* source of truth the
HTTP routes use — so the agent can never drift from route permissions.

This is the property that makes the Phase-3 collaboration matcher safe:
each person is represented by an agent that is *structurally* unable to
read beyond their scope, so cross-person leakage is impossible by
construction rather than filtered out after the fact. Every accessor here
is scoped to ``self.session_ids`` and nothing ever queries outside it
(with a defense-in-depth recheck on hydrated rows).

v1 is a read-only accessor (search / entities / obligations / profile),
NOT an LLM agent loop. Scope is ACCESS scope — everything the user may
read — which is purely auth-based (``user.id`` / ``email``) and needs no
speaker↔user identity resolution (that is deferred; a Phase-3 concern).
"""
from __future__ import annotations

from typing import Optional


class PersonalMemory:
    """One user's permission-bounded view of the knowledge base."""

    def __init__(
        self,
        user: dict,
        workspace_id: str,
        *,
        session_ids: Optional[list[str]] = None,
    ) -> None:
        self.user = user
        self.workspace_id = workspace_id
        if session_ids is None:
            # Reuse — not re-implement — the canonical visibility resolver so
            # permissions can never diverge from the API routes.
            from api.kb_routes import _visible_session_ids

            session_ids = _visible_session_ids(workspace_id, user)
        #: The permission boundary. Every method is scoped to exactly this
        #: set of session ids; nothing in this class reads outside it.
        self.session_ids: list[str] = list(session_ids)
        self._scope = set(self.session_ids)

    def __repr__(self) -> str:
        who = self.user.get("email") or self.user.get("id")
        return (
            f"PersonalMemory(user={who!r}, workspace={self.workspace_id!r}, "
            f"sessions={len(self.session_ids)})"
        )

    @property
    def has_scope(self) -> bool:
        return bool(self.session_ids)

    # -- retrieval --------------------------------------------------------

    def search(self, query: str, *, top_k: int = 10) -> list[dict]:
        """Hybrid (FTS5 + dense, RRF) chunk search within this person's scope.

        Degrades to FTS-only when the embedder is down — same contract as the
        ``/search`` route. Returns ``[{chunk_id, session_id, text, score}]``.
        """
        if not self.session_ids:
            return []
        from infra.rrf import rrf_fuse
        from storage import kb

        fetch = max(top_k * 3, 50)
        fts = kb.fts_search_chunks(query, limit=fetch, session_ids=self.session_ids)
        vec: list[dict] = []
        try:
            from transcripts.embed import embed_texts

            qvec = embed_texts([query], kind="query")[0]
            vec = kb.vec_search_chunks(qvec, k=fetch, session_ids=self.session_ids)
        except Exception:  # noqa: BLE001 — embedder down → FTS-only, same as route
            pass

        fused = rrf_fuse(
            [[h["chunk_id"] for h in fts], [h["chunk_id"] for h in vec]]
        )[:top_k]
        if not fused:
            return []
        return self._hydrate_chunks(fused)

    def _hydrate_chunks(self, fused: list[tuple[str, float]]) -> list[dict]:
        from storage.sqlite import _get_conn

        ids = [cid for cid, _ in fused]
        qs = ",".join("?" * len(ids))
        rows = {
            r["id"]: r
            for r in _get_conn()
            .execute(
                f"SELECT id, session_id, text FROM chunks WHERE id IN ({qs})", ids
            )
            .fetchall()
        }
        out: list[dict] = []
        for cid, score in fused:
            r = rows.get(cid)
            if r is None:
                continue
            # Defense in depth: never surface a chunk outside scope, even if a
            # fusion input somehow slipped one through.
            if r["session_id"] not in self._scope:
                continue
            out.append(
                {
                    "chunk_id": cid,
                    "session_id": r["session_id"],
                    "text": r["text"],
                    "score": score,
                }
            )
        return out

    # -- knowledge --------------------------------------------------------

    def entities(self, *, type: Optional[str] = None, limit: int = 100) -> list[dict]:
        """Entities the person can see, ranked by mention count."""
        from storage import kb_graph

        return kb_graph.entities_for_sessions(
            self.session_ids, etype=type, limit=limit
        )

    def obligations(
        self, *, type: Optional[str] = None, status: Optional[str] = None
    ) -> list[dict]:
        """Current obligations the person can see, importance-ranked."""
        from storage import kb_graph

        rows = kb_graph.current_obligations(otype=type, session_ids=self.session_ids)
        if status:
            rows = [r for r in rows if r.get("status_inferred") == status]
        rows.sort(key=lambda r: (-(r.get("importance") or 0), r.get("ingested_at") or ""))
        return rows

    # -- profile (Phase-3 substrate) -------------------------------------

    def profile(self, *, top_entities: int = 20, top_obligations: int = 20) -> dict:
        """A compact, scope-bounded portrait of what this person knows.

        This is the input the Phase-3 collaboration matcher will consume.
        Built ONLY from in-scope data, so it inherits the permission boundary
        — a profile can never carry information the person couldn't read.
        """
        ents = self.entities(limit=top_entities)
        obs = self.obligations()
        counts: dict[str, int] = {}
        for o in obs:
            counts[o["type"]] = counts.get(o["type"], 0) + 1
        return {
            "user_id": self.user.get("id"),
            "email": self.user.get("email"),
            "workspace_id": self.workspace_id,
            "session_count": len(self.session_ids),
            "top_entities": ents,
            "obligation_counts": counts,
            "top_obligations": obs[:top_obligations],
        }


def personal_memory(
    user: dict, workspace_id: str, *, session_ids: Optional[list[str]] = None
) -> PersonalMemory:
    """Convenience factory for :class:`PersonalMemory`."""
    return PersonalMemory(user, workspace_id, session_ids=session_ids)
