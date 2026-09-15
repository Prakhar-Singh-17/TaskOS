"""Top-level entry point: goal in, executed Run out.

Ties together the pieces built in steps 3-6 -- Supervisor, the state store,
the event bus, and the DAG runner -- into the one function the API layer
calls when a user submits a goal. Nothing in here is new logic; it's wiring.
"""

from __future__ import annotations

import logging

from taskos.agents import supervisor
from taskos.agents.llm import LLMMalformedOutputError
from taskos.core.events import EventBus
from taskos.core.graph import TaskGraph
from taskos.core.models import Event, EventType, Run, RunStatus
from taskos.core.runner import run_graph
from taskos.mcp_client.client import MCPClientManager
from taskos.store.base import StateStore

logger = logging.getLogger(__name__)


async def execute_goal(
    goal: str,
    *,
    tools: MCPClientManager,
    store: StateStore,
    events: EventBus,
    run_id: str | None = None,
) -> Run:
    """Plan `goal` into a task DAG, persist it, run it to completion.

    Always returns a Run -- even a planning failure produces one with
    status=FAILED and no tasks, so callers (the API) never need a separate
    error path just because the Supervisor couldn't produce a usable plan.

    `run_id`, if given, lets a caller (the API) know the run's id before this
    coroutine finishes -- it creates the Run row up front and returns
    immediately with the id, then runs the goal in the background.
    """
    run_kwargs = {"goal": goal, "status": RunStatus.PLANNING}
    if run_id:
        run_kwargs["run_id"] = run_id
    run = Run(**run_kwargs)
    await store.create_run(run)
    await events.emit(Event(run_id=run.run_id, event_type=EventType.RUN_CREATED, payload={"goal": goal}))

    try:
        planned = await supervisor.plan(goal)
    except LLMMalformedOutputError as exc:
        logger.warning("Planning failed for run %s: %s", run.run_id, exc)
        run.status = RunStatus.FAILED
        run.error = f"Planning failed: {exc}"
        await store.update_run(run.run_id, status=run.status.value, error=run.error)
        await events.emit(Event(
            run_id=run.run_id, event_type=EventType.RUN_COMPLETED,
            payload={"status": run.status.value, "error": run.error},
        ))
        return run

    # Re-home the Supervisor's tasks onto the run_id already persisted above.
    for task in planned.tasks:
        task.run_id = run.run_id
    run.tasks = planned.tasks
    run.status = RunStatus.RUNNING
    for task in run.tasks:
        await store.save_task(task)
    await store.update_run(run.run_id, status=run.status.value)

    await events.emit(Event(
        run_id=run.run_id, event_type=EventType.PLAN_CREATED,
        payload={
            "tasks": [
                {"taskId": t.task_id, "description": t.description,
                 "agent": t.assigned_agent.value, "dependsOn": t.depends_on}
                for t in run.tasks
            ],
            "layers": TaskGraph(run.tasks).layers(),
        },
    ))

    return await run_graph(run, tools=tools, store=store, events=events)
