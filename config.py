from __future__ import annotations

import os

from pydantic_settings import BaseSettings

# ---------------------------------------------------------------------------
# Telemetry kill-switch (operator-blind invariant)
# ---------------------------------------------------------------------------
# LangChain/LangSmith tracing ships full prompts — transcript content — to
# api.smith.langchain.com when LANGCHAIN_TRACING_V2 / LANGSMITH_TRACING is
# set. That is exactly the third-party exfiltration this product promises
# cannot happen, so it is force-disabled in code: no env var, .env line, or
# deploy-image config can re-enable it. (Found live 2026-06-04: a stale
# tracing key in .env had every LLM call POSTing prompts to LangSmith —
# rejected only because the key was invalid.)
# This module is imported by every LLM entry point (config.get_llm), so the
# guard runs before any langchain client is constructed.
for _var in ("LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING", "LANGCHAIN_API_KEY",
             "LANGSMITH_API_KEY", "LANGCHAIN_ENDPOINT", "LANGSMITH_ENDPOINT",
             "LANGCHAIN_PROJECT", "LANGSMITH_PROJECT"):
    os.environ.pop(_var, None)
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"


class Settings(BaseSettings):
    # Backend selector — one of:
    #   "redpill" (default, production TEE-served via Phala RedPill)
    #   "nearai"  (alternate TEE backend, kept for compatibility)
    #   "ollama"  (local dev)
    # Set via CONCLAVE_LLM_BACKEND.
    llm_backend: str = "redpill"

    # RedPill (Phala) — TEE-served, OpenAI-compatible API. The production
    # default. Get an API key at https://redpill.ai; set CONCLAVE_REDPILL_API_KEY.
    # `google/gemma-3-27b-it` is the cohort-transcripts default: cheap
    # ($0.04/M in), strong English instruction-following, ample 54K context.
    redpill_api_key: str = ""
    # NOTE: the live host is `api.redpill.ai` (NO hyphen). The old `api.red-pill.ai` default now 502s
    # on every call → enrich/insights silently fail. Override with CONCLAVE_REDPILL_BASE_URL if it moves.
    redpill_base_url: str = "https://api.redpill.ai/v1"
    redpill_model: str = "google/gemma-3-27b-it"

    # NearAI API — alternate TEE backend.
    nearai_api_key: str = ""
    nearai_base_url: str = "https://cloud-api.near.ai/v1"
    default_model: str = "deepseek-ai/DeepSeek-V3.1"

    # Ollama (local dev) — only used when llm_backend == "ollama".
    # Default is the Conclave-tuned qwen2.5:7b-instruct variant
    # (num_ctx=8192 baked in — see ollama/Modelfile.qwen-conclave).
    # Build it once with: ollama create qwen2.5-conclave -f ollama/Modelfile.qwen-conclave
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen2.5-conclave"

    # Embedding (unchanged)
    embedding_model: str = "all-MiniLM-L6-v2"

    # KB ingest: bounded concurrency for the per-chunk extraction LLM calls
    # (env CONCLAVE_EXTRACT_CONCURRENCY). 1 = sequential. Resolution/upsert stay
    # serial regardless. Raise to speed long transcripts; mind backend rate limits.
    extract_concurrency: int = 6

    # Supabase auth (optional — if unset, /auth/* endpoints return 503 and /register is the fallback)
    supabase_url: str = ""
    supabase_anon_key: str = ""

    # Google Calendar integration (optional — if client id/secret are unset,
    # all /api/calendar/* routes return 503 and the auto-dispatch poller is a
    # no-op). A *dedicated* Google OAuth flow (not the Supabase Google login)
    # so we can request Calendar scopes + offline access and hold a refresh
    # token for background bot dispatch even when the user isn't active.
    google_client_id: str = ""
    google_client_secret: str = ""
    # Where Google redirects after consent — must match the Authorized
    # redirect URI registered in the Google Cloud console, and points at our
    # GET /api/calendar/callback.
    google_redirect_uri: str = ""
    # Fernet key used to encrypt Google access/refresh tokens at rest (the
    # `google_oauth_tokens` table). Generate with
    # `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
    # When unset, the token store refuses to persist tokens (raises) rather
    # than writing provider credentials in plaintext — matches the
    # operator-blind invariant the rest of the codebase enforces.
    token_enc_key: str = ""

    # In-person Record ingress (Conclave ingress mode 3: bot · upload · record).
    # Server-side orchestration of the consent plane: a recorded clip is sent to
    # FPM (diarize + identify) and the NEAR Whisper transcription-service (ASR) —
    # both behind tokens held HERE, never in the browser — then merged by timestamp
    # and ingested through the normal upload pipeline. All unset → /record returns 503.
    fpm_base_url: str = ""          # e.g. http://localhost:8000
    fpm_api_token: str = ""         # Bearer token scoped for 'diarize'
    # FPM workspace to diarize against. Empty → use the Conclave workspace_id
    # verbatim (so demo voiceprints seeded under that id are recognized).
    fpm_workspace: str = ""
    transcription_service_url: str = ""    # e.g. http://localhost:8083 (NEAR Whisper)
    transcription_service_token: str = ""  # optional bearer
    transcription_model: str = "whisper-1"

    # Migration P4 atomic cutover (R1): when True, in-person identity comes from CAPTURE's diarization
    # — Conclave sends capture's own spans to VFTE `/v1/identify-spans` (identity only). When False
    # (default), the legacy path re-diarizes via FPM `/v1/diarize`. This is the instant-rollback
    # toggle — flipping it back restores the old pipeline with no code change.
    inperson_via_capture: bool = False     # env CONCLAVE_INPERSON_VIA_CAPTURE

    # Authoritative finalizer (topology A): the DiariZen post engine (GPU, hosted). When set, the
    # finalizer-A path POSTs the recording here for the AUTHORITATIVE diarization, then feeds those spans
    # to VFTE /v1/identify-spans. Empty → fall back to capture's own (diart) spans from raw_diarization.
    # Local stack reaches the GPU box via an SSH tunnel → http://localhost:8086. Swap GPU = retarget the
    # tunnel; this URL stays put.
    diarize_url: str = ""                  # env CONCLAVE_DIARIZE_URL (e.g. http://localhost:8086)
    diarize_token: str = ""                # env CONCLAVE_DIARIZE_TOKEN (the service's bearer)

    # ── Task #16: durable job queue ──────────────────────────────────────────────────────────
    # Finalize-time diarization delivery: "blocking" (default, legacy in-process call — instant
    # rollback) vs "queue" (submit a durable Redis-Streams job; a DiariZen worker pulls it, runs
    # the engine, and POSTs the result back to /api/diarize/result). Submit needs a Redis (REDIS_URL).
    diarize_jobs: str = "blocking"         # env CONCLAVE_DIARIZE_JOBS (queue | blocking)
    # Where the DiariZen worker POSTs `{job_id, segments}` (Conclave's own externally-reachable URL).
    diarize_result_callback_url: str = ""  # env CONCLAVE_DIARIZE_RESULT_CALLBACK_URL
    # Optional bearer the worker presents to POST /api/diarize/result (best-effort auth, like the webhook).
    diarize_result_token: str = ""         # env CONCLAVE_DIARIZE_RESULT_TOKEN
    # Audio-by-reference: base URL the worker GETs the recording from (audio_ref = base + native_id),
    # served by GET /api/diarize/audio/{native_id} over CONCLAVE_AUDIO_DIR, gated by audio_fetch_token.
    audio_fetch_url: str = ""              # env CONCLAVE_AUDIO_FETCH_URL
    audio_fetch_token: str = ""            # env CONCLAVE_AUDIO_FETCH_TOKEN (service token for workers)
    # Master switch for the Conclave-internal job queue (enrich / regen / KB index+extract).
    # Off (default) → those run in-process as before; on → submitted to `conclave_jobs`, drained by
    # the in-process worker (durable across restarts). Needs REDIS_URL.
    jobs_queue: bool = False               # env CONCLAVE_JOBS_QUEUE

    # ── Task #20: contribute a meeting to Shape Rotator OS ───────────────────────────────────────
    # Arm 1 (LIVE): POST the host-approved v2 transcript to Shape OS's public anon
    # `context_submissions` inbox. The project URL + anon key are PUBLIC by design — Shape OS is a
    # public repo that ships the anon key, and RLS (INSERT-only, no read-back) is the boundary. We
    # default them to the committed prod values; override via env for a test/stub Supabase.
    # (Arm 2 — distilled readout → PR — is intentionally NOT wired: upstream moved all transcript
    # content off the public repo, so a readout PR is a no-op diff. See TASK-20 (2026-06-29 finding).)
    shapeos_supabase_url: str = "https://txjntzwksiluvqcpccpc.supabase.co"
    shapeos_anon_key: str = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InR4am50endrc2ls"
        "dXZxY3BjY3BjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODEzNzA1NzEsImV4cCI6MjA5Njk0NjU3MX0."
        "XjXEUnw3jq1E7PwIOvhr7a3OpO2lyZv6S_Hn3JqogBA"
    )
    # Safety valve for dev: when True the contribute endpoint validates + builds the payload but
    # NEVER hits the network — it returns a simulated success. Keeps dev from posting at real Shape OS.
    shapeos_contrib_dry_run: bool = False  # env CONCLAVE_SHAPEOS_CONTRIB_DRY_RUN

    model_config = {"env_prefix": "CONCLAVE_", "env_file": ".env", "extra": "ignore"}

    def record_meeting_enabled(self) -> bool:
        """True when both FPM and the transcription service are configured."""
        return bool(self.fpm_base_url and self.transcription_service_url)

    def fpm_workspace_for(self, workspace_id: str) -> str:
        """FPM workspace to diarize against for a given Conclave workspace."""
        return self.fpm_workspace or workspace_id

    def google_calendar_enabled(self) -> bool:
        """True when a dedicated Google OAuth client is configured."""
        return bool(self.google_client_id and self.google_client_secret
                    and self.google_redirect_uri)

    def llm_configured(self) -> bool:
        """True when the selected `llm_backend` can actually be reached (has a key).

        Used to skip enrichment (and avoid burning tokens / a wasted round-trip) when
        no LLM is set up. `ollama` is local and assumed available.
        """
        backend = self.llm_backend
        if backend == "ollama":
            return True
        if backend == "nearai":
            return bool(self.nearai_api_key)
        return bool(self.redpill_api_key)  # default backend


settings = Settings()


def get_llm(model: str | None = None):
    """Return the configured LangChain chat model.

    Backend is selected by `settings.llm_backend`:
      - "redpill" (default): production path; RedPill (Phala) TEE-served,
        OpenAI-compatible. Default model `google/gemma-3-27b-it`.
      - "nearai": alternate TEE backend, OpenAI-compatible.
      - "ollama": local dev; assumes Ollama is running at settings.ollama_base_url.

    model: specific model ID. Falls back to the backend's default if None.
    Skills declare their own per-node models in their own config.py.
    """
    from langchain_openai import ChatOpenAI

    backend = settings.llm_backend

    if backend == "ollama":
        # Ignore the per-call `model` arg in ollama mode: hosted model IDs
        # (e.g. "google/gemma-3-27b-it") are not valid Ollama tags and would
        # fail to load. A single env var (CONCLAVE_OLLAMA_MODEL) controls the
        # local model for every skill node.
        return ChatOpenAI(
            model=settings.ollama_model,
            api_key="ollama",  # Ollama ignores the key; ChatOpenAI requires one
            base_url=settings.ollama_base_url,
        )

    if backend == "redpill":
        return ChatOpenAI(
            model=model or settings.redpill_model,
            api_key=settings.redpill_api_key,
            base_url=settings.redpill_base_url,
        )

    # Fallback: NearAI (kept for backwards compatibility with @pytest.mark.live
    # and any caller passing a NearAI model id explicitly).
    return ChatOpenAI(
        model=model or settings.default_model,
        api_key=settings.nearai_api_key,
        base_url=settings.nearai_base_url,
    )
