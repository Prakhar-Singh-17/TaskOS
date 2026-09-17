"""Agent-level error types.

These are distinct from the LLMError family in llm.py: they cover an agent's
own work failing (a tool call, a missing handoff), not just the LLM call.
The task runner (step 6) catches these and classifies them into a
FailureKind to decide whether -- and how -- to retry.
"""

from __future__ import annotations


class AgentError(Exception):
    """Base class for agent execution failures."""


class ToolCallError(AgentError):
    """An MCP tool call the agent depended on failed outright."""


class EmptyResultError(AgentError):
    """A tool call succeeded but returned nothing useful.

    Distinct from ToolCallError on purpose: this is the case your v1 failure
    demo targets (retry with a reworded query), not a broken tool.
    """


class MissingDependencyOutputError(AgentError):
    """None of this task's dependencies left usable output in shared state."""


class CodeExecutionError(AgentError):
    """Generated code ran (the sandbox call itself succeeded) but exited with
    an error -- a compile error, an exception, a non-zero exit status.

    Distinct from ToolCallError the same way EmptyResultError is: the tool
    call worked fine, the *result* is what needs fixing.
    """
