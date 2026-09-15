"""Manual, live smoke test for the sequential Research -> Writer pipeline.

Proves v1's use case #1 ("sequential pipeline: Research -> Write, proves
handoff + tool use") end-to-end against real services: Gemini plans and
summarizes, Tavily searches, MemoryStore carries the handoff between agents.

Not part of the pytest suite -- it costs real API quota and isn't
deterministic. Run by hand:

    python -m scripts.smoke_pipeline
"""

from __future__ import annotations

import asyncio

from taskos.agents.registry import dispatch
from taskos.agents import supervisor
from taskos.core.graph import TaskGraph
from taskos.core.models import TaskStatus
from taskos.mcp_client.client import MCPClientManager
from taskos.store.memory import MemoryStore


async def main() -> None:
    goal = "Write a short, factual overview of what Anthropic does"
    print(f"GOAL: {goal}\n")

    run = await supervisor.plan(goal)
    graph = TaskGraph(run.tasks)
    print("PLAN:")
    for task in run.tasks:
        print(f"  [{task.assigned_agent.value:9s}] {task.task_id}  deps={task.depends_on}")

    store = MemoryStore()
    await store.connect()
    await store.create_run(run)

    async with MCPClientManager() as tools:
        # Walk the DAG in dependency layers -- correct even though this
        # particular plan happens to be a simple chain.
        for layer in graph.layers():
            for task_id in layer:
                task = graph.get(task_id)
                print(f"\n--- running {task.task_id} ({task.assigned_agent.value}) ---")
                result = await dispatch(task, tools=tools, store=store)
                task.status = TaskStatus.DONE
                task.result = result
                await store.save_task(task)
                preview = str(result)[:300]
                print(preview)

    final_writer_task = next(t for t in run.tasks if t.assigned_agent.value == "writer")
    print("\n=== FINAL DRAFT ===")
    print(final_writer_task.result)

    await store.close()


if __name__ == "__main__":
    asyncio.run(main())
