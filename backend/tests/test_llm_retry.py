"""Tests for the transient-failure retry inside the LLM wrapper.

Mocks _call_once directly so these run instantly (no real sleep, no network)
and prove the retry/backoff/give-up logic in isolation.
"""

from unittest.mock import AsyncMock

import pytest
from google.genai import errors as genai_errors

from taskos.agents import llm


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Don't actually wait out the backoff in tests."""
    monkeypatch.setattr(llm.asyncio, "sleep", AsyncMock())


def make_server_error() -> llm.LLMError:
    """An LLMError wrapping a ServerError, as _call_once would raise it."""
    cause = genai_errors.ServerError(503, {"error": {"message": "overloaded"}})
    err = llm.LLMError("ServerError: overloaded")
    err.__cause__ = cause
    return err


async def test_succeeds_on_first_try_without_retrying(monkeypatch):
    call_once = AsyncMock(return_value="ok")
    monkeypatch.setattr(llm, "_call_once", call_once)

    result = await llm._call("prompt", system_instruction=None, json_mode=False)

    assert result == "ok"
    assert call_once.call_count == 1


async def test_retries_transient_server_error_then_succeeds(monkeypatch):
    call_once = AsyncMock(side_effect=[make_server_error(), "ok"])
    monkeypatch.setattr(llm, "_call_once", call_once)

    result = await llm._call("prompt", system_instruction=None, json_mode=False)

    assert result == "ok"
    assert call_once.call_count == 2


async def test_gives_up_after_max_attempts(monkeypatch):
    call_once = AsyncMock(side_effect=[make_server_error() for _ in range(5)])
    monkeypatch.setattr(llm, "_call_once", call_once)

    with pytest.raises(llm.LLMError):
        await llm._call("prompt", system_instruction=None, json_mode=False)

    assert call_once.call_count == llm.TRANSIENT_RETRY_ATTEMPTS


async def test_retries_timeout_as_transient(monkeypatch):
    call_once = AsyncMock(side_effect=[llm.LLMTimeoutError("timed out"), "ok"])
    monkeypatch.setattr(llm, "_call_once", call_once)

    result = await llm._call("prompt", system_instruction=None, json_mode=False)

    assert result == "ok"
    assert call_once.call_count == 2


async def test_non_transient_error_fails_immediately_without_retrying(monkeypatch):
    """A 4xx ClientError (bad request, auth) or malformed output should never
    be retried -- retrying it can't ever succeed."""
    non_transient = llm.LLMError("ClientError: 400 bad request")
    non_transient.__cause__ = genai_errors.ClientError(400, {"error": {"message": "bad"}})
    call_once = AsyncMock(side_effect=non_transient)
    monkeypatch.setattr(llm, "_call_once", call_once)

    with pytest.raises(llm.LLMError, match="ClientError"):
        await llm._call("prompt", system_instruction=None, json_mode=False)

    assert call_once.call_count == 1
