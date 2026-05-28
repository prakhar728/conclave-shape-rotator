"""Batch ingest — provided transcript files → stored sessions (raw, no LLM).

Phase 1's no-LLM milestone (`IMPLEMENTATION_PLAN.md` §G9 / §H C4):

    file/dir → sources.read_file → parse.build_session → store.save_session

`derived` is left empty on insert; enrichment runs later via
`enrich_pending`. A credit/network outage therefore cannot lose ingested
data — that's the whole point of decoupling ingest from enrich.

This module is **deterministic and never constructs an LLM**. C5 will plug
identity resolution in between `build_session` and `save_session`; the
contract here is stable across that change.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from transcripts import store, sources
from transcripts.identity import resolve_speakers
from transcripts.parse import build_session


# Files we know how to ingest. JSON kept for the VoxTerm-fixture path that
# `sources.read_obj` already understands.
_TRANSCRIPT_SUFFIXES = {".txt", ".json"}


@dataclass
class IngestReport:
    stored: int = 0
    skipped: int = 0  # idempotent: session_id already present with raw
    replaced: int = 0  # --force path
    failed: list[tuple[str, str]] = field(default_factory=list)  # (path, error)


def ingest_path(
    path: os.PathLike | str,
    *,
    force: bool = False,
    dry_run: bool = False,
    tags: Optional[list[str]] = None,
) -> IngestReport:
    """Ingest a file or every transcript file under a directory.

    Idempotent by `session_id`: re-ingesting the same file is a no-op on
    raw (the storage layer is raw-write-once). `force=True` routes through
    `store.replace_session` (delete + save) so a corrected transcript can
    replace its predecessor in place.
    """
    report = IngestReport()
    for fp in _iter_files(path):
        try:
            ni = sources.read_file(fp)
            if not ni.segments:
                # Empty parse (e.g. the "Notes" file that isn't Otter-shaped) —
                # surface as failed so the caller knows, don't pollute the store.
                report.failed.append((str(fp), "no segments parsed"))
                continue
            session = build_session(ni, tags=tags)
            # C5: mock identity linkage. Deterministic, no LLM, no network.
            # Unresolved labels (Speaker N, guests not in the roster) stay out
            # of resolved_speakers — see identity.resolve_speakers.
            session.metadata.resolved_speakers = resolve_speakers(session)
            if dry_run:
                report.stored += 1
                continue
            existing = store.load_session(session.session_id)
            if existing is None:
                store.save_session(session)
                report.stored += 1
            elif force:
                store.replace_session(session)
                report.replaced += 1
            else:
                # Raw-write-once: re-saving is harmless (storage layer keeps
                # raw, updates metadata/derived only) — but for ingest's
                # contract "raw unchanged" we just skip.
                report.skipped += 1
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the batch
            report.failed.append((str(fp), f"{type(exc).__name__}: {exc}"))
    return report


def _iter_files(path: os.PathLike | str) -> Iterable[Path]:
    """Yield candidate transcript files under a path (file or directory)."""
    p = Path(path)
    if p.is_file():
        yield p
        return
    if not p.is_dir():
        raise FileNotFoundError(p)
    for fp in sorted(p.iterdir()):
        if fp.is_file() and fp.suffix.lower() in _TRANSCRIPT_SUFFIXES:
            yield fp
