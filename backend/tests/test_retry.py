"""Tests for failure classification and retry preparation (core/retry.py)."""

import pytest

from taskos.agents import research
from taskos.agents.errors import EmptyResultError, MissingDependencyOutputError, ToolCallError
from taskos.agents.llm import LLMError, LLMMalformedOutputError, LLMTimeoutError
from taskos.core.models import AgentType, FailureKind, RETRYABLE_FAILURES, Task
from taskos.core.retry import classify_failure, prepare_retry

RUN_ID = "run_test"


# -- classify_failure ----------------------------------------------------


@pytest.mark.parametrize("exc,expected", [
    (EmptyResultError("nothing found"), FailureKind.EMPTY_RESULT),
    (MissingDependencyOutputError("no upstream output"), FailureKind.EMPTY_RESULT),
    (ToolCallError("tool broke"), FailureKind.TOOL_FAILURE),
    (LLMTimeoutError("timed out"), FailureKind.TIMEOUT),
    (LLMMalformedOutputError("bad json"), FailureKind.MALFORMED_OUTPUT),
    (LLMError("generic API error"), FailureKind.LLM_ERROR),
    (ValueError("something unrelated broke"), FailureKind.UNKNOWN),
])
def test_classify_failure_maps_exception_types(exc, expected):
    assert classify_failure(exc) is expected


def test_every_classifiable_kind_except_dependency_and_unknown_is_retryable():
    """Sanity check on the model's own RETRYABLE_FAILURES set: everything
    classify_failure can produce from a real agent exception should be
    retryable, except UNKNOWN (unclassified) and DEPENDENCY_FAILED (which
    classify_failure never produces -- that's set directly by the runner
    when a task is blocked, not raised as an exception)."""
    classifiable = {
        classify_failure(exc) for exc in [
            EmptyResultError(""), ToolCallError(""), LLMTimeoutError(""),
            LLMMalformedOutputError(""), LLMError(""),
        ]
    }
    assert classifiable <= RETRYABLE_FAILURES
    assert FailureKind.UNKNOWN not in RETRYABLE_FAILURES
    assert FailureKind.DEPENDENCY_FAILED not in RETRYABLE_FAILURES


# -- prepare_retry ---------------------------------------------------------


def make_research_task(description: str = "original query") -> Task:
    return Task(run_id=RUN_ID, description=description, assigned_agent=AgentType.RESEARCH)


async def test_empty_result_on_research_rewords_the_query(monkeypatch):
    async def fake_reword_query(original: str) -> str:
        return f"broader version of: {original}"

    monkeypatch.setattr(research, "reword_query", fake_reword_query)
    task = make_research_task("very specific niche query")

    note = await prepare_retry(task, FailureKind.EMPTY_RESULT)

    assert task.description == "broader version of: very specific niche query"
    assert "reworded query" in note


async def test_non_empty_result_failure_leaves_research_task_unchanged():
    task = make_research_task("original query")

    note = await prepare_retry(task, FailureKind.TOOL_FAILURE)

    assert task.description == "original query"
    assert note is None


async def test_empty_result_on_non_research_agent_leaves_task_unchanged():
    """Only Research has a meaningful "reword" action for EMPTY_RESULT --
    a Writer/Synthesis task with no usable findings just retries as-is."""
    task = Task(run_id=RUN_ID, description="draft something", assigned_agent=AgentType.WRITER)

    note = await prepare_retry(task, FailureKind.EMPTY_RESULT)

    assert task.description == "draft something"
    assert note is None
