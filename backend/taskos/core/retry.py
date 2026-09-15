"""Failure classification and retry preparation.

Two jobs, kept separate from the runner's scheduling logic:

1. classify_failure() turns an exception an agent raised into a FailureKind
   (see core/models.py) -- this is what the runner uses to decide whether a
   failure is worth retrying at all.
2. prepare_retry() adjusts a task before its next attempt, when the failure
   kind calls for it. Right now there's exactly one such adjustment, matching
   the v1 failure scenario: a Research task that found nothing gets its query
   reworded by Gemini before trying again. Everything else just retries the
   same task unchanged.
"""

from __future__ import annotations

from taskos.agents.errors import EmptyResultError, MissingDependencyOutputError, ToolCallError
from taskos.agents.llm import LLMError, LLMMalformedOutputError, LLMTimeoutError
from taskos.core.models import AgentType, FailureKind, Task


def classify_failure(exc: BaseException) -> FailureKind:
    """Map an exception raised by an agent into a FailureKind.

    Order matters: check the more specific exception types before the base
    LLMError, since LLMTimeoutError/LLMMalformedOutputError subclass it.
    """
    if isinstance(exc, EmptyResultError):
        return FailureKind.EMPTY_RESULT
    if isinstance(exc, MissingDependencyOutputError):
        # Nothing usable to work with -- same recovery bucket as an empty
        # search result, even though it isn't a search at all.
        return FailureKind.EMPTY_RESULT
    if isinstance(exc, ToolCallError):
        return FailureKind.TOOL_FAILURE
    if isinstance(exc, LLMTimeoutError):
        return FailureKind.TIMEOUT
    if isinstance(exc, LLMMalformedOutputError):
        return FailureKind.MALFORMED_OUTPUT
    if isinstance(exc, LLMError):
        return FailureKind.LLM_ERROR
    return FailureKind.UNKNOWN


async def prepare_retry(task: Task, failure_kind: FailureKind) -> str | None:
    """Adjust `task` in place before its next attempt.

    Returns a short human-readable note describing what changed (stored on
    the Attempt record), or None if nothing was adjusted.
    """
    if task.assigned_agent is AgentType.RESEARCH and failure_kind is FailureKind.EMPTY_RESULT:
        from taskos.agents import research  # local import: avoids a cycle with registry

        old_query = task.description
        task.description = await research.reword_query(old_query)
        return f"reworded query: {old_query!r} -> {task.description!r}"

    return None
