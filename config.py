from __future__ import annotations
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Backend selector — "nearai" (default, production TEE-served) or "ollama" (local dev).
    # Set CONCLAVE_LLM_BACKEND=ollama to route get_llm through a local Ollama daemon.
    llm_backend: str = "nearai"

    # NearAI API — all models served via NearAI confidential compute
    nearai_api_key: str = ""
    nearai_base_url: str = "https://cloud-api.near.ai/v1"
    default_model: str = "deepseek-ai/DeepSeek-V3.1"

    # Ollama (local dev) — only used when llm_backend == "ollama".
    # Default is the Conclave-tuned qwen2.5:14b-instruct variant
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
      - "nearai" (default): production path; NearAI's OpenAI-compatible endpoint
      - "ollama": local dev; assumes Ollama is running at settings.ollama_base_url

    model: specific model ID. Falls back to the backend's default if None.
    Skills declare their own per-node models in their own config.py.
    """
    from langchain_openai import ChatOpenAI

    if settings.llm_backend == "ollama":
        # Ignore the per-call `model` arg in ollama mode: NearAI model IDs
        # (e.g. "Qwen/Qwen3-30B-A3B-Instruct-2507") are not valid Ollama tags
        # and would fail to load. A single env var (CONCLAVE_OLLAMA_MODEL)
        # controls the local model for every skill node.
        return ChatOpenAI(
            model=settings.ollama_model,
            api_key="ollama",  # Ollama ignores the key; ChatOpenAI requires one
            base_url=settings.ollama_base_url,
        )

    return ChatOpenAI(
        model=model or settings.default_model,
        api_key=settings.nearai_api_key,
        base_url=settings.nearai_base_url,
    )
