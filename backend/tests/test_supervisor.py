"""Tests for the Supervisor's plan() -> validated DAG pipeline.

The Gemini call itself is mocked out (patching generate_json) so these run
instantly and deterministically -- they test the label-resolution and
validation logic, not Gemini's behavior. See scripts/smoke_gemini.py for a
real, live call against the API.
"""

import pytest

from taskos.agents import supervisor
from taskos.agents.llm import LLMMalformedOutputError
from taskos.core.models import AgentType, TaskStatus


def _mock_plan(monkeypatch, tasks: list[dict]):
    async def fake_generate_json(prompt, *, system_instruction=None):
        return tasks

    monkeypatch.setattr(supervisor, "generate_json", fake_generate_json)


# -- happy paths -------------------------------------------------------


async def test_sequential_pipeline_resolves_labels_to_real_task_ids(monkeypatch):
    _mock_plan(monkeypatch, [
        {"id": "r1", "description": "Research Anthropic", "agent": "research", "depends_on": []},
        {"id": "w1", "description": "Write summary", "agent": "writer", "depends_on": ["r1"]},
    ])

    run = await supervisor.plan("Write a summary about Anthropic")

    assert len(run.tasks) == 2
    research, writer = run.tasks
    assert research.assigned_agent is AgentType.RESEARCH
    assert writer.assigned_agent is AgentType.WRITER
    assert writer.depends_on == [research.task_id]  # label "r1" resolved to real id
    assert all(t.status is TaskStatus.PENDING for t in run.tasks)


async def test_parallel_fan_in_plan(monkeypatch):
    _mock_plan(monkeypatch, [
        {"id": "r1", "description": "Research company A", "agent": "research", "depends_on": []},
        {"id": "r2", "description": "Research company B", "agent": "research", "depends_on": []},
        {"id": "r3", "description": "Research company C", "agent": "research", "depends_on": []},
        {"id": "synth", "description": "Merge findings", "agent": "synthesis",
         "depends_on": ["r1", "r2", "r3"]},
    ])

    run = await supervisor.plan("Compare companies A, B, and C")

    assert len(run.tasks) == 4
    synth = next(t for t in run.tasks if t.assigned_agent is AgentType.SYNTHESIS)
    research_ids = {t.task_id for t in run.tasks if t.assigned_agent is AgentType.RESEARCH}
    assert set(synth.depends_on) == research_ids  # fan-in resolved correctly


async def test_plan_can_include_an_illustrator_task(monkeypatch):
    """The Supervisor accepts "illustrator" as a valid agent -- proves adding
    a new AgentType required no change to the plan-parsing logic itself,
    only the enum and the system prompt."""
    _mock_plan(monkeypatch, [
        {"id": "img", "description": "A red panda astronaut, flat vector style",
         "agent": "illustrator", "depends_on": []},
    ])

    run = await supervisor.plan("Make a picture of a red panda astronaut")

    assert len(run.tasks) == 1
    assert run.tasks[0].assigned_agent is AgentType.ILLUSTRATOR


# -- malformed output is rejected, not silently accepted ----------------


async def test_non_list_response_is_rejected(monkeypatch):
    _mock_plan(monkeypatch, {"not": "a list"})
    with pytest.raises(LLMMalformedOutputError, match="non-empty JSON array"):
        await supervisor.plan("goal")


async def test_empty_list_is_rejected(monkeypatch):
    _mock_plan(monkeypatch, [])
    with pytest.raises(LLMMalformedOutputError, match="non-empty JSON array"):
        await supervisor.plan("goal")


async def test_missing_field_is_rejected(monkeypatch):
    _mock_plan(monkeypatch, [{"id": "r1", "agent": "research", "depends_on": []}])
    with pytest.raises(LLMMalformedOutputError, match="missing id/description/agent"):
        await supervisor.plan("goal")


async def test_unknown_agent_type_is_rejected(monkeypatch):
    _mock_plan(monkeypatch, [
        {"id": "r1", "description": "do a thing", "agent": "coder", "depends_on": []},
    ])
    with pytest.raises(LLMMalformedOutputError, match="unknown agent type 'coder'"):
        await supervisor.plan("goal")


async def test_cannot_assign_task_to_supervisor(monkeypatch):
    _mock_plan(monkeypatch, [
        {"id": "r1", "description": "do a thing", "agent": "supervisor", "depends_on": []},
    ])
    with pytest.raises(LLMMalformedOutputError, match="cannot be assigned"):
        await supervisor.plan("goal")


async def test_duplicate_label_is_rejected(monkeypatch):
    _mock_plan(monkeypatch, [
        {"id": "r1", "description": "first", "agent": "research", "depends_on": []},
        {"id": "r1", "description": "second", "agent": "research", "depends_on": []},
    ])
    with pytest.raises(LLMMalformedOutputError, match="Duplicate task label"):
        await supervisor.plan("goal")


async def test_dependency_on_unknown_label_is_rejected(monkeypatch):
    _mock_plan(monkeypatch, [
        {"id": "w1", "description": "write", "agent": "writer", "depends_on": ["ghost"]},
    ])
    with pytest.raises(LLMMalformedOutputError, match="unknown label 'ghost'"):
        await supervisor.plan("goal")


async def test_cyclic_plan_is_rejected(monkeypatch):
    _mock_plan(monkeypatch, [
        {"id": "a", "description": "a", "agent": "research", "depends_on": ["b"]},
        {"id": "b", "description": "b", "agent": "research", "depends_on": ["a"]},
    ])
    with pytest.raises(LLMMalformedOutputError, match="invalid DAG"):
        await supervisor.plan("goal")
