"""The observability event bus.

Every meaningful thing that happens during a run -- a task starting, a tool
being called, a retry, completion -- becomes an Event (core/models.py) with a
free-form `payload` dict. This module has exactly one job: take an Event,
persist it, and hand it to whoever is listening.

Nothing in the runner or an agent needs to know that a websocket exists. The
API layer (api/app.py) is the only thing that subscribes a callback which
pushes events to Socket.io -- the runner just calls `events.emit(...)`. This
is what makes the dashboard "generic": it renders whatever payload shape an
event carries, and the core system never imports anything web-related.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from taskos.core.models import Event, EventType, Task
from taskos.mcp_client.client import MCPClientManager, ToolResult
from taskos.store.base import StateStore

logger = logging.getLogger(__name__)

Subscriber = Callable[[Event], Awaitable[None]]


class EventBus:
    def __init__(self, store: StateStore) -> None:
        self._store = store
        self._subscribers: list[Subscriber] = []

    def subscribe(self, callback: Subscriber) -> None:
        """Register a callback invoked with every event after it's persisted."""
        self._subscribers.append(callback)

    async def emit(self, event: Event) -> None:
        await self._store.append_event(event)
        for callback in self._subscribers:
            try:
                await callback(event)
            except Exception:
                # A broken dashboard connection must never break the run.
                logger.exception("Event subscriber raised for event %s", event.event_type.value)


class ObservedTools:
    """Wraps an MCPClientManager so every tool call also emits a TOOL_CALL
    event, without any agent needing to know observability exists.

    An agent's code (e.g. research.py calling `tools.call_tool("search", ...)`)
    is completely unchanged -- the runner just hands it one of these instead
    of the raw MCPClientManager when dispatching a task.
    """

    def __init__(self, tools: MCPClientManager, events: EventBus, task: Task) -> None:
        self._tools = tools
        self._events = events
        self._task = task

    async def call_tool(self, name: str, params: dict[str, Any] | None = None) -> ToolResult:
        result = await self._tools.call_tool(name, params)
        await self._events.emit(Event(
            run_id=self._task.run_id,
            task_id=self._task.task_id,
            agent_id=self._task.assigned_agent.value,
            event_type=EventType.TOOL_CALL,
            payload=result.to_event_payload(),
        ))
        return result
