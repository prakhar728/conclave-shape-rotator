# Transcript-refine — parked issues / deferred work

Loose threads surfaced during local testing. None block the editor working; each is
deferred with the user's awareness. Newest first.

## B — DB setup footguns (PARKED 2026-06-22)
Two traps that only bite a **fresh or custom-path** DB (not the default DB):
1. **Two env vars for the same DB.** `alembic/env.py:19` reads **`CONCLAVE_DB_URL`**;
   the app (`storage/sqlite.py`) reads **`CONCLAVE_DB_PATH`**. Point the app at a
   custom DB and run `alembic upgrade head` → alembic migrates a *different* file →
   app DB has no tables ("no such table: transcript_v2").
2. **Fresh-DB init order.** Schema is split: `storage.init_db()` makes the legacy
   tables, alembic makes the rest, and migration `0004` ALTERs a legacy table — so
   `alembic upgrade head` on a brand-new empty DB fails. README's bare
   `alembic upgrade head` step is wrong for a clean DB.
**Fix:** have alembic derive its URL from `CONCLAVE_DB_PATH` (single source of
truth) + a single ordered setup command (`init_db()` → alembic) + README update.

## Meeting view shows RAW, not the corrected v2 (OPEN — agreed worth doing)
After Approve, `/meeting/[id]`'s `TranscriptPanel` calls `GET /transcript` →
`to_transcript(session)` = **`raw_diarization`** (the immutable original). So your
corrections are invisible there — only the `/refine` editor shows them. The KB +
insights DO use the corrected v2; just the on-screen transcript doesn't.
**Fix:** post-approval, serve the corrected v2 (`store.v2_segments_or_raw`) as the
meeting transcript (new field or a switched source), so the loop closes visually.

## Speaker identity should branch on audio vs text (OPEN — needs a product call)
The meeting view's "tag a speaker" asks for name **+ email** → the VFTEE voiceprint +
consent-email flow. That only makes sense for **recorded audio**. For an **uploaded
transcript** (no voice) it's wrong — the editor's `assign-speaker` (plain text label,
no voiceprint/email) is the right path. `metadata.source` (`upload` vs `record`)
distinguishes them.
**Decision needed:** for uploads, is speaker naming *purely* a text label, or should
an uploaded "Speaker 1" still be linkable to a known person by name (no voiceprint)?
Then: hide the email/VFTEE tag UI on audio-less sessions.

## Done (for the ledger)
- **Editor swallowed write errors** → FIXED 2026-06-22: edit/tag/assign now surface a
  "couldn't save" banner + re-sync from the server (no silent optimistic-only state).
- **Editor needs dev-only NLP deps** (spaCy + `en_core_web_sm` + wordfreq) — documented
  in the README; run uvicorn from a venv that has them or detection silently no-ops.
