"""Suggestion engine for the editor (docs/plans/transcript-refine.md §6, §7).

Speaker suggestions come ONLY from trusted, identity-connected sources — WARM
(people already identified by voiceprint / VFTEE in this workspace) ranked ahead of
COLD (this meeting's invitees). We deliberately do NOT mine names out of the raw
transcript text (noisy + premature — same principle as OOV-only word detection). On
an empty account with no invitees, suggestions are legitimately empty. Vocab
suggestions: per-user autocomplete over the dictionary.
"""
from __future__ import annotations

from transcripts import store, vocab


def speaker_suggestions(session_id: str) -> list[str]:
    session = store.load_session(session_id)
    if session is None:
        return []
    fields = store.get_workspace_fields(session_id) or {}
    wsid = fields.get("workspace_id")
    warm = _warm_names(wsid, session_id) if wsid else []  # workspace voiceprints / VFTEE
    cold = list(session.metadata.participants or [])      # this meeting's invitees
    return _dedupe_ranked(warm, cold)


def vocab_suggestions(user_id: str, prefix: str = "", *, limit: int = 10) -> list[str]:
    """Per-user autocomplete: surfaces from the vocab whose normalized form starts
    with `prefix` (case-insensitive). Empty prefix → all (capped)."""
    p = prefix.strip().casefold()
    out = [
        e.surface_norm for e in vocab.list_for_user(user_id)
        if not p or e.surface_norm.startswith(p)
    ]
    return sorted(out)[:limit]


def _warm_names(wsid: str, exclude_session: str) -> list[str]:
    """Confirmed voiceprint names across the workspace's other sessions."""
    out: list[str] = []
    for s in store.list_workspace_sessions(wsid):
        if s.session_id == exclude_session:
            continue
        for entry in (s.metadata.resolved_speakers or {}).values():
            if isinstance(entry, dict) and entry.get("name"):
                out.append(entry["name"])
    return out


def _dedupe_ranked(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for g in groups:
        for n in g:
            k = (n or "").strip().casefold()
            if k and k not in seen:
                seen.add(k)
                out.append(n)
    return out
