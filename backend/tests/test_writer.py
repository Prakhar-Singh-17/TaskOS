"""Tests for the Writer agent.

The LLM call is faked; the store is real (MemoryStore) so these tests prove
the actual handoff mechanism -- reading a dependency's shared-state
namespace -- not just mocked plumbing.
"""

import pytest

from taskos.agents import writer
from taskos.agents.errors import MissingDependencyOutputError
from taskos.core.models import AgentType, Task
from taskos.store.memory import MemoryStore

RUN_ID = "run_test"


@pytest.fixture
async def store():
    s = MemoryStore()
    await s.connect()
    yield s
    await s.close()


def make_writer_task(depends_on: list[str]) -> Task:
    return Task(
        run_id=RUN_ID,
        description="Draft a summary",
        assigned_agent=AgentType.WRITER,
        depends_on=depends_on,
    )


async def test_drafts_from_research_findings(monkeypatch, store):
    research_task_id = "task_research1"
    await store.write_state(
        RUN_ID, research_task_id, "findings",
        {"summary": "Anthropic builds Claude and focuses on AI safety.", "sources": []},
    )

    captured_prompt = {}

    async def fake_generate_text(prompt, *, system_instruction=None):
        captured_prompt["prompt"] = prompt
        return "Anthropic is an AI safety company that builds the Claude model family."

    monkeypatch.setattr(writer, "generate_text", fake_generate_text)
    task = make_writer_task(depends_on=[research_task_id])

    draft = await writer.run(task, tools=None, store=store)

    assert draft == "Anthropic is an AI safety company that builds the Claude model family."
    assert "Anthropic builds Claude and focuses on AI safety." in captured_prompt["prompt"]

    stored = await store.read_state(RUN_ID, task.task_id)
    assert stored["draft"] == draft


async def test_drafts_from_synthesis_output_too(monkeypatch, store):
    """Writer shouldn't care whether its input came from Research or Synthesis --
    both write a dict with a "summary" key, just under a different state key."""
    synth_task_id = "task_synth1"
    await store.write_state(
        RUN_ID, synth_task_id, "synthesis",
        {"summary": "All three companies are investing heavily in AI infrastructure."},
    )

    async def fake_generate_text(prompt, *, system_instruction=None):
        return "draft based on synthesis"

    monkeypatch.setattr(writer, "generate_text", fake_generate_text)
    task = make_writer_task(depends_on=[synth_task_id])

    draft = await writer.run(task, tools=None, store=store)
    assert draft == "draft based on synthesis"


async def test_raises_when_no_dependency_has_usable_findings(store):
    task = make_writer_task(depends_on=["task_missing"])

    with pytest.raises(MissingDependencyOutputError, match="No usable findings"):
        await writer.run(task, tools=None, store=store)


async def test_raises_when_dependency_wrote_state_without_a_summary(store):
    """A dependency namespace can exist but not contain anything usable --
    e.g. it wrote some other key. That still counts as no usable findings."""
    dep_id = "task_dep1"
    await store.write_state(RUN_ID, dep_id, "some_other_key", {"not": "a summary"})
    task = make_writer_task(depends_on=[dep_id])

    with pytest.raises(MissingDependencyOutputError):
        await writer.run(task, tools=None, store=store)
