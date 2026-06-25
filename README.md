# Conclave — Confidential Team Memory

Conclave is a **meeting-intelligence system where the operator provably cannot read your meetings.**
Transcripts are captured, enriched, and turned into a searchable, graph-connected team memory —
inside attestable confidential infrastructure (Intel TDX). Every LLM call happens **at ingest**; the
read path (search, entities, obligations, graph) is pure SQL + local embeddings, so no third-party
API ever sees your data. The one exception is the optional `/ask` RAG endpoint, which synthesizes an
answer with the same TEE-served LLM used at ingest.

> **Read this first (mental model).** One FastAPI process + one SQLite file (relational + full-text +
> vectors) + a Next.js frontend. Transcripts arrive from the **capture** microservice (Conclave's
> meeting bot, extracted from Recato — see the `capture/` repo), in-person
> **Record** capture, or **upload**. Ingest does all the AI (enrich → chunk → embed → extract →
> store, bi-temporally). The frontend reads via fast, LLM-free queries. Speaker **identity** is
> resolved against **VFTE/FPM** (voiceprints). The whole thing runs in a **Phala dstack TDX CVM** and
> exposes a `/attestation` quote so a client can verify the enclave before trusting it.

> **Heads-up for anyone reading old docs:** this repo used to also host a "hackathon-novelty / interview
> skill runtime" (a LangGraph-based `/instances`+`/submit` product with its own `client/` frontend).
> **That was removed** — Conclave is now purely the transcript-intelligence product. If you see
> references to skills, `/instances`, langgraph, or `client/apps/web`, they are stale.

## Contents
- [Architecture at a glance](#architecture-at-a-glance)
- [Ingest pipeline (where the AI is)](#ingest-pipeline-where-the-ai-is)
- [Query path (deliberately LLM-free)](#query-path-deliberately-llm-free)
- [Ingest sources](#ingest-sources)
- [HTTP API surface](#http-api-surface)
- [Storage & migrations](#storage--migrations)
- [Trust, privacy & attestation](#trust-privacy--attestation)
- [Identity (speaker → person)](#identity-speaker--person)
- [Frontend](#frontend)
- [Configuration](#configuration)
- [Run it locally](#run-it-locally)
- [Deploy](#deploy)
- [Tests & eval](#tests--eval)
- [Repo map](#repo-map)

## Architecture at a glance
```
 capture bot ┐
 in-person   ┤ transcript ──► INGEST PIPELINE (all LLM work, in the TEE)
 upload     ┘                  parse → enrich → chunk → embed → extract → store
                                          │
                                          ▼
                          ONE SQLite file: relational + FTS5 + sqlite-vec
                                          │
                                          ▼
                        QUERY PATH (no LLM*): search · entities · obligations · graph
                                          │
                                          ▼
                          Next.js UI (frontend/) · per-meeting visibility enforced
```
- **One process, one DB.** FastAPI app (`main.py`) + a single SQLite file holding relational data, the
  BM25 index (FTS5), and the vector ANN index (`sqlite-vec`). No Postgres / Pinecone / Elastic — every
  external service is a hole in the attestation story.
- **LLM backends** (`config.py`, `transcripts/llm.py`): **RedPill** (Phala TEE-served `gemma-3-27b-it`,
  default) · **NEAR AI** (`DeepSeek-V3.1`) · **Ollama** (local `qwen2.5-conclave`). Flip with
  `python -m transcripts.cli llm use <backend>`.
- **Embeddings** (`transcripts/embed.py`): `nomic-embed-text v1.5` via Ollama — 768-dim stored in
  `embeddings`, 256-dim Matryoshka-truncated copies in the `chunks_vec` ANN index. Local, in-process.
- `*` the only LLM on the read path is the optional `/ask` RAG answer.

## Ingest pipeline (where the AI is)
Triggered async after a transcript lands (`api/transcripts_routes.py::_enrich_in_background`):

1. **Parse → store** (`transcripts/parse.py`, `store.py`): raw turns persist immutably in
   `transcript_sessions.raw_diarization`; all derived data lands in `derived` (JSON). This split is
   what makes "delete raw, keep summary" clean.
2. **v1 enrichment** (`transcripts/enrich.py`): map-reduce summary + signals via the TEE LLM.
3. **3.5a retrieval indexing — always on** (`transcripts/kb_pipeline.py`): turn-aware chunking
   (`kb_chunk.py`, never splits mid-turn) → 1–2 sentence context header per chunk (`context_header.py`)
   → embed → FTS5 (trigger-synced) + `sqlite-vec` ANN. Best-effort & idempotent (re-runnable).
4. **3.5b knowledge extraction — flag `ENABLE_KB_PIPELINE`** (`transcripts/kb_extract.py`,
   `extract.py`, `entity_resolution.py`, `importance.py`, `upsert.py`): typed entity + obligation
   extraction (1 call/chunk) → **lexical-first** entity resolution over definition embeddings (the
   OI-7 over-merge fix — no bare-name cosine auto-merge) → importance scoring (batched) → Mem0-style
   ADD/UPDATE/DELETE/NOOP upsert → **bi-temporal write** (`valid_to`/`superseded_by`, never hard-deletes).

Per-stage cost is queryable live at `GET /api/workspaces/{id}/ingest-metrics`.

## Query path (deliberately LLM-free)
`POST /api/workspaces/{id}/search` (`api/kb_routes.py`, `infra/rrf.py`):
- embed query locally (nomic, `search_query:` prefix) ‖ FTS5 BM25 (sanitized — no operator injection)
- **Reciprocal Rank Fusion** (k=60, ~20 lines, no model) merges the two legs
- per-meeting **visibility filter** (`can_user_see`) applied server-side on every route

`entities` / `obligations` / `graph` are pure SQL projections. `POST /api/workspaces/{id}/ask` is the
one read endpoint that calls the LLM (RAG answer synthesis over retrieved chunks).

## Ingest sources
| Source | Endpoint | Notes |
|---|---|---|
| **Capture bot** (online meetings) | bot streams to Redis `transcription_segments` live; `POST /api/webhooks/capture/meeting-completed` finalizes | HMAC-signed, idempotent; finalize = live buffer → canonical envelope → bind workspace → identity → enrich |
| **In-person Record** | `POST /api/workspaces/{id}/record` | capture audio → FPM diarize/identify + ASR → merge → ingest (consent plane) |
| **Upload** | `POST /api/workspaces/{id}/transcripts` | paste/file; same enrich chain as the webhook |
| **Capture stream** | `POST /api/capture/audio-chunk` + Redis `transcription_segments` consumer (`connectors/capture`) | audio → Conclave TEE; segment stream consumed as a consumer group |
| **Calendar auto-dispatch** | `infra/scheduler.py` poll → `infra/calendar_dispatch.py` | sends the bot to soon-starting connected-calendar meetings |

Producers translate to a **canonical transcript envelope** before Conclave core sees them
(`connectors/capture/`), so Conclave stays source-agnostic.

### Ingest contract — what shapes each endpoint accepts
Everything normalizes into one **canonical transcript envelope** (`connectors/capture/translator.py`)
before enrichment. That target shape is:
```jsonc
{
  "meeting": {
    "external_id": "abc-defg-hij",      // native meeting id (e.g. a Meet code)
    "platform": "google_meet",          // lowercased; optional
    "url": "https://meet.google.com/…", // optional
    "title": "…",                       // optional
    "participants": ["Alice", "Bob"]    // optional
  },
  "segments": [
    { "speaker": "Alice", "text": "…",
      "start": 0.0, "end": 1.8,         // relative seconds (floats)
      "language": "en",                  // optional
      "absolute_start": "2026-06-25T12:00:03Z", "absolute_end": "…" }  // optional UTC
  ]
}
```
What each ingest path expects on the wire:

| Endpoint | Content type | Shape it accepts |
|---|---|---|
| `POST /api/webhooks/capture/meeting-completed` | JSON, **HMAC-signed** (`X-Signature: sha256=…`, `CAPTURE_WEBHOOK_SECRET`) | `{event_id, event_type:"meeting.completed", api_version, created_at, data:{meeting:{platform, native_meeting_id, status}}}`. **Finalize signal** — the bot has already streamed segments into the live buffer (`transcription_segments`); this materializes `raw_diarization` from that buffer (write-once), then translates → binds → enriches. **No fetch.** (`CAPTURE_API_BASE_URL`/`CAPTURE_API_TOKEN` point at the capture runtime-api, used by `connectors/capture/launch.py` to *launch* bots.) |
| `POST /api/workspaces/{id}/transcripts` (upload) | JSON `{ "text": "<≤2 MB>" }` | `text` is auto-detected: a **JSON** transcript (VoxTerm/generic segment shapes) **or** **Otter-style plaintext** (`Speaker  M:SS` lines). 422 if zero segments parse — junk is never stored. |
| `POST /api/workspaces/{id}/record` (in-person) | JSON (capture handle) | kicks the capture→FPM diarize/identify + ASR→merge chain, which emits envelope segments. |
| `POST /api/capture/audio-chunk` | `multipart/form-data` | `metadata` (JSON: `{meeting_id, session_uid, format, chunk_seq, is_final}`), `chunk_seq` (int), `is_final`, `file` (audio bytes). Raw audio is **stored, not parsed** here (staged for diarization/VFTE); transcript text arrives via the segment stream below. |
| Redis stream `transcription_segments` (consumed by `connectors/capture`) | Redis `XADD` | live bot segments: `{type:"transcription", token, uid, segments:[{start, end, text, speaker, completed, absolute_start_time, absolute_end_time}]}` (`completed:false` draft → `true` confirmed). |

Speaker labels and timestamps are preserved verbatim through translation; identity resolution
(speaker → person) happens later in the pipeline, not at the ingest boundary.

## HTTP API surface
Mounted in `main.py`. Prefix → file:

| Prefix | File | Key endpoints |
|---|---|---|
| _(none)_ | `api/routes.py` | `/health`, `/attestation` (TDX quote), legacy token/OTP auth (`/register`, `/generate-token`, `/auth/*`, `/me`) |
| `/auth/v1` | `auth/routes.py` | cookie-backed v1 auth: `send-otp`, `verify-otp`, `exchange-token`, `dev-login`, `logout`, `me` |
| `/transcripts` | `api/transcripts_routes.py` | `sessions`, `sessions/{id}`, `sessions/{id}/transcript` (raw, gated), `…/visibility`, `me/action-items`, ingest |
| `/api/workspaces` | `workspaces_routes.py` | list/create, `{id}`, `{id}/meetings`, `{id}/open-questions`, members (501 stub) |
| `/api/workspaces` | `kb_routes.py` | `{id}/entities`, `{id}/entities/{name}`, `{id}/obligations`, `{id}/ingest-metrics`, `{id}/graph`, `{id}/search`, `{id}/ask` |
| `/api/workspaces` | `upload_routes.py` / `record_routes.py` | `{id}/transcripts` (upload), `{id}/record`, `{id}/meetings/{sid}/tag-speaker` |
| `/api/meetings` | `bot_routes.py` | `invite-bot`, `bot/status_change`, `active`, bot delete/status, `{sid}/visibility`, `{sid}/shares` (GET/POST), `{sid}/retention`, `{sid}/tag-speaker` |
| `/api/users` | `users_routes.py` | `me/settings` (GET/POST) — account retention default |
| `/api/calendar` | `calendar_routes.py` | Google OAuth `connect`/`callback`/`status`/`disconnect`, `events` (GET/POST), `events/{id}/auto-record`, `auto-record-all` |
| `/api/capture` | `capture_routes.py` | `audio-chunk` |
| `/api/webhooks/capture` | `webhooks_capture.py` | `meeting-completed` |
| `/api/magic-links` | `magic_link_routes.py` | `{token}`, `{token}/consume` (public token resolve; meeting still permission-gated) |

A static dashboard is also mounted at `/dashboard` (serves `web/`, reads `/transcripts/sessions`).

## Storage & migrations
- `storage/sqlite.py` — relational tables + app state; `storage/vec.py` — `sqlite-vec` (vec0) ANN;
  `storage/kb.py` + `storage/kb_graph.py` — KB read/write.
- On import, `main.py` runs `storage.init_db()` then **Alembic `upgrade head`** (migrations
  `alembic/versions/0001`–`0016`). Notable: `0006` embeddings/chunks, `0007` entities/facts/obligations,
  `0008` ingest_metrics, `0011` google_calendar, `0012` meeting_share_scope, `0013` retention,
  `0015` capture_state, `0016` live_segments.
- Core tables: `transcript_sessions` (`raw_diarization` immutable + `derived` JSON), `workspaces`,
  `users`, `meeting_shares` (`scope`: `summary_and_transcript` | `summary_only`), `chunks`/`embeddings`/
  `chunks_vec`, `entities`/`mentions`/`obligations`/`facts`, `ingest_metrics`, `google_oauth_tokens`.

## Trust, privacy & attestation
- **Operator-blind by construction:** all LLM work is at ingest inside the TEE; the read path is local.
- **Raw transcript is gated:** `transcript_sessions.raw_diarization` is served only to the owner /
  workspace members / `summary_and_transcript` shares. `summary_only` recipients are stripped of raw
  (`api/transcripts_routes.py`). Visibility (`can_user_see`) is enforced server-side on every route.
- **Retention / auto-delete** (`transcripts/retention.py`): account default (`/api/users/me/settings`)
  + per-meeting override (`/api/meetings/{sid}/retention`). The sweep purges **only the raw transcript**
  (`raw_transcript_deleted_at`); summary + derived KB are kept.
- **TDX attestation:** `GET /attestation?nonce=` → dstack TDX quote (`infra/enclave.py`), verifiable via
  Phala's endpoint. Stub outside a TEE (`IN_TEE != "true"`). This is how a client verifies the CVM before
  routing meetings/secrets to it.

## Identity (speaker → person)
Post-meeting voice identity (P4): after ingest, diarized segments are re-embedded and matched against
**VFTE/FPM** voiceprints (`infra/fpm_consent.py`, `infra/identity.py`, `transcripts/identity.py`).
Confident matches name the speaker; borderline → "Is this you?"; no match → anonymous. Manual fixes via
`tag-speaker`. Resolved speakers carry `voiceprint_id`s into the read path. Conclave consumes identity —
it does **not** own diarization (capture) or voiceprint policy (VFTE).

## Frontend
Next.js app in **`frontend/`** (this is the product UI; the old skills `client/` app was removed).
Routes under `frontend/src/app/`: `dashboard`, `search`, `entities` / `entity`, `graph`, `obligations`,
`questions`, `meeting`, `workspace`, `calendar`, `settings`, `login` / `signup` / `auth`, `invite`,
`m` (magic-link recipient view).

## Configuration
All env vars use the `CONCLAVE_` prefix (`config.py`, `.env.example`):

| Group | Vars |
|---|---|
| **LLM** | `LLM_BACKEND` (`redpill`\|`nearai`\|`ollama`), `REDPILL_API_KEY`/`REDPILL_MODEL`, `NEARAI_API_KEY`, `DEFAULT_MODEL` |
| **Auth** | `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `TOKEN_ENC_KEY` |
| **Calendar** | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` |
| **Capture** | `CAPTURE_API_BASE_URL`, `CAPTURE_API_TOKEN` (capture runtime-api, for bot launch), `CAPTURE_MEETING_COMPLETED_URL`, `CAPTURE_WEBHOOK_SECRET` |
| **Identity (VFTE/FPM)** | `FPM_BASE_URL`, `FPM_API_TOKEN`, `FPM_WORKSPACE` |
| **ASR** | `TRANSCRIPTION_SERVICE_URL` (NEAR Whisper), `TRANSCRIPTION_SERVICE_TOKEN`, `TRANSCRIPTION_MODEL` |
| **TEE / tracing** | `IN_TEE`, `DSTACK_AGENT_URL`, `LANGCHAIN_TRACING_V2`/`LANGCHAIN_API_KEY`/`LANGCHAIN_PROJECT` |

## Run it locally
**Backend**
```bash
cp .env.example .env
pip install -r requirements.txt
uvicorn main:app --reload          # → http://localhost:8000
# or: python -m transcripts.cli serve   (FastAPI + static /dashboard)
```
**LLM**: defaults to RedPill (cloud TEE). For fully local, use Ollama:
```bash
make ollama-prereqs && make ollama-models     # pull nomic-embed-text + the chat model
python -m transcripts.cli llm use ollama
python -m transcripts.cli llm smoke            # prove wiring
```
**Frontend**
```bash
cd frontend && npm install && npm run dev      # → http://localhost:3000
```
**CLI** (`python -m transcripts.cli …`): `ingest` (batch parse, no LLM) · `enrich` (LLM map-reduce) ·
`serve` · `eval` (score vs golden YAML) · `link` (identity linkage) · `llm status|use|smoke` · `run`.

## Deploy
- **Docker:** `Dockerfile` + `docker-compose.yml`. Set `IN_TEE=true` for the enclave path.
- **Production:** runs as a **Phala dstack TDX CVM** (`conclave`). Updates are typically env-only via the
  Phala CLI (`phala deploy --cvm-id <id>`). The `/attestation` endpoint proves the deployed image.

## Tests & eval
```bash
pytest tests -q
```
~548 tests pass. A handful of pre-existing failures exist in `test_webhooks_capture`, `test_calendar_stop_link`,
and `test_record_routes` (env/idempotency — unrelated to core read/ingest). The KB design rationale lives
in `METHODOLOGY_SURVEY.md`; eval harness + policy registry + gold queries live in `transcripts/eval.py`,
`transcripts/EVAL.md`, and `scripts/eval/`.

## Repo map
```text
main.py                     FastAPI entrypoint — mounts all routers, init_db + alembic upgrade
api/                        HTTP routers (transcripts, kb, workspaces, bot, calendar, capture, …)
auth/routes.py              cookie-backed v1 auth (/auth/v1)
transcripts/                the intelligence pipeline + CLI
  parse · enrich            raw parse, map-reduce summary/signals
  kb_pipeline · kb_chunk    chunk → context header → embed → index (3.5a)
  kb_extract · extract      typed entity/obligation extraction (3.5b, ENABLE_KB_PIPELINE)
  entity_resolution         lexical-first resolution over definition embeddings (OI-7 fix)
  importance · upsert       importance scoring + Mem0-style bi-temporal upsert
  embed                     nomic-embed-text v1.5 via Ollama (768 stored / 256 indexed)
  answer · compile_intent   /ask RAG synthesis + query intent
  retention · store         retention sweep + session read/write
  identity · team_context   speaker identity + cohort context
  llm · config · prompts    LLM backend switch, settings, prompt library
  eval · *_bakeoff          eval harness + prompt/extraction bake-offs
storage/                    sqlite (relational+state) · vec (sqlite-vec ANN) · kb · kb_graph
infra/                      scheduler(calendar) · calendar_* · google_calendar · supabase_auth ·
                            enclave(TDX) · fpm_consent · identity · rrf · workspaces · email · magic_links
connectors/capture/         launch (drive capture runtime-api) · translator (canonical envelope) ·
                            consumer (Redis segment stream) · identify (FPM voice identity)
frontend/                   Next.js product UI (dashboard, search, graph, entities, …)
alembic/versions/           migrations 0001–0016
tests/                      pytest suite
METHODOLOGY_SURVEY.md       literature/methodology grounding the KB architecture
```
Per-area detail also lives in `transcripts/` docs (`EVAL.md`, `IMPLEMENTATION_PLAN.md`) and `scripts/eval/`.
