"""Thin wrapper around the Gemini API, shared by every agent.

One job: send a prompt, get back parsed JSON or plain text. Every agent
(Supervisor, Research, Writer, Synthesis) calls through here instead of
touching the google-genai SDK directly -- so there is exactly one place that
knows how to talk to the LLM, and exactly one place that classifies an LLM
failure as a timeout, an API error, or malformed output.
"""

from __future__ import annotations

import asyncio
import json
import logging

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from taskos.config import settings

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30

# Gemini's free tier returns 503 ("model overloaded") often enough in practice
# that a single call isn't reliable. This retries only transient failures
# (5xx server errors, and our own client-side timeout) with a short backoff --
# a 4xx ClientError (bad request, auth) fails immediately since retrying it
# would never succeed. This is separate from the task-level retry the DAG
# runner does later: this just makes one LLM call resilient to a network
# blip, the runner's retry handles a whole task failing for domain reasons
# (e.g. an empty search result).
TRANSIENT_RETRY_ATTEMPTS = 3
TRANSIENT_RETRY_BACKOFF_SECONDS = 2.0


class LLMError(Exception):
    """Base class for LLM call failures."""


class LLMTimeoutError(LLMError):
    """The model did not respond within the timeout."""


class LLMMalformedOutputError(LLMError):
    """The model responded, but not with usable content (empty or not valid JSON)."""


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not settings.gemini_api_key.strip():
            raise LLMError("GEMINI_API_KEY is not set")
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


async def _call_once(prompt: str, *, system_instruction: str | None, json_mode: bool) -> str:
    client = _get_client()
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json" if json_mode else None,
    )
    try:
        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
                config=config,
            ),
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise LLMTimeoutError(
            f"Gemini did not respond within {DEFAULT_TIMEOUT_SECONDS}s"
        ) from exc
    except genai_errors.ClientError as exc:  # 4xx: bad request/auth, never retry
        raise LLMError(f"{type(exc).__name__}: {exc}") from exc
    except Exception as exc:  # includes ServerError (5xx) -- may be retried
        raise LLMError(f"{type(exc).__name__}: {exc}") from exc

    text = (response.text or "").strip()
    if not text:
        raise LLMMalformedOutputError("Empty response from model")
    return text


async def _call(prompt: str, *, system_instruction: str | None, json_mode: bool) -> str:
    """Call Gemini, retrying transient failures (server overload, timeout)
    a few times with backoff before giving up."""
    last_error: LLMError | None = None
    for attempt in range(1, TRANSIENT_RETRY_ATTEMPTS + 1):
        try:
            return await _call_once(prompt, system_instruction=system_instruction, json_mode=json_mode)
        except LLMTimeoutError as exc:
            last_error = exc
        except LLMError as exc:
            if not isinstance(exc.__cause__, genai_errors.ServerError):
                raise  # not transient (bad request, auth, malformed output) -- fail fast
            last_error = exc

        if attempt < TRANSIENT_RETRY_ATTEMPTS:
            wait = TRANSIENT_RETRY_BACKOFF_SECONDS * attempt
            logger.warning(
                "Gemini call failed (attempt %d/%d): %s -- retrying in %.0fs",
                attempt, TRANSIENT_RETRY_ATTEMPTS, last_error, wait,
            )
            await asyncio.sleep(wait)

    assert last_error is not None
    raise last_error


async def generate_text(prompt: str, *, system_instruction: str | None = None) -> str:
    """Call Gemini and return the raw text response."""
    return await _call(prompt, system_instruction=system_instruction, json_mode=False)


async def generate_json(prompt: str, *, system_instruction: str | None = None):
    """Call Gemini in JSON mode and return the parsed result.

    Raises LLMMalformedOutputError if the response isn't valid JSON -- callers
    treat that the same way they'd treat a malformed agent output, i.e. as a
    retryable failure (see FailureKind.MALFORMED_OUTPUT).
    """
    text = await _call(prompt, system_instruction=system_instruction, json_mode=True)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMMalformedOutputError(f"Response was not valid JSON: {exc}") from exc
