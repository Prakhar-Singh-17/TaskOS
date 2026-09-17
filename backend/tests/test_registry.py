"""Tests for the agent dispatch registry."""

import pytest

from taskos.agents.registry import AGENT_REGISTRY, dispatch
from taskos.agents import coder, illustrator, research, synthesis, writer
from taskos.core.models import AgentType, Task

RUN_ID = "run_test"


def test_registry_maps_every_assignable_agent_type():
    assert AGENT_REGISTRY[AgentType.RESEARCH] is research.run
    assert AGENT_REGISTRY[AgentType.WRITER] is writer.run
    assert AGENT_REGISTRY[AgentType.SYNTHESIS] is synthesis.run
    assert AGENT_REGISTRY[AgentType.ILLUSTRATOR] is illustrator.run
    assert AGENT_REGISTRY[AgentType.CODER] is coder.run
    assert AgentType.SUPERVISOR not in AGENT_REGISTRY  # the supervisor plans, it isn't dispatched to


async def test_dispatch_calls_the_registered_agent_function(monkeypatch):
    called_with = {}

    async def fake_research_run(task, *, tools, store):
        called_with["task"] = task
        called_with["tools"] = tools
        called_with["store"] = store
        return "ok"

    monkeypatch.setitem(AGENT_REGISTRY, AgentType.RESEARCH, fake_research_run)
    task = Task(run_id=RUN_ID, description="x", assigned_agent=AgentType.RESEARCH)

    result = await dispatch(task, tools="fake_tools", store="fake_store")

    assert result == "ok"
    assert called_with == {"task": task, "tools": "fake_tools", "store": "fake_store"}


async def test_dispatch_raises_for_unregistered_agent_type():
    task = Task(run_id=RUN_ID, description="x", assigned_agent=AgentType.SUPERVISOR)

    with pytest.raises(ValueError, match="No agent registered for 'supervisor'"):
        await dispatch(task, tools=None, store=None)
