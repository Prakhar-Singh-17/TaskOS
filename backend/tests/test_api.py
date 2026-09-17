"""Tests for the HTTP API.

`create_store` is patched to always hand out a fresh MemoryStore, regardless
of what MONGODB_URI is set to in .env -- these tests must stay fast, offline,
and independent of your Atlas cluster being reachable. `execute_goal` is
patched too, so submitting a run never makes a real Gemini/Tavily call.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from taskos.api import app as app_module
from taskos.core.models import AgentType, Attempt, Event, EventType, FailureKind, Run, RunStatus, Task
from taskos.store.memory import MemoryStore


@pytest.fixture
def client(monkeypatch):
    shared_store = MemoryStore()

    async def fake_create_store():
        await shared_store.connect()
        return shared_store

    monkeypatch.setattr(app_module, "create_store", fake_create_store)

    with TestClient(app_module.asgi_app) as c:
        c.store = shared_store  # convenience handle for seeding data directly
        yield c


def test_list_tools_returns_every_registered_tool(client):
    response = client.get("/api/tools")
    assert response.status_code == 200
    names = {t["name"] for t in response.json()}
    assert names == {"search", "generate_image", "execute_code"}


def test_get_unknown_run_is_404(client):
    response = client.get("/api/runs/run_does_not_exist")
    assert response.status_code == 404


def _seed_coder_task(client, code: dict) -> Task:
    run = Run(goal="write me some code", status=RunStatus.COMPLETED)
    task = Task(run_id=run.run_id, description="write it", assigned_agent=AgentType.CODER)
    task.result = {"summary": "Drafted code for: write it", "code": code}
    task.status = "done"
    run.tasks = [task]
    asyncio.run(client.store.create_run(run))
    return task


def test_run_drafted_code_executes_an_unexecuted_draft(client):
    task = _seed_coder_task(client, {
        "source": "print(1)", "language": "python", "stdout": None, "note": "needs a live database",
    })

    response = client.post(f"/api/runs/{task.run_id}/tasks/{task.task_id}/run-code")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "mock mode" in body["stdout"]  # TASKOS_CODE_MODE=mock for the whole suite


def test_run_drafted_code_404s_for_unknown_run(client):
    response = client.post("/api/runs/run_does_not_exist/tasks/task_x/run-code")
    assert response.status_code == 404


def test_run_drafted_code_404s_for_unknown_task(client):
    task = _seed_coder_task(client, {
        "source": "print(1)", "language": "python", "stdout": None, "note": "needs a live database",
    })

    response = client.post(f"/api/runs/{task.run_id}/tasks/task_does_not_exist/run-code")

    assert response.status_code == 404


def test_run_drafted_code_400s_when_already_executed(client):
    task = _seed_coder_task(client, {
        "source": "print(1)", "language": "python", "stdout": "1\n", "note": None,
    })

    response = client.post(f"/api/runs/{task.run_id}/tasks/{task.task_id}/run-code")

    assert response.status_code == 400


def test_create_run_returns_immediately_with_a_run_id(client, monkeypatch):
    started = {}

    async def fake_execute_goal(goal, *, tools, store, events, run_id=None):
        started["goal"] = goal
        started["run_id"] = run_id
        return Run(run_id=run_id, goal=goal, status=RunStatus.COMPLETED)

    monkeypatch.setattr(app_module, "execute_goal", fake_execute_goal)

    response = client.post("/api/runs", json={"goal": "Write about Anthropic"})

    assert response.status_code == 200
    run_id = response.json()["runId"]
    assert run_id.startswith("run_")

    # The background task is scheduled but this endpoint must not block on it.
    asyncio.run(asyncio.sleep(0.05))
    assert started["goal"] == "Write about Anthropic"
    assert started["run_id"] == run_id


def test_create_run_rejects_an_empty_goal(client):
    response = client.post("/api/runs", json={"goal": "   "})
    assert response.status_code == 422


def test_list_runs_returns_seeded_runs(client):
    run = Run(goal="a seeded run", status=RunStatus.COMPLETED)
    asyncio.run(client.store.create_run(run))

    response = client.get("/api/runs")

    assert response.status_code == 200
    body = response.json()
    assert any(r["runId"] == run.run_id and r["goal"] == "a seeded run" for r in body)


def test_get_run_includes_tasks_and_layers(client):
    run = Run(goal="compare things", status=RunStatus.COMPLETED)
    r1 = Task(run_id=run.run_id, description="research", assigned_agent=AgentType.RESEARCH)
    w1 = Task(run_id=run.run_id, description="write", assigned_agent=AgentType.WRITER,
              depends_on=[r1.task_id])
    run.tasks = [r1, w1]
    asyncio.run(client.store.create_run(run))

    response = client.get(f"/api/runs/{run.run_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["goal"] == "compare things"
    assert {t["taskId"] for t in body["tasks"]} == {r1.task_id, w1.task_id}
    assert body["layers"] == [[r1.task_id], [w1.task_id]]


def test_get_run_includes_final_output(client):
    run = Run(goal="compare things", status=RunStatus.COMPLETED)
    run.final_output = {"text": "# Final Report\n\nAnthropic builds Claude.", "sources": []}
    asyncio.run(client.store.create_run(run))

    body = client.get(f"/api/runs/{run.run_id}").json()

    assert body["finalOutput"]["text"].startswith("# Final Report")


def test_get_run_reflects_a_status_update_made_through_the_store(client):
    """Regression test: GET /api/runs/{id} crashed with AttributeError after
    store.update_run(status="completed") left a raw string on the Run model
    instead of a RunStatus enum. Exercise that exact path, through the API."""
    run = Run(goal="will be completed", status=RunStatus.RUNNING)
    asyncio.run(client.store.create_run(run))
    asyncio.run(client.store.update_run(run.run_id, status="completed"))

    response = client.get(f"/api/runs/{run.run_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_get_run_serializes_retry_history_for_the_dashboard(client):
    """The dashboard's retry badge and expanded attempt list (TaskNode.jsx)
    read task.attempts[].{ok,failureKind,note} -- verify the API actually
    produces that exact shape for a task that failed once then recovered."""
    run = Run(goal="retry demo", status=RunStatus.COMPLETED)
    task = Task(run_id=run.run_id, description="research it", assigned_agent=AgentType.RESEARCH)
    task.attempts = [
        Attempt(number=1, ok=False, failure_kind=FailureKind.EMPTY_RESULT,
                error="No search results for query: 'x'",
                note="reworded query: 'x' -> 'broader x'"),
        Attempt(number=2, ok=True),
    ]
    task.status = "done"
    run.tasks = [task]
    asyncio.run(client.store.create_run(run))

    body = client.get(f"/api/runs/{run.run_id}").json()

    wire_task = body["tasks"][0]
    assert len(wire_task["attempts"]) == 2
    assert wire_task["attempts"][0] == {
        "number": 1, "ok": False, "failureKind": "empty_result",
        "error": "No search results for query: 'x'",
        "note": "reworded query: 'x' -> 'broader x'",
        "startedAt": wire_task["attempts"][0]["startedAt"],  # timestamp, just check it's present
        "finishedAt": None,
    }
    assert wire_task["attempts"][1]["ok"] is True
    assert wire_task["attempts"][1]["failureKind"] is None


def test_get_run_events_returns_the_event_log(client):
    run = Run(goal="test events", status=RunStatus.COMPLETED)
    asyncio.run(client.store.create_run(run))
    asyncio.run(client.store.append_event(
        Event(run_id=run.run_id, event_type=EventType.RUN_CREATED, payload={"goal": run.goal})
    ))

    response = client.get(f"/api/runs/{run.run_id}/events")

    assert response.status_code == 200
    events = response.json()
    assert len(events) == 1
    assert events[0]["eventType"] == "run_created"
