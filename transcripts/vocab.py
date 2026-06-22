"""Per-user vocab — the Part 1 dictionary (docs/plans/transcript-refine.md §12 #2, §15).

A hashmap `normalized-surface → entity record`, scoped per user. `get`/`put` are
the only access seam; suggestions + candidate-state lookup ride on top. Kept
separate from the global `entities` graph so Part 1 stays per-user and decoupled.
"""
from __future__ import annotations

import re
from typing import Optional

from storage import sqlite
from transcripts.models import VocabEntry

_WS = re.compile(r"\s+")


def normalize(surface: str) -> str:
    """Casefold + collapse internal whitespace → the O(1) lookup key.

    So "DStack Protocol", "dstack protocol", and "  dstack   protocol " all map
    to the same key.
    """
    return _WS.sub(" ", surface.strip()).casefold()


def put(
    user_id: str,
    surface: str,
    *,
    is_entity: bool = True,
    type: Optional[str] = None,
    canonical_id: Optional[str] = None,
    provenance: str = "user",
) -> VocabEntry:
    """Upsert a vocab entry for a user. Last-write-wins on (user, normalized
    surface) — retagging updates the single entry, never duplicates it."""
    norm = normalize(surface)
    sqlite.upsert_vocab(user_id, norm, is_entity, type, canonical_id, provenance)
    return VocabEntry(
        user_id=user_id, surface_norm=norm, is_entity=is_entity,
        type=type, canonical_id=canonical_id, provenance=provenance,
    )


def get(user_id: str, surface: str) -> Optional[VocabEntry]:
    row = sqlite.get_vocab(user_id, normalize(surface))
    return _to_entry(row) if row else None


def list_for_user(user_id: str) -> list[VocabEntry]:
    return [_to_entry(r) for r in sqlite.list_vocab(user_id)]


def _to_entry(row: dict) -> VocabEntry:
    return VocabEntry(
        user_id=row["user_id"],
        surface_norm=row["surface_norm"],
        is_entity=bool(row["is_entity"]),
        type=row["type"],
        canonical_id=row["canonical_id"],
        provenance=row["provenance"],
    )
