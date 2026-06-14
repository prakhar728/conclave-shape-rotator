# Branch B — voiceprint_id persistence + name projection (P2)

**Repo:** Conclave · **Base:** `main` (`feat/consent-plane`) · **Autonomy:** agent-autonomous
(test-first) · **Depends on:** Contracts **C2** (consumes `/v1/diarize` `voiceprint_id`) + **C3**
(`resolved_speakers` schema). **Conclave-only — touches no FPM code.** Unblocks the whole feedback
loop and is on the critical path (B → P4 → P5).

## Goal
Stop dropping `voiceprint_id`. Persist it per segment so identity edits (P4) and redaction (P5) have
a stable key, and make the display name a pure read-time projection.

## Scope (files)
- `api/record_routes.py` — `merge_by_timestamp`: **keep `voiceprint_id`** on each merged segment
  (currently collapses to `{speaker, text, start, end}`). Make **"Speaker N" numbering deterministic
  by `voiceprint_id`** (not first-appearance) so live vs post passes don't diverge. **This is the
  only file branch A must stay out of — B owns it.**
- `transcripts/models.py` — `resolved_speakers[label] = {voiceprint_id, name, confidence}` per C3
  (mutable JSON; no SQL migration).
- ingest (`api/record_routes.py` / wherever `resolve_speakers` runs) — populate `resolved_speakers`
  with the `voiceprint_id` carried from FPM.
- `api/transcripts_routes.py` (read path) — project `voiceprint_id → name`; **keep the label string
  immutable as the join key**; **never rewrite `Signal.said_by`**.

## Things to be careful about
- **Two-keyspace discipline:** `voiceprint_id` lives in metadata; the **display label string stays
  the immutable join key** for already-enriched signals. Project names at read time; don't rewrite
  derived blobs.
- Deterministic numbering is what makes replace-safety work across the live→post swap.
- Pure consumer of C2 — if the FPM segment shape isn't there yet, gate/skip gracefully (don't crash
  the existing upload path).
- `raw_diarization`/`RawSegment` are immutable — put `voiceprint_id` in `resolved_speakers`, not on
  the raw segment.

## Test-gated steps (test first → green → atomic commit each)
1. **`merge_by_timestamp` preserves `voiceprint_id`** per segment. (Unit.)
2. **Deterministic numbering** — same identity input → same `Speaker N` labels across two runs. (Unit.)
3. **Ingest writes C3** — a recorded meeting's `resolved_speakers[label]` carries
   `{voiceprint_id, name, confidence}`. (Integration.)
4. **Read path projects** `voiceprint_id → name`; `said_by` unchanged. (Unit/integration.)
5. **Regression:** existing paste/upload ingest still green.

## Definition of done
`voiceprint_id` persisted per C3 and projected at read time; numbering deterministic; upload
regression green; no FPM changes.
