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
