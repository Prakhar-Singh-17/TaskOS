"""Seeds a real failure+retry run into the configured store (Mongo if
MONGODB_URI is set, matching whatever the running API server is using) so it
shows up in the actual dashboard -- lets you visually confirm the retry
badge and attempt history render correctly, not just that the mechanism
works (scripts/smoke_failure.py already proves that against MemoryStore).

Forces the search MCP server's mock-mode empty-result marker so the first
attempt is guaranteed to fail, exactly like smoke_failure.py -- the
difference is purely which store this writes to.

    python -m scripts.smoke_dashboard_retry

Then open the dashboard and select the run it prints.
"""

from __future__ import annotations

import os

os.environ["TASKOS_SEARCH_MODE"] = "mock"  # must be set before any taskos import

import asyncio  # noqa: E402

from taskos.core.events import EventBus  # noqa: E402
from taskos.core.models import AgentType, Run, Task  # noqa: E402
from taskos.core.runner import run_graph  # noqa: E402
from taskos.mcp_client.client import MCPClientManager  # noqa: E402
from taskos.store.factory import create_store  # noqa: E402


async def main() -> None:
    task = Task(
        run_id="",  # filled in once the Run exists
        description="__no_results__ this query is deliberately unsearchable nonsense",
        assigned_agent=AgentType.RESEARCH,
        max_attempts=3,
    )
    run = Run(goal="[demo] Failure + retry visualization check", tasks=[])
    task.run_id = run.run_id
    run.tasks = [task]

    store = await create_store()
    events = EventBus(store)
    await store.create_run(run)

    async with MCPClientManager() as tools:
        result = await run_graph(run, tools=tools, store=store, events=events)

    print(f"Seeded run: {result.run_id}  (status: {result.status.value})")
    print("Open the dashboard and select it from Runs to see the retry badge/attempts.")
    await store.close()


if __name__ == "__main__":
    asyncio.run(main())
