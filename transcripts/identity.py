"""Mock name → Cohort-OS ``record_id`` linkage — the identity seam.

`IMPLEMENTATION_PLAN.md` §G2 / §H C5. **This is the single chokepoint** for
name→id resolution; never scatter that logic elsewhere. The real lookup
(`cohort-surface.json` / swf-node `/graph` / voiceprint UUIDs) swaps in at
``resolve_identity`` later (§K #2) — same signature, same return shape.

`MOCK_DIRECTORY` is built at import time from
``external/shape-rotator-os/cohort-data/people/*.md`` frontmatter — the
**real** cohort roster, looked up by simple name equality instead of an
API call. Phase-1 demos therefore show real ``record_id``s alongside real
names from day one. Failures are **non-fatal**: a missing directory → an
empty ``MOCK_DIRECTORY`` + a warning, never a crash (§G2 critical note).

What ``resolve_identity`` handles, from the real transcript labels:
- ``"Shaw Walters"`` → exact full-name match.
- ``"Shaw"`` → unique-first-name shortcut. (When two cohort members share a
  first name, e.g. ``"Andrew"``, no shortcut is added — the caller must use
  the full name or a parenthetical alias to disambiguate. A wrong link is
  worse than no link.)
- ``"Alex (flashbots?)"`` → parenthetical stripped on the lookup side; the
  verbatim label stays on ``RawSegment.speaker``.
- ``"Matt Van Ommeren (quasimatt)"`` in the roster → both the full name
  *and* ``"quasimatt"`` resolve to the same ``record_id``.
- ``"Speaker N"`` / ``"Unknown Speaker"`` → return ``None`` (correct, not
  a bug — the diarizer literally doesn't know who that is).

Deterministic, no LLM, no network — safe to run in any ingest path.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from transcripts import store
from transcripts.models import Session

log = logging.getLogger(__name__)


_PARENS_RE = re.compile(r"\s*\([^)]*\)")
_ANON_RE = re.compile(r"^(speaker\s+\d+|unknown\s+speaker)$", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


def _default_people_dir() -> Path:
    """Resolve the cohort-data path from the repo root.

    This file lives at ``transcripts/identity.py``; the cohort-data tree
    sits beside it at ``external/shape-rotator-os/cohort-data/people``.
    """
    return Path(__file__).resolve().parent.parent / "external" / "shape-rotator-os" / "cohort-data" / "people"


def _normalize_name(s: str) -> str:
    """Lowercase + collapse whitespace + strip parentheticals.

    ``"Alex (flashbots?)"`` → ``"alex"``. The parenthetical-strip is the
    load-bearing trick (§G2 critical note): without it, every label with
    a department/team annotation misses the lookup.
    """
    if not s:
        return ""
    n = _PARENS_RE.sub(" ", s)
    n = _WS_RE.sub(" ", n).strip().lower()
    return n


def _is_anonymous(name: str) -> bool:
    return bool(_ANON_RE.match(name.strip()))


def _load_mock_directory(people_dir: Optional[Path] = None) -> dict[str, str]:
    """Walk the cohort roster → ``{normalized_lookup_key: record_id}``.

    Three kinds of keys per person:
      1. Full normalized name (always).
      2. Parenthetical alias inside the ``name:`` field (e.g. ``"Matt Van
         Ommeren (quasimatt)"`` adds ``"quasimatt"``).
      3. First name **only when unique** across the cohort.
    """
    import yaml  # local import — keeps module-load cost off the cold path

    pdir = people_dir or _default_people_dir()
    if not pdir.is_dir():
        log.warning("identity: cohort people directory not found at %s — "
                    "MOCK_DIRECTORY will be empty; speakers will not resolve.", pdir)
        return {}

    # First pass: collect every person's record_id, full normalized name, and
    # parenthetical alias if present. We need the full pass before deciding
    # which first names are unique.
    entries: list[tuple[str, str, Optional[str]]] = []  # (record_id, full_norm, alias_norm)
    for fp in sorted(pdir.glob("*.md")):
        try:
            text = fp.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning("identity: cannot read %s (%s); skipping", fp, exc)
            continue
        # Parse only the YAML frontmatter block (between leading `---` fences).
        if not text.startswith("---"):
            continue
        end = text.find("\n---", 3)
        if end < 0:
            continue
        try:
            front = yaml.safe_load(text[3:end]) or {}
        except yaml.YAMLError as exc:
            log.warning("identity: bad frontmatter in %s (%s); skipping", fp, exc)
            continue
        rid = front.get("record_id")
        raw_name = front.get("name")
        if not rid or not raw_name:
            continue
        full = _normalize_name(str(raw_name))
        alias = None
        m = re.search(r"\(([^)]+)\)", str(raw_name))
        if m:
            alias = _normalize_name(m.group(1))
        entries.append((str(rid), full, alias))

    directory: dict[str, str] = {}

    # Pass 2a: full names + aliases. Collisions log a warning; first writer wins.
    for rid, full, alias in entries:
        if full:
            if full in directory and directory[full] != rid:
                log.warning("identity: name collision %r maps to both %s and %s; keeping %s",
                            full, directory[full], rid, directory[full])
            else:
                directory.setdefault(full, rid)
        if alias and alias != full:
            if alias in directory and directory[alias] != rid:
                log.warning("identity: alias collision %r (%s vs %s); keeping first",
                            alias, directory[alias], rid)
            else:
                directory.setdefault(alias, rid)

    # Pass 2b: first-name shortcut — only added when unique across the cohort.
    first_counts: dict[str, list[str]] = {}
    for rid, full, _ in entries:
        if not full:
            continue
        first = full.split(" ", 1)[0]
        if first == full:
            continue  # mononym already covered above
        first_counts.setdefault(first, []).append(rid)
    for first, rids in first_counts.items():
        # Don't shadow an existing entry (e.g. a person actually named just "Mike").
        if first in directory:
            continue
        if len(set(rids)) == 1:
            directory[first] = rids[0]

    return directory


# Populated at module import — one round-trip across ~50 markdown files,
# trivial cost. Re-import after the directory changes to refresh.
MOCK_DIRECTORY: dict[str, str] = _load_mock_directory()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_identity(name: str) -> Optional[str]:
    """Speaker label → ``record_id``, or ``None`` if unresolved.

    The **only** name→id function in the codebase. The Phase-2 real lookup
    swaps the body of this function with the same signature.
    """
    if not name or _is_anonymous(name):
        return None
    key = _normalize_name(name)
    if not key:
        return None
    return MOCK_DIRECTORY.get(key)


def resolve_speakers(session: Session) -> dict[str, dict]:
    """Walk a session's raw labels → ``{label: {record_id, name, mock: True}}``.

    Unresolved labels are **omitted** (rather than mapped to ``None``) so a
    consumer can iterate the dict and trust every entry has a record_id.
    The original verbatim labels on ``raw_diarization`` are not touched.
    """
    resolved: dict[str, dict] = {}
    seen: set[str] = set()
    for seg in session.raw_diarization:
        label = seg.speaker
        if label in seen:
            continue
        seen.add(label)
        rid = resolve_identity(label)
        if rid:
            resolved[label] = {"record_id": rid, "name": label, "mock": True}
    return resolved


def link_identities(*, session_id: Optional[str] = None) -> int:
    """Re-run resolution over stored sessions and persist updated metadata.

    Called from the ``transcripts link`` CLI subcommand. Use this when the
    roster grows or when transcripts were ingested before a speaker was in
    the directory. Returns the number of sessions whose
    ``resolved_speakers`` actually changed.
    """
    changed = 0
    sessions: list[Session]
    if session_id:
        s = store.load_session(session_id)
        sessions = [s] if s else []
    else:
        sessions = store.list_sessions()
    for s in sessions:
        new = resolve_speakers(s)
        if new != s.metadata.resolved_speakers:
            md = s.metadata.model_copy(update={"resolved_speakers": new})
            store.set_metadata(s.session_id, md)
            changed += 1
    return changed
