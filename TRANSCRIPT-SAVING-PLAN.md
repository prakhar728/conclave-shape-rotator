# Transcript Saving & Sharing — Build Plan

Branch: `feat/transcript-saving` (worktree off `main`)
Status: PLAN — not yet implemented (no coding done)

## Goal

Anyone who invites the bot to their meeting gets their transcription by default
(already true). On top of that:

1. Owners can **share** a meeting with another person by email at different
   **permission levels** (summary-only vs summary + full transcript).
2. Owners can set **auto-delete (retention)** on their transcripts, with an
   account-wide default plus a per-meeting override.
3. Auto-delete only removes the **raw transcript** — the summary and all derived
   knowledge (signals, entities, KB graph) are kept.
4. A clearly-labeled **future-feature placeholder**: let a person remove
   themselves (or parts of themselves) from the knowledge base.

## What already exists (reuse, don't rebuild)

- Owner-by-default: bot ingest sets `transcript_sessions.owner_user_id`
  (`api/webhooks_recato.py` -> `/transcripts/ingest`). Shows on `/dashboard`
  and `/meeting/[id]`.
- Email sharing: `meeting_shares` table, endpoints in `api/bot_routes.py`
  (`GET/POST /api/meetings/{id}/shares`, `POST /{id}/visibility`), UI in
  `frontend/src/components/owner-controls.tsx`. Visibility today is BINARY
  (`owner-only` <-> `shared`).
- Email + magic-link delivery: Resend (`infra/email.py`),
  `infra/magic_links.py`, recipient view at `/m/[token]`.
- Schema: raw transcript lives in `transcript_sessions.raw_diarization`
  (immutable); summary + derived live in `transcript_sessions.derived` (JSON).
  This split is what makes "delete raw, keep summary" clean.

## Decisions (locked with product owner)

- **Delete behavior:** auto-delete removes ONLY the raw transcript. Keep summary,
  signals, entities, and KB. Optional warning email ~24h before deletion.
- **Retention config:** account-wide default + per-meeting override.
- **Permission levels:** `summary_and_transcript` (default) | `summary_only`.
- **Transcript-section UI states:** normal / processing / auto-deleted /
  not-shared (summary-only) — each shows the right message.
- **Future feature (parked):** self-removal from the knowledge base. Placeholder
  only for now.

---

## Phase 1 — Per-share permission levels

- Migration `0011`: add `scope` to `meeting_shares`
  (`summary_and_transcript` default | `summary_only`).
- `infra/workspaces.py`: `add_meeting_share(..., scope=...)`; expose scope in
  `list_meeting_shares`.
- `api/bot_routes.py`: `POST /{id}/shares` accepts `scope`.
- Enforcement at read (`api/transcripts_routes.py` meeting detail): strip
  `raw_diarization` from the response when the viewer's access is via a
  `summary_only` share. Owner / workspace members always see full transcript.
- `owner-controls.tsx`: per-recipient scope dropdown ("Summary only" /
  "Summary + full transcript"). Reflect scope in share email copy.

## Phase 2 — Retention / auto-delete

Schema:
- `users.settings` JSON column: `{ retention_days: null | int }`
  (account default; `null` = keep forever).
- `transcript_sessions.retention_override`: nullable — `null` = inherit account
  default, `'keep_forever'`, or an int (days). Per-meeting override.
- `transcript_sessions.raw_transcript_deleted_at`: timestamp set when retention
  purges the raw transcript.

Backend:
- `GET/POST /api/users/me/settings` (account default).
- Per-meeting override endpoint (extend `api/bot_routes.py`).
- Sweep job: find sessions whose effective expiry
  (`created_at + effective_days`) has passed and `raw_transcript_deleted_at IS
  NULL`; null out `raw_diarization`, set `raw_transcript_deleted_at`. Keep
  `derived`. Runnable as a script/endpoint; external scheduler triggers it.

Frontend:
- New `/settings` page: account-wide retention selector. Add to
  `middleware.ts` protected routes + sidebar link in `app-shell.tsx`.
- Per-meeting override control on `/meeting/[id]` ("keep forever" / "delete
  after N days").
- Transcript-section states on `/meeting/[id]`:
  - normal -> show transcript
  - processing -> existing enrichment-pending state
  - auto-deleted -> "Transcript auto-deleted on <date>" (summary still shown)
  - summary-only share -> "Transcript wasn't shared with you"

## Phase 3 — Optional 24h warning email (nice-to-have)

- `transcript_sessions.retention_warned_at` timestamp.
- Sweep pass: sessions ~24h before effective expiry with `retention_warned_at
  IS NULL` -> send email via Resend, set `retention_warned_at`.
- New email template in `infra/email_templates.py`.

## Phase 4 — Future-feature placeholder + polish

- Disabled "Remove me from the knowledge base (coming soon)" control (likely on
  `/settings`). No logic — just reserves the surface.
- Test pass on the security boundary: a `summary_only` recipient must NEVER
  receive `raw_diarization`. Cover auto-deleted + not-shared read paths.

## Open / deferred

- Scheduler choice for the sweep (cron vs in-app loop) — decide at Phase 2.
- Whether per-meeting override UI ships in Phase 2 or as a fast-follow.
