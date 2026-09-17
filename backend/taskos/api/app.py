"""HTTP + realtime API for the TaskOS dashboard.

FastAPI serves the REST endpoints (submit a goal, list/inspect runs);
Socket.io broadcasts every event on the EventBus to connected dashboard
clients as it happens. The two share one ASGI app (`asgi_app`, served by
uvicorn) so they run on the same port.

CORS and Socket.io allow only origins listed in ALLOWED_ORIGINS -- there is
no wildcard fallback, so this must be set (locally and in production) or
nothing can reach the API cross-origin. See .env.example.

Run with:  uvicorn taskos.api.app:asgi_app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import socketio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from taskos.config import settings
from taskos.core.events import EventBus
from taskos.core.graph import TaskGraph
from taskos.core.models import new_id
from taskos.core.orchestrator import execute_goal
from taskos.mcp_client.client import MCPClientManager
from taskos.store.factory import create_store
from taskos.api.schemas import CreateRunRequest, CreateRunResponse

logger = logging.getLogger(__name__)

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=settings.allowed_origins)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = await create_store()
    tools = MCPClientManager()
    await tools.start()
    events = EventBus(store)
    events.subscribe(_broadcast_to_dashboard)

    app.state.store = store
    app.state.tools = tools
    app.state.events = events
    logger.info("TaskOS API ready")
    try:
        yield
    finally:
        await tools.stop()
        await store.close()


async def _broadcast_to_dashboard(event) -> None:
    await sio.emit("task_event", event.to_wire())


app = FastAPI(title="TaskOS API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.allowed_origins, allow_methods=["*"], allow_headers=["*"],
)


@app.post("/api/runs", response_model=CreateRunResponse)
async def create_run(request: CreateRunRequest) -> CreateRunResponse:
    """Kick off a goal. Returns immediately with a run id -- the goal is
    planned and executed in the background; connect via Socket.io (or poll
    GET /api/runs/{id}) to watch it progress."""
    if not request.goal.strip():
        raise HTTPException(422, "goal must not be empty")

    run_id = new_id("run")
    asyncio.create_task(
        execute_goal(
            request.goal, run_id=run_id,
            tools=app.state.tools, store=app.state.store, events=app.state.events,
        )
    )
    return CreateRunResponse(runId=run_id)


@app.get("/api/runs")
async def list_runs():
    runs = await app.state.store.list_runs()
    return [
        {"runId": r.run_id, "goal": r.goal, "status": r.status.value, "createdAt": r.created_at}
        for r in runs
    ]


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    run = await app.state.store.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"No such run: {run_id}")

    layers = TaskGraph(run.tasks).layers() if run.tasks else []
    return {
        "runId": run.run_id,
        "goal": run.goal,
        "status": run.status.value,
        "error": run.error,
        "createdAt": run.created_at,
        "finishedAt": run.finished_at,
        "finalOutput": run.final_output,
        "layers": layers,
        "tasks": [_task_to_wire(t) for t in run.tasks],
    }


@app.post("/api/runs/{run_id}/tasks/{task_id}/run-code")
async def run_drafted_code(run_id: str, task_id: str):
    """Manually execute a Coder task's drafted-but-unverified code.

    The one interactive action in TaskOS that happens after a run has
    already finished: Coder sometimes writes correct code but skips running
    it (needs a live database/API/credentials the sandbox can't provide --
    see coder.py's NOTE: marker). This lets the user try running it anyway,
    on demand. Deliberately not persisted back onto the task/run -- this is
    a one-off "try it" action, not part of the recorded pipeline history.
    """
    run = await app.state.store.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"No such run: {run_id}")
    task = next((t for t in run.tasks if t.task_id == task_id), None)
    if task is None:
        raise HTTPException(404, f"No such task: {task_id}")

    code = task.result.get("code") if isinstance(task.result, dict) else None
    if not code or code.get("stdout") is not None:
        raise HTTPException(400, "This task has no unexecuted code draft to run")

    tool_result = await app.state.tools.call_tool(
        "execute_code", {"code": code["source"], "language": code["language"]}
    )
    if not tool_result.ok:
        return {"ok": False, "message": tool_result.error or "execute_code tool call failed"}

    output = tool_result.content
    if not output.get("exitOk"):
        return {"ok": False, "message": output.get("stderr") or "code exited with an error"}

    return {"ok": True, "stdout": output.get("stdout", "")}


@app.get("/api/runs/{run_id}/events")
async def get_run_events(run_id: str):
    events = await app.state.store.get_events(run_id)
    return [e.to_wire() for e in events]


@app.get("/healthz")
async def health_check():
    """Liveness probe for Render/uptime monitors -- deliberately does no
    work (no store/tool calls) so it stays fast even if a dependency is slow."""
    return {"status": "ok"}


@app.get("/api/tools")
async def list_tools():
    """The MCP tool registry currently available to agents -- exists so the
    dashboard can show tool capability without hardcoding a tool list."""
    return app.state.tools.describe_tools()


def _task_to_wire(task) -> dict:
    return {
        "taskId": task.task_id,
        "description": task.description,
        "assignedAgent": task.assigned_agent.value,
        "dependsOn": task.depends_on,
        "status": task.status.value,
        "failureKind": task.failure_kind.value if task.failure_kind else None,
        "error": task.error,
        "result": task.result,
        "attempts": [
            {
                "number": a.number,
                "ok": a.ok,
                "failureKind": a.failure_kind.value if a.failure_kind else None,
                "error": a.error,
                "note": a.note,
                "startedAt": a.started_at,
                "finishedAt": a.finished_at,
            }
            for a in task.attempts
        ],
        "startedAt": task.started_at,
        "finishedAt": task.finished_at,
        "durationMs": task.duration_ms,
    }


asgi_app = socketio.ASGIApp(sio, app)
