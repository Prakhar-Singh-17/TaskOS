"""Maps an AgentType to the agent module that executes it.

The task runner dispatches through here instead of an if/elif chain -- adding
a new agent (e.g. Synthesis in step 5) means adding one line to AGENT_REGISTRY,
nothing else in the runner changes.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from taskos.agents import research, writer
from taskos.core.models import AgentType, Task
from taskos.mcp_client.client import MCPClientManager
from taskos.store.base import StateStore

AgentFn = Callable[..., Awaitable[Any]]

# Every agent function shares the signature (task, *, tools, store) -> result,
# even if a given agent doesn't need one of those (e.g. Writer ignores `tools`).
AGENT_REGISTRY: dict[AgentType, AgentFn] = {
    AgentType.RESEARCH: research.run,
    AgentType.WRITER: writer.run,
}


async def dispatch(task: Task, *, tools: MCPClientManager, store: StateStore) -> Any:
    """Run the agent assigned to a task."""
    agent_fn = AGENT_REGISTRY.get(task.assigned_agent)
    if agent_fn is None:
        raise ValueError(f"No agent registered for '{task.assigned_agent.value}'")
    return await agent_fn(task, tools=tools, store=store)
