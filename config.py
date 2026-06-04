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

    # Supabase auth (optional — if unset, /auth/* endpoints return 503 and /register is the fallback)
    supabase_url: str = ""
    supabase_anon_key: str = ""

    model_config = {"env_prefix": "CONCLAVE_", "env_file": ".env", "extra": "ignore"}


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
