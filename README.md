# Conclave — Confidential Team Memory

Conclave is a **meeting-intelligence product where the operator provably cannot read your meetings.**
Meetings (online bots, in-person walk-up recordings, or pasted uploads) are captured, enriched, and
turned into a searchable, graph-connected team memory — inside attestable confidential infrastructure
(Intel TDX). Every LLM call happens **at ingest**; the read path (search, entities, obligations, graph)
is pure SQL + local embeddings, so no third-party API ever sees your data. The one read-path exception
is the optional `/ask` RAG endpoint, which synthesizes an answer with the same TEE-served LLM used at
ingest.

> **Mental model (read this first).** One FastAPI process + one SQLite file (relational + full-text +
> vectors) + a Next.js frontend. The AI lives at **ingest** (parse → enrich → chunk → embed → extract →
> store, bi-temporally). The frontend reads via fast, LLM-free queries. Speaker **identity** is resolved
> against **VFTE/FPM** voiceprints. The whole thing runs in a **Phala dstack TDX CVM** and exposes a
> `/attestation` quote so a client can verify the enclave before trusting it.

> **Heads-up for old docs:** this repo once hosted a hackathon "interview skill runtime"
> (LangGraph `/instances`+`/submit` with a `client/` frontend). **That was removed.** References to
> skills, `/instances`, langgraph, or `client/apps/web` are stale.

---

## 1. Where Conclave sits — the 3-repo system

Conclave is **1 of 3 repos** that together deliver confidential team-meeting intelligence with in-person
diarization + voice identity (validated live end-to-end, all merged to `main`, 2026-06-27):

| Repo | Dir | Role | State |
|---|---|---|---|
| **Conclave** (this repo) | `conclave-shape-rotator/` | **The product.** Orchestration, transcript persistence, enrichment / KB / intelligence, and the **in-person finalize** (consumes capture's live stream, then runs authoritative DiariZen diarization + VFTE identity). | — |
| **capture** | repo `conclave-sync`, dir `capture/services/diarization/` | Diarization + ASR microservice: **diart** (live/CPU) + **DiariZen** (post/GPU) acoustic diarization, in-person browser-mic ingress, NEAR Whisper ASR per span. | **Stateless** — holds no voiceprints |
| **VFTE / FPM** | repo `VFTE`, dir `FPM/` | Identity-only layer: voiceprint **embed → match → tag** with consent (`/v1/identify-spans`). Diarization was stripped out. | Identity only |

### The flagship in-person pipeline (Conclave's role in **bold**)

```
 user clicks RECORD in Conclave's frontend
        │  browser mic stream
        ▼
 capture WS ──► diart live-diarize + NEAR ASR per span ──► Redis `transcription_segments`
        │                                                          │
        │                                          ┌───────────────┘
        ▼                                          ▼
 on Stop, capture uploads recording      **Conclave consumer ingests → `live_segments`**
 + fires Conclave's `meeting-completed`   **→ live SSE view shows [speaker] text live**
 webhook
        │
        ▼
 **Conclave FINALIZES (non-blocking background task):**
   1. materialize the diart transcript immediately (write-once `raw_diarization`)
   2. **DiariZen (GPU) re-diarizes AUTHORITATIVELY → OVERWRITES `raw_diarization`**
   3. **VFTE identifies the speakers** (enroll on 1st meeting / recognize later)
   4. names resolve via **consent-gated tagging**
```

A 2nd meeting **recognizes the same speakers** from stored voiceprints with no re-tagging.

The online-bot path is the same shape minus the mic: a capture bot streams `transcription_segments`
live, then the `meeting-completed` webhook finalizes from the buffered segments.

**Monorepo-root reference docs** (`shape-rotator-all/`): `DIARIZATION-MIGRATION.md`,
`BUILD-LOG-diarization-deployment.md`, `TROUBLESHOOTING-inperson.md`, `JOBS-QUEUE-HANDOFF-PROMPT.md`,
`DEPLOY-LOCAL.md`, `CONCLAVE-CAPTURE-ARCHITECTURE.md`.

---

## 2. Architecture & key directories

**One process, one DB.** `main.py` boots a single FastAPI app, runs `storage.init_db()` then Alembic
`upgrade head`, mounts every router, and on lifespan-start launches the calendar scheduler + the capture
Redis consumer. The DB is one SQLite file holding relational data, the BM25 index (FTS5), and the vector
ANN index (`sqlite-vec`). No Postgres / Pinecone / Elastic — every external service is a hole in the
attestation story.

```
main.py            FastAPI entrypoint — mounts routers, init_db + alembic upgrade head, starts scheduler + capture consumer
config.py          Settings (CONCLAVE_ env prefix) + get_llm() backend switch; LangSmith tracing force-disabled here
api/               HTTP routers (one file per surface) — see §4
auth/              cookie-backed v1 auth (/auth/v1) + require_current_user session dep
connectors/capture/  the capture bridge (see below)
transcripts/       the intelligence pipeline + CLI + persistence models
storage/           sqlite (relational + state) · vec (sqlite-vec ANN) · kb · kb_graph
infra/             scheduler · calendar_* · enclave (TDX) · fpm_consent · identity · rrf · workspaces · email · magic_links · bot_invitations
frontend/          Next.js product UI (dashboard, search, graph, entities, meeting, record, …)
alembic/versions/  migrations 0001–0016
tests/             pytest suite
web/               legacy static dashboard mounted at /dashboard
```

### Load-bearing modules (the ones to read first)

| Module | What it does |
|---|---|
| `api/webhooks_capture.py` | **In-person + online finalize trigger.** `POST /api/webhooks/capture/meeting-completed`: HMAC-verify → materialize `raw_diarization` from the `live_segments` buffer (write-once, idempotent) → bind workspace (bot_invitation for online; payload `workspace_id` for in-person, owned by the workspace creator) → spawn the non-blocking `_identify_then_enrich()` background task. |
| `connectors/capture/identify.py` | **Finalizer-A** (`identify_meeting`). The authoritative post-pass: when `CONCLAVE_INPERSON_VIA_CAPTURE` + `CONCLAVE_DIARIZE_URL` are set, POSTs the recording to **DiariZen** → authoritative spans → VFTE `/v1/identify-spans` for names → **re-attributes every ASR segment to DiariZen's speaker and OVERWRITES `raw_diarization`** via `set_raw_diarization`. Falls back to (a) capture's own diart spans, or (b) legacy FPM re-diarize. Best-effort — never blocks finalize. |
| `connectors/capture/consumer.py` | **Redis stream → `live_segments`.** Reads `transcription_segments` as a consumer group (replay-safe), buffers each segment via `store.append_segment`. No-op if `REDIS_URL` unset. |
| `connectors/capture/diarize_client.py` | HTTP client for the DiariZen GPU service (heartbeat-NDJSON; diarize-only, no identity). |
| `connectors/capture/translator.py` | Normalizes any producer into the **canonical transcript envelope** (`to_canonical`). |
| `connectors/capture/launch.py` | Drives capture's runtime-api to *launch* bots for online meetings. |
| `api/record_routes.py` | **Legacy in-person batch path** + the reusable merge/tag helpers: `merge_by_timestamp` (ASR ∥ identity → `[speaker] text`, deterministic labels), `build_resolved_speakers`, and `tag_speaker` (host binds `Speaker N` → name/email via FPM). |
| `api/live_routes.py` | **Live SSE view** — `GET /api/meetings/{id}/live` tails the `live_segments` buffer (diart preview) before DiariZen finalizes; `/live-view` is a minimal EventSource page. |
| `transcripts/store.py` + `storage/sqlite.py` | Persistence. `store` is the typed `Session`↔table translation; `sqlite` owns the write-once `raw_diarization` invariant (`set_raw_diarization` is the one sanctioned override). |

### Ingest pipeline (where all the AI is)

Triggered async after a transcript is materialized (`_enrich_in_background`):

1. **Parse → store** (`transcripts/parse.py`, `store.py`): raw turns persist immutably in
   `transcript_sessions.raw_diarization`; derived data lands in `derived` (JSON). This split is what makes
   "delete raw, keep summary" clean.
2. **v1 enrichment** (`transcripts/enrich.py`): map-reduce summary + signals via the TEE LLM.
3. **3.5a retrieval indexing — always on** (`transcripts/kb_pipeline.py`): turn-aware chunking
   (`kb_chunk.py`, never splits mid-turn) → 1–2 sentence context header per chunk (`context_header.py`) →
   embed → FTS5 (trigger-synced) + `sqlite-vec` ANN. Best-effort & idempotent.
4. **3.5b knowledge extraction — flag `ENABLE_KB_PIPELINE`** (`kb_extract.py`, `extract.py`,
   `entity_resolution.py`, `importance.py`, `upsert.py`): typed entity + obligation extraction (1 call/chunk)
   → **lexical-first** entity resolution over definition embeddings (the OI-7 over-merge fix) → importance
   scoring → Mem0-style ADD/UPDATE/DELETE/NOOP upsert → **bi-temporal write** (`valid_to`/`superseded_by`,
   never hard-deletes).

Per-stage cost is queryable live at `GET /api/workspaces/{id}/ingest-metrics`.

### Query path (deliberately LLM-free)

`POST /api/workspaces/{id}/search` embeds the query locally (nomic, `search_query:` prefix) ‖ runs FTS5
BM25 (sanitized), merges the two legs with **Reciprocal Rank Fusion** (k=60, `infra/rrf.py`), and applies
the per-meeting visibility filter server-side. `entities` / `obligations` / `graph` are pure SQL
projections. `POST /api/workspaces/{id}/ask` is the only read endpoint that calls the LLM (RAG synthesis).

**LLM backends** (`config.py`, `transcripts/llm.py`): **RedPill** (Phala TEE `google/gemma-3-27b-it`,
default) · **NEAR AI** (`DeepSeek-V3.1`) · **Ollama** (local `qwen2.5-conclave`). Switch with
`python -m transcripts.cli llm use <backend>`. **Embeddings**: `nomic-embed-text v1.5` via Ollama —
768-dim stored, 256-dim Matryoshka copies in the ANN index. Local, in-process.

---

## 3. Data model

The core row is a **Session** (`transcript_sessions`), three logical parts:

| Part | Column | Mutability | Contents |
|---|---|---|---|
| **Raw** | `raw_diarization` | **Write-once (§A invariant)** — `save_session` refuses to overwrite once a row exists. **One sanctioned exception:** the in-person **DiariZen post-pass overwrite** via `store.set_raw_diarization` → `sqlite.update_transcript_raw`. | The immutable diarized turns `[{speaker, text, start, end}]`. |
| **Metadata** | `metadata` (JSON) | Mutable | Source, date, owner/visibility mirrors, `raw_intent`, and **`resolved_speakers`** (`{label: {voiceprint_id, name, confidence}}` — the speaker→person map identity writes). |
| **Derived** | `derived` (JSON) | Mutable (re-runnable) | The served projection: summary, signals, action items — everything enrichment + KB produce. |

Re-running enrichment only moves `derived`/`metadata` forward; raw stays put. The live buffer
(`live_segments`, keyed by native meeting id) is a **separate** append-only table that the finalize path
materializes into `raw_diarization` exactly once, then clears.

**Served vs withheld (transcript-read gating, `api/transcripts_routes.py`):** the derived projection
(summary, entities, action items, resolved-speaker chips) is broadly served; **`raw_diarization` is the
only field stripped at the API boundary**. `can_user_see` gates a session generally; the stricter
`can_see_transcript` gates the raw transcript — served only to the owner, workspace members, and
`summary_and_transcript` shares. `summary_only` recipients pass `can_user_see` (get the summary) but fail
`can_see_transcript` (raw withheld).

Other core tables: `workspaces`, `users`, `meeting_shares` (`scope`: `summary_and_transcript` |
`summary_only`), `chunks`/`embeddings`/`chunks_vec`, `entities`/`mentions`/`obligations`/`facts`,
`ingest_metrics`, `google_oauth_tokens`, `bot_invitations`, `live_segments`. Migrations live in
`alembic/versions/` (0001–0016; notable: 0006 embeddings, 0007 entities/obligations, 0011 calendar,
0012 share-scope, 0013 retention, 0015 capture_state, 0016 live_segments).

---

## 4. HTTP API surface

Mounted in `main.py`. Prefix → file:

| Prefix | File | Key endpoints |
|---|---|---|
| _(none)_ | `api/routes.py` | `/health`, `/attestation` (TDX quote), legacy token/OTP auth (`/register`, `/generate-token`, `/auth/*`, `/me`) |
| `/auth/v1` | `auth/routes.py` | cookie auth: `send-otp`, `verify-otp`, `exchange-token`, `dev-login`, `logout`, `me` |
| `/transcripts` | `api/transcripts_routes.py` | `sessions`, `sessions/{id}`, `sessions/{id}/transcript` (raw, gated), `…/visibility`, `me/action-items`, ingest |
| `/api/workspaces` | `api/workspaces_routes.py` | list/create, `{id}`, `{id}/meetings`, `{id}/open-questions`, members |
| `/api/workspaces` | `api/kb_routes.py` | `{id}/entities`, `{id}/entities/{name}`, `{id}/obligations`, `{id}/ingest-metrics`, `{id}/graph`, `{id}/search`, `{id}/ask` |
| `/api/workspaces` | `api/upload_routes.py` · `api/record_routes.py` | `{id}/transcripts` (upload), `{id}/record` (in-person batch), `{id}/meetings/{sid}/tag-speaker` |
| `/api/meetings` | `api/bot_routes.py` | `invite-bot`, `bot/status_change`, `active`, `{sid}/visibility`, `{sid}/shares`, `{sid}/retention`, `{sid}/tag-speaker` |
| `/api/meetings` | `api/live_routes.py` | `{native_id}/live` (SSE), `{native_id}/live-view` (page) |
| `/api/users` | `api/users_routes.py` | `me/settings` (account retention default) |
| `/api/calendar` | `api/calendar_routes.py` | Google OAuth `connect`/`callback`/`status`/`disconnect`, `events`, `events/{id}/auto-record`, `auto-record-all` |
| `/api/capture` | `api/capture_routes.py` | `audio-chunk` (multipart audio → `CONCLAVE_AUDIO_DIR`; staged for DiariZen/VFTE) |
| `/api/webhooks/capture` | `api/webhooks_capture.py` | `meeting-completed` (**finalize**; HMAC-signed, idempotent) |
| `/api/magic-links` | `api/magic_link_routes.py` | `{token}`, `{token}/consume` (public resolve; meeting still permission-gated) |

A legacy static dashboard is also mounted at `/dashboard` (serves `web/`).

### Ingest contract (canonical envelope)

Every producer is translated to one **canonical transcript envelope**
(`connectors/capture/translator.py`) before core sees it, so Conclave stays source-agnostic:

```jsonc
{
  "meeting": { "external_id": "abc-defg-hij", "platform": "google_meet",
               "url": "…", "title": "…", "participants": ["Alice","Bob"] },
  "segments": [ { "speaker": "Alice", "text": "…", "start": 0.0, "end": 1.8,
                  "language": "en", "absolute_start": "…", "absolute_end": "…" } ]
}
```

| Ingest path | Wire shape |
|---|---|
| `POST /api/webhooks/capture/meeting-completed` | HMAC-signed (`X-Signature: sha256=…`, `CAPTURE_WEBHOOK_SECRET`) `{event_id, event_type:"meeting.completed", data:{meeting:{platform, native_meeting_id, status, workspace_id?}}}`. **Finalize signal** — segments already streamed into `live_segments`; this materializes `raw_diarization` from that buffer. No post-hoc fetch. |
| `POST /api/workspaces/{id}/transcripts` (upload) | JSON `{ "text": "<≤2 MB>" }`; auto-detects a JSON transcript or Otter-style plaintext. 422 if zero segments parse. |
| `POST /api/workspaces/{id}/record` (in-person batch) | multipart `file=<audio>`, `intent?`. Server-side: FPM diarize+identify ∥ NEAR ASR → `merge_by_timestamp` → upload ingest path. Tokens stay server-side. |
| `POST /api/capture/audio-chunk` | multipart `metadata` (JSON), `chunk_seq`, `is_final`, `file`. Raw audio **stored, not parsed**. |
| Redis `transcription_segments` | `XADD` of `{type:"transcription", uid, segments:[{start,end,text,speaker,...}]}`; consumed by `connectors/capture/consumer.py`. |

---

## 5. Identity & consent

Identity is resolved against **VFTE/FPM** voiceprints; Conclave **consumes** identity and owns the
consent-gated tagging UX, but does **not** own diarization (capture) or voiceprint policy (VFTE).

- **Post-meeting (authoritative in-person path):** `identify_meeting` sends DiariZen's spans to VFTE
  `/v1/identify-spans`, writes `resolved_speakers[label] = {voiceprint_id, name}`, and overwrites the
  stored transcript with DiariZen's labels. First meeting **enrolls**; later meetings **recognize** the
  same voiceprint with no re-tagging (`reresolve_voiceprint` propagates a confirmed name across all of the
  workspace's transcripts, keyed on `voiceprint_id`, never the label).
- **Manual tagging** (`record_routes.tag_speaker`): the host binds a `Speaker N` label → `(name, email)`.
  Conclave maps label → `voiceprint_id` from `resolved_speakers` and calls FPM `propose_binding` with the
  host's email as `proposed_by`:
  - **Self-tag / dev auto-confirm** → status `confirmed` → name re-resolves across the workspace
    immediately.
  - **Tagging someone else** → status `pending` → the target confirms on the **VFTE consent dashboard**;
    nothing is named until they do.

> **Workspace-mapping gotcha (load-bearing).** VFTE is scoped by `settings.fpm_workspace_for(workspace_id)`
> (= `CONCLAVE_FPM_WORKSPACE`, e.g. `local-ws`/`live-test`; falls back to the raw Conclave `workspace_id`
> when unset). **Enroll AND tag must use the same value** — `identify_meeting` and `tag_speaker` both call
> `fpm_workspace_for`. Enroll under the bare workspace id but tag under the FPM workspace (or vice-versa)
> and tagging looks in a different VFTE workspace and never finds the voiceprint.

---

## 6. Configuration

All Conclave env vars use the `CONCLAVE_` prefix (`config.py`, `.env.example`). Capture-bot dispatch vars
are unprefixed.

| Group | Vars |
|---|---|
| **LLM** | `CONCLAVE_LLM_BACKEND` (`redpill`\|`nearai`\|`ollama`), `CONCLAVE_REDPILL_API_KEY`/`CONCLAVE_REDPILL_MODEL`, `CONCLAVE_NEARAI_API_KEY`/`CONCLAVE_DEFAULT_MODEL`, `CONCLAVE_OLLAMA_MODEL`/`CONCLAVE_OLLAMA_BASE_URL`, `CONCLAVE_EXTRACT_CONCURRENCY` |
| **Auth** | `CONCLAVE_SUPABASE_URL`, `CONCLAVE_SUPABASE_ANON_KEY`, `CONCLAVE_TOKEN_ENC_KEY` (Fernet, also encrypts Google tokens) |
| **Calendar** | `CONCLAVE_GOOGLE_CLIENT_ID`, `CONCLAVE_GOOGLE_CLIENT_SECRET`, `CONCLAVE_GOOGLE_REDIRECT_URI` (all unset → `/api/calendar/*` 503 + poller no-op) |
| **In-person toggles** | `CONCLAVE_INPERSON_VIA_CAPTURE` (true → boundary path: capture/DiariZen diarizes, VFTE identifies spans; false → legacy FPM re-diarize, the instant rollback) |
| **Authoritative diarizer** | `CONCLAVE_DIARIZE_URL` (DiariZen GPU service, e.g. `http://localhost:8086` via SSH tunnel), `CONCLAVE_DIARIZE_TOKEN`. Empty → fall back to diart spans. |
| **Identity (VFTE/FPM)** | `CONCLAVE_FPM_BASE_URL`, `CONCLAVE_FPM_API_TOKEN`, `CONCLAVE_FPM_WORKSPACE` (the scope used for BOTH enroll and tag — see §5) |
| **ASR** | `CONCLAVE_TRANSCRIPTION_SERVICE_URL` (NEAR Whisper; base or full `/v1/audio/transcriptions`), `CONCLAVE_TRANSCRIPTION_SERVICE_TOKEN`, `CONCLAVE_TRANSCRIPTION_MODEL` |
| **Audio staging** | `CONCLAVE_AUDIO_DIR` (where `audio-chunk` writes; `identify_meeting` re-assembles from here) |
| **Capture stream / dispatch** | `REDIS_URL`, `CAPTURE_SEGMENT_STREAM`, `CAPTURE_CONSUMER_GROUP`; `CAPTURE_API_BASE_URL`/`CAPTURE_API_TOKEN` (runtime-api for bot launch), `CAPTURE_MEETING_COMPLETED_URL`, `CAPTURE_WEBHOOK_SECRET`, `CONCLAVE_CAPTURE_INGEST_SECRET` |
| **TEE** | `CONCLAVE_IN_TEE`, `DSTACK_AGENT_URL` |

> **Telemetry kill-switch:** `config.py` force-disables all LangChain/LangSmith tracing env vars at import
> — prompts (transcript content) can never be POSTed to a third party, regardless of `.env` or deploy
> config. (`.env.example` still shows `LANGCHAIN_*` lines; they are popped at startup.)

---

## 7. Run locally

The realistic local stack is brought up from the **monorepo root** (`shape-rotator-all/`), which mounts
all three repos' `main` checkouts. See `DEPLOY-LOCAL.md` for the full runbook.

```bash
# from shape-rotator-all/
./scripts/diarize-tunnel.sh up        # SSH tunnel → GPU DiariZen at localhost:8086 (authoritative pass)
./envctl local                        # render environments/matrix.local.env into each repo's .env
docker compose -f docker-compose.local.yml -f docker-compose.migrated.yml up -d
```

| Service | Port | What it is |
|---|---|---|
| **conclave-api** | `:8000` | this repo, `uvicorn main:app`; `CONCLAVE_INPERSON_VIA_CAPTURE=true`, `CONCLAVE_DIARIZE_URL=http://host.docker.internal:8086`. The migrated override **mounts `./conclave-shape-rotator` into the container** so it runs the live source. |
| **conclave-web** | `:3001` | the Next.js frontend (`frontend/`), `next dev -p 3001`, `NEXT_PUBLIC_API_BASE=http://conclave-api:8000` |
| capture diart | `:8087` | live diarize+ASR; `http://localhost:8087/inperson` records a room on one mic and publishes to Redis |
| fpm-backend | `:8085` | VFTE identity-only |
| redis | `:6379` | in-RAM `transcription_segments` bus (no persistence) |
| DiariZen | `:8086` (tunnel) | GPU authoritative diarizer |

**Watch it live:** record via `http://localhost:8087/inperson`, watch `[speaker] text` arrive at
`http://localhost:8000/api/meetings/<id>/live-view`, Stop, then confirm the finalized transcript shows
DiariZen's authoritative speakers + VFTE names.

**Standalone backend (no Docker), for tests/dev:**
```bash
cp .env.example .env
pip install -r requirements.txt
uvicorn main:app --reload          # → http://localhost:8000
# fully local LLM:
make ollama-prereqs && make ollama-models
python -m transcripts.cli llm use ollama && python -m transcripts.cli llm smoke
```

**CLI** (`python -m transcripts.cli …`): `ingest` (batch parse, no LLM) · `enrich` · `serve` · `eval` ·
`link` (identity) · `llm status|use|smoke` · `run`.

---

## 8. Test

```bash
# canonical venv (the in-repo .venv is incomplete — missing sqlite_vec/alembic)
/Users/prakharojha/Desktop/me/personal/conclave/.venv/bin/python -m pytest
# or, with that venv active:
PYTHONPATH=. pytest
```

**~544 pass, 7 pre-existing failures** (test-isolation / env ordering — **not regressions**):
`record_routes` returning 503-vs-400 under full-suite ordering, and webhook-secret / calendar env tests
that depend on process env state. They pass in isolation. KB design rationale lives in
`METHODOLOGY_SURVEY.md`; the eval harness + policy registry + gold queries are in `transcripts/eval.py`,
`transcripts/EVAL.md`, and `scripts/eval/`.

---

## 9. Trust, privacy & status

- **Operator-blind by construction:** all LLM work is at ingest inside the TEE; the read path is local SQL +
  embeddings. LangSmith tracing is force-disabled in code.
- **Raw transcript is gated:** `raw_diarization` is the only field stripped at the API boundary; served only
  to owner / workspace members / `summary_and_transcript` shares (§3).
- **Retention / auto-delete** (`transcripts/retention.py`): account default (`/api/users/me/settings`) +
  per-meeting override (`/api/meetings/{sid}/retention`); the sweep purges **only** the raw transcript,
  keeping summary + KB.
- **TDX attestation:** `GET /attestation?nonce=` → dstack TDX quote (`infra/enclave.py`), verifiable via
  Phala. Stub outside a TEE (`CONCLAVE_IN_TEE != "true"`).
- **Production:** runs as a **Phala dstack TDX CVM** (`conclave`); env-only updates via
  `phala deploy --cvm-id <id>`.

### Status (2026-06-27)

The **in-person pipeline is validated live end-to-end and merged to `main`** across all three repos
(record → diart live → DiariZen authoritative → VFTE enroll → tag → recognize). The interim finalize runs
as a **non-blocking in-process background task** (`asyncio.create_task(_identify_then_enrich())`), which
holds the DiariZen HTTP connection open for the whole ~6-minute job and is lost on a Conclave restart. The
planned next step is a **durable diarization job queue** (Redis-backed, retryable, horizontally scalable
across GPU workers) — full spec in `JOBS-QUEUE-HANDOFF-PROMPT.md`. Cut a new `feat/` branch off `main` for
that work; keep `main` clean.
