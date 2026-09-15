"""Scheduling and validation rules for the task DAG."""

import pytest

from taskos.core.graph import InvalidGraphError, TaskGraph
from taskos.core.models import AgentType, Task, TaskStatus

RUN = "run_test"


def task(
    task_id: str,
    *,
    depends_on: list[str] | None = None,
    agent: AgentType = AgentType.RESEARCH,
) -> Task:
    return Task(
        task_id=task_id,
        run_id=RUN,
        description=f"do {task_id}",
        assigned_agent=agent,
        depends_on=depends_on or [],
    )


def fan_in_graph() -> TaskGraph:
    """Three parallel research tasks feeding one synthesis task."""
    return TaskGraph(
        [
            task("r1"),
            task("r2"),
            task("r3"),
            task("syn", depends_on=["r1", "r2", "r3"], agent=AgentType.SYNTHESIS),
        ]
    )


# -- validation ------------------------------------------------------------


def test_valid_dag_passes_validation():
    fan_in_graph().validate()


def test_unknown_dependency_is_rejected():
    graph = TaskGraph([task("a", depends_on=["ghost"])])
    with pytest.raises(InvalidGraphError, match="unknown task"):
        graph.validate()


def test_self_dependency_is_rejected():
    graph = TaskGraph([task("a", depends_on=["a"])])
    with pytest.raises(InvalidGraphError, match="depends on itself"):
        graph.validate()


def test_cycle_is_rejected():
    graph = TaskGraph([task("a", depends_on=["b"]), task("b", depends_on=["a"])])
    with pytest.raises(InvalidGraphError, match="Cycle detected"):
        graph.validate()


def test_duplicate_task_ids_are_rejected():
    graph = TaskGraph([task("a"), task("a")])
    with pytest.raises(InvalidGraphError, match="Duplicate task id"):
        graph.validate()


# -- scheduling ------------------------------------------------------------


def test_only_independent_tasks_are_ready_initially():
    graph = fan_in_graph()
    assert sorted(t.task_id for t in graph.ready_tasks()) == ["r1", "r2", "r3"]


def test_dependent_task_becomes_ready_once_all_deps_are_done():
    graph = fan_in_graph()
    for tid in ("r1", "r2"):
        graph.get(tid).status = TaskStatus.DONE
    assert [t.task_id for t in graph.ready_tasks()] == ["r3"]

    graph.get("r3").status = TaskStatus.DONE
    assert [t.task_id for t in graph.ready_tasks()] == ["syn"]


def test_running_tasks_are_not_rescheduled():
    graph = fan_in_graph()
    graph.get("r1").status = TaskStatus.RUNNING
    assert sorted(t.task_id for t in graph.ready_tasks()) == ["r2", "r3"]


def test_failed_dependency_blocks_downstream_task():
    graph = fan_in_graph()
    graph.get("r1").status = TaskStatus.FAILED
    graph.get("r2").status = TaskStatus.DONE
    graph.get("r3").status = TaskStatus.DONE
    assert [t.task_id for t in graph.newly_blocked_tasks()] == ["syn"]
    assert graph.ready_tasks() == []


def test_completion_and_failure_reporting():
    graph = fan_in_graph()
    assert not graph.is_complete()
    for t in graph.tasks:
        t.status = TaskStatus.DONE
    assert graph.is_complete()
    assert not graph.has_failures()


def test_layers_expose_parallelism():
    assert fan_in_graph().layers() == [["r1", "r2", "r3"], ["syn"]]


def test_layers_for_sequential_pipeline():
    graph = TaskGraph(
        [
            task("research"),
            task("write", depends_on=["research"], agent=AgentType.WRITER),
        ]
    )
    assert graph.layers() == [["research"], ["write"]]


def test_dependents_lookup():
    graph = fan_in_graph()
    assert [t.task_id for t in graph.dependents_of("r1")] == ["syn"]
    assert graph.dependents_of("syn") == []
