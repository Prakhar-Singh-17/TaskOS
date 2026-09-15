"""Tests for the Synthesis agent -- the DAG's fan-in point.

The LLM call is faked; the store is real (MemoryStore) so these prove the
actual merge mechanism: reading multiple dependency namespaces and combining
their summaries and sources.
"""

import pytest

from taskos.agents import synthesis
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


def make_synthesis_task(depends_on: list[str]) -> Task:
    return Task(
        run_id=RUN_ID,
        description="Merge findings on companies A, B, C",
        assigned_agent=AgentType.SYNTHESIS,
        depends_on=depends_on,
    )


async def test_merges_findings_and_sources_from_three_research_tasks(monkeypatch, store):
    for name, company in [("r_a", "A"), ("r_b", "B"), ("r_c", "C")]:
        await store.write_state(
            RUN_ID, name, "findings",
            {
                "summary": f"Company {company} focuses on cloud AI infrastructure.",
                "sources": [{"title": f"{company} homepage", "url": f"https://{company}.example"}],
            },
        )

    captured_prompt = {}

    async def fake_generate_text(prompt, *, system_instruction=None):
        captured_prompt["prompt"] = prompt
        return "All three companies are investing heavily in cloud AI infrastructure."

    monkeypatch.setattr(synthesis, "generate_text", fake_generate_text)
    task = make_synthesis_task(depends_on=["r_a", "r_b", "r_c"])

    result = await synthesis.run(task, tools=None, store=store)

    assert result["summary"] == "All three companies are investing heavily in cloud AI infrastructure."
    assert len(result["sources"]) == 3
    assert {s["title"] for s in result["sources"]} == {"A homepage", "B homepage", "C homepage"}
    for company in ("A", "B", "C"):
        assert f"Company {company} focuses on cloud AI infrastructure." in captured_prompt["prompt"]

    stored = await store.read_state(RUN_ID, task.task_id)
    assert stored["synthesis"] == result


async def test_raises_when_no_dependency_has_usable_findings(store):
    task = make_synthesis_task(depends_on=["missing_1", "missing_2"])

    with pytest.raises(MissingDependencyOutputError, match="No usable findings"):
        await synthesis.run(task, tools=None, store=store)


async def test_tolerates_a_partial_set_of_usable_findings(monkeypatch, store):
    """If one research branch failed upstream and left nothing, Synthesis
    should still merge whatever the others produced rather than fail outright."""
    await store.write_state(RUN_ID, "r_a", "findings", {"summary": "A is doing fine.", "sources": []})
    # r_b intentionally has nothing written -- e.g. it failed and got blocked

    async def fake_generate_text(prompt, *, system_instruction=None):
        return "Summary based on partial findings."

    monkeypatch.setattr(synthesis, "generate_text", fake_generate_text)
    task = make_synthesis_task(depends_on=["r_a", "r_b"])

    result = await synthesis.run(task, tools=None, store=store)
    assert result["summary"] == "Summary based on partial findings."
