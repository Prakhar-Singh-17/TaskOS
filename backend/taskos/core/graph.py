"""DAG validation and scheduling logic over a set of tasks.

Pure and synchronous -- no I/O, no agents -- so the scheduling rules are
testable on their own. The task runner asks this class what may run next.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Iterable

from taskos.core.models import TERMINAL_STATUSES, Task, TaskStatus

FAILED_STATUSES = {TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.CANCELLED}


class InvalidGraphError(ValueError):
    """The supervisor produced a plan that is not a runnable DAG."""


class TaskGraph:
    def __init__(self, tasks: Iterable[Task]) -> None:
        self.tasks: list[Task] = list(tasks)
        self._by_id: dict[str, Task] = {t.task_id: t for t in self.tasks}
        self._dependents: dict[str, list[str]] = defaultdict(list)
        for task in self.tasks:
            for dep in task.depends_on:
                self._dependents[dep].append(task.task_id)

    # -- access ------------------------------------------------------------

    def __len__(self) -> int:
        return len(self.tasks)

    def __contains__(self, task_id: object) -> bool:
        return task_id in self._by_id

    def get(self, task_id: str) -> Task:
        try:
            return self._by_id[task_id]
        except KeyError:
            raise KeyError(f"No such task: {task_id}") from None

    def dependencies_of(self, task_id: str) -> list[Task]:
        return [self._by_id[dep] for dep in self.get(task_id).depends_on]

    def dependents_of(self, task_id: str) -> list[Task]:
        return [self._by_id[tid] for tid in self._dependents.get(task_id, [])]

    # -- validation --------------------------------------------------------

    def validate(self) -> None:
        """Raise InvalidGraphError unless this is a well-formed DAG."""
        seen: set[str] = set()
        for task in self.tasks:
            if task.task_id in seen:
                raise InvalidGraphError(f"Duplicate task id: {task.task_id}")
            seen.add(task.task_id)

        for task in self.tasks:
            if task.task_id in task.depends_on:
                raise InvalidGraphError(f"Task {task.task_id} depends on itself")
            for dep in task.depends_on:
                if dep not in self._by_id:
                    raise InvalidGraphError(
                        f"Task {task.task_id} depends on unknown task {dep!r}"
                    )

        cycle = self._find_cycle()
        if cycle:
            raise InvalidGraphError("Cycle detected: " + " -> ".join(cycle))

    def _find_cycle(self) -> list[str] | None:
        """Kahn's algorithm; whatever never drains is inside a cycle."""
        indegree = {t.task_id: len(t.depends_on) for t in self.tasks}
        queue = deque(tid for tid, deg in indegree.items() if deg == 0)
        visited = 0
        while queue:
            current = queue.popleft()
            visited += 1
            for dependent in self._dependents.get(current, []):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    queue.append(dependent)

        if visited == len(self.tasks):
            return None
        stuck = sorted(tid for tid, deg in indegree.items() if deg > 0)
        return stuck + [stuck[0]]

    # -- scheduling --------------------------------------------------------

    def ready_tasks(self) -> list[Task]:
        """Pending tasks whose dependencies have all completed successfully."""
        ready = []
        for task in self.tasks:
            if task.status is not TaskStatus.PENDING:
                continue
            deps = self.dependencies_of(task.task_id)
            if all(dep.status is TaskStatus.DONE for dep in deps):
                ready.append(task)
        return ready

    def newly_blocked_tasks(self) -> list[Task]:
        """Pending tasks that can never run because an upstream task failed."""
        return [
            task
            for task in self.tasks
            if task.status is TaskStatus.PENDING
            and any(
                dep.status in FAILED_STATUSES
                for dep in self.dependencies_of(task.task_id)
            )
        ]

    def is_complete(self) -> bool:
        return all(task.status in TERMINAL_STATUSES for task in self.tasks)

    def has_failures(self) -> bool:
        return any(task.status in FAILED_STATUSES for task in self.tasks)

    def layers(self) -> list[list[str]]:
        """Group task ids into dependency levels -- each layer may run in
        parallel. Used by the dashboard to lay the graph out."""
        indegree = {t.task_id: len(t.depends_on) for t in self.tasks}
        frontier = sorted(tid for tid, deg in indegree.items() if deg == 0)
        layers: list[list[str]] = []
        while frontier:
            layers.append(frontier)
            nxt: set[str] = set()
            for tid in frontier:
                for dependent in self._dependents.get(tid, []):
                    indegree[dependent] -= 1
                    if indegree[dependent] == 0:
                        nxt.add(dependent)
            frontier = sorted(nxt)
        return layers
