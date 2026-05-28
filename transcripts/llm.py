"""Shared LLM reliability layer — JSON parse + repair retry + access guard.

`IMPLEMENTATION_PLAN.md` §G4 / §H C6. The **only** caller of
``config.get_llm`` in the transcripts pipeline; everything that wants
structured output from a model goes through ``invoke_json``. This is also
where provider errors get mapped to a typed ``LLMUnavailable`` so the
backfill pass (``enrich_pending``) can skip-and-continue past a credit
wall or a network blip instead of crashing the batch.

Failure-mode discipline:

- Bad / missing JSON on the first attempt → one repair re-prompt asking
  explicitly for a single JSON object.
- Still bad → ``LLMOutputError`` (caller decides; ``enrich_pending``
  treats this as a per-session skip).
- ``required_keys`` missing from the parsed dict → ``LLMOutputError``.
- 402 / connection / DNS / timeout from the provider → ``LLMUnavailable``.

The bracket-matched JSON extractor is moved here from ``enrich.py`` (the
pre-refactor version stays in ``enrich._extract_json_object`` until C8
rewires enrich on top of this module).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Iterable, Optional

from langchain_core.messages import HumanMessage, SystemMessage

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------

class LLMUnavailable(Exception):
    """Provider-side failure — the model couldn't even be reached.

    Maps to: 402 (credit cap), connection refused, DNS failure, timeout,
    auth errors. Callers (e.g. ``enrich_pending``) treat this as a soft
    failure: skip this session, continue the batch.
    """


class LLMOutputError(Exception):
    """The model responded but its output wasn't usable.

    Maps to: unparseable JSON after one repair attempt, or schema check
    failure (``required_keys`` missing). Callers treat this as a *per-call*
    failure — the model is fine, this specific call needs a different
    prompt or retry strategy.
    """


# ---------------------------------------------------------------------------
# Bracket-matched JSON extractor (moved from enrich.py)
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> Optional[dict]:
    """Pull the first balanced ``{...}`` object out of an LLM response.

    Tolerant of reasoning prefixes, markdown fences, and trailing prose
    because real models do all three. Returns ``None`` on no-match or
    parse failure — caller decides whether to retry/raise.
    """
    if not text:
        return None
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\" and in_str:
            escape = True
            continue
        if c == '"':
            in_str = not in_str
        if not in_str:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        return None
    return None


# ---------------------------------------------------------------------------
# Provider-error mapping
# ---------------------------------------------------------------------------

_UNAVAILABLE_HINTS = (
    "connection",
    "timeout",
    "timed out",
    "name or service",
    "nodename nor servname",
    "credit",
    "quota",
    "rate limit",
    "unauthorized",
    "402",
    "401",
    "429",
    "503",
)


def _is_unavailable(exc: BaseException) -> bool:
    """Heuristic: does this exception mean 'the provider isn't reachable'?

    We try the typed ``openai.APIStatusError`` first (status code 402/429/
    401/503), then fall back to string sniffing the message — which catches
    raw ``ConnectionError`` from Ollama, DNS failures, and NearAI's
    pre-langchain error wrappers consistently.
    """
    try:  # openai's typed errors carry a status_code
        from openai import APIStatusError, APIConnectionError, APITimeoutError, AuthenticationError, RateLimitError
        if isinstance(exc, (APIConnectionError, APITimeoutError, AuthenticationError, RateLimitError)):
            return True
        if isinstance(exc, APIStatusError) and exc.status_code in {401, 402, 403, 429, 503}:
            return True
    except ImportError:
        pass
    msg = str(exc).lower()
    return any(hint in msg for hint in _UNAVAILABLE_HINTS) or isinstance(exc, ConnectionError)


def _is_bad_request(exc: BaseException) -> bool:
    """A 400-class rejection — the provider refused this specific request.

    Common causes: prompt + completion budget exceeds the model's effective
    context window (this happens on repair retries when the echoed bad
    output bloats the input), content-filter trip, or malformed payload.
    Treated as ``LLMOutputError`` so ``enrich_pending`` skips the session
    rather than crashing the whole batch.
    """
    try:
        from openai import BadRequestError
        if isinstance(exc, BadRequestError):
            return True
    except ImportError:
        pass
    msg = str(exc).lower()
    return "400" in msg and ("bad request" in msg or "upstream" in msg or "context" in msg)


def _get_llm(model: Optional[str] = None):
    """Construct the configured chat model, mapping construction errors.

    Construction itself rarely throws (ChatOpenAI just stores config), but
    we still wrap it so a missing-API-key surface shows up as
    ``LLMUnavailable`` and not an opaque pydantic validation.
    """
    try:
        from config import get_llm
        return get_llm(model)
    except Exception as exc:  # noqa: BLE001
        if _is_unavailable(exc):
            raise LLMUnavailable(str(exc)) from exc
        raise


# ---------------------------------------------------------------------------
# Public: invoke_json
# ---------------------------------------------------------------------------

_REPAIR_PROMPT = (
    "Your previous response did not parse as JSON. Reply with ONE valid JSON "
    "object that matches the schema requested above. No prose, no markdown, "
    "no code fences — just the raw JSON object."
)


def invoke_json(
    messages: list,
    *,
    llm: Any = None,
    model: Optional[str] = None,
    required_keys: Iterable[str] = (),
    max_retries: int = 1,
) -> dict:
    """Call the chat model and return a parsed, schema-checked JSON dict.

    On parse failure, re-prompt **once** asking for valid JSON (the only
    repair strategy in Phase 1 — `BUILD_PLAN.md` List B "LLM JSON
    reliability" minimal-now). Provider errors become ``LLMUnavailable``;
    parser/schema errors become ``LLMOutputError``.

    Pass ``llm=`` to inject a fake in tests; otherwise the configured
    backend (``config.get_llm(model)``) is used.
    """
    chat = llm if llm is not None else _get_llm(model)
    required = tuple(required_keys)

    # First attempt.
    try:
        response = chat.invoke(messages)
    except Exception as exc:  # noqa: BLE001 — provider can throw anything
        if _is_unavailable(exc):
            raise LLMUnavailable(str(exc)) from exc
        if _is_bad_request(exc):
            raise LLMOutputError(f"provider rejected the request (400): {exc}") from exc
        raise

    raw = _response_text(response)
    data = _extract_json(raw)
    if data is not None and _has_required(data, required):
        return data

    # One repair retry.
    if max_retries < 1:
        raise LLMOutputError(_describe_failure(data, raw, required))

    repair_messages = list(messages) + [
        # Echo the model's bad output back so it can see what to fix.
        HumanMessage(content=raw),
        SystemMessage(content=_REPAIR_PROMPT),
    ]
    try:
        response2 = chat.invoke(repair_messages)
    except Exception as exc:  # noqa: BLE001
        if _is_unavailable(exc):
            raise LLMUnavailable(str(exc)) from exc
        if _is_bad_request(exc):
            # Repair retries echo the bad output back as a HumanMessage,
            # which can push the combined input past the model's effective
            # ctx. Surface as output error so the session is skipped.
            raise LLMOutputError(f"provider rejected the repair retry (400): {exc}") from exc
        raise

    raw2 = _response_text(response2)
    data2 = _extract_json(raw2)
    if data2 is not None and _has_required(data2, required):
        return data2

    log.warning("invoke_json: repair retry also failed; raising LLMOutputError")
    raise LLMOutputError(_describe_failure(data2, raw2, required))


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _response_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    return str(content)


def _has_required(data: dict, required: tuple[str, ...]) -> bool:
    if not required:
        return True
    return all(k in data for k in required)


def _describe_failure(data: Optional[dict], raw: str, required: tuple[str, ...]) -> str:
    if data is None:
        head = raw[:200].replace("\n", " ")
        return f"could not extract JSON from response (first 200 chars: {head!r})"
    missing = [k for k in required if k not in data]
    return f"response JSON missing required keys: {missing}"
