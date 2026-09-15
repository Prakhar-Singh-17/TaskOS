"""Tests for the agent dispatch registry."""

import pytest

from taskos.agents.registry import AGENT_REGISTRY, dispatch
from taskos.agents import research, writer
from taskos.core.models import AgentType, Task

RUN_ID = "run_test"


def test_registry_maps_research_and_writer():
    assert AGENT_REGISTRY[AgentType.RESEARCH] is research.run
    assert AGENT_REGISTRY[AgentType.WRITER] is writer.run


def test_synthesis_is_not_registered_yet():
    """Synthesis lands in step 5 -- until then, dispatch must fail loudly
    rather than silently doing nothing."""
    assert AgentType.SYNTHESIS not in AGENT_REGISTRY


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
    task = Task(run_id=RUN_ID, description="x", assigned_agent=AgentType.SYNTHESIS)

    with pytest.raises(ValueError, match="No agent registered for 'synthesis'"):
        await dispatch(task, tools=None, store=None)
