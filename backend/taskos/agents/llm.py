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
from google.genai import types

from taskos.config import settings

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30


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


async def _call(prompt: str, *, system_instruction: str | None, json_mode: bool) -> str:
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
    except Exception as exc:  # API/network error from the SDK
        raise LLMError(f"{type(exc).__name__}: {exc}") from exc

    text = (response.text or "").strip()
    if not text:
        raise LLMMalformedOutputError("Empty response from model")
    return text


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
