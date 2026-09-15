"""Storage interface for runs, tasks, events, and shared agent state.

Two implementations satisfy this: MongoDB (`mongo.MongoStore`) for real use,
and an in-process dict store (`memory.MemoryStore`) so the system runs and
tests without a database.

Tasks live in their own collection rather than embedded in the run document,
and shared state is keyed by (run_id, namespace, key). Concurrent agents
therefore only ever write to disjoint documents -- parallel branches of the DAG
cannot clobber each other.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from taskos.core.models import Event, Run, Task


class StateStore(ABC):
    """Shared state store backing a TaskOS run."""

    # -- lifecycle ---------------------------------------------------------

    @abstractmethod
    async def connect(self) -> None:
        """Open the backing connection and ensure indexes exist."""

    @abstractmethod
    async def close(self) -> None:
        """Release the backing connection."""

    # -- runs --------------------------------------------------------------

    @abstractmethod
    async def create_run(self, run: Run) -> None:
        """Persist a new run and all of its tasks."""

    @abstractmethod
    async def get_run(self, run_id: str) -> Run | None:
        """Load a run with its tasks attached, or None if unknown."""

    @abstractmethod
    async def list_runs(self, limit: int = 25) -> list[Run]:
        """Most recent runs first, without tasks attached."""

    @abstractmethod
    async def update_run(self, run_id: str, **fields: Any) -> None:
        """Patch top-level fields on a run (status, final_output, ...)."""

    # -- tasks -------------------------------------------------------------

    @abstractmethod
    async def save_task(self, task: Task) -> None:
        """Insert or replace a single task document."""

    @abstractmethod
    async def get_tasks(self, run_id: str) -> list[Task]:
        """All tasks for a run, in creation order."""

    # -- events ------------------------------------------------------------

    @abstractmethod
    async def append_event(self, event: Event) -> None:
        """Append one entry to the observability log."""

    @abstractmethod
    async def get_events(self, run_id: str, limit: int = 1000) -> list[Event]:
        """Event log for a run, oldest first."""

    # -- shared state ------------------------------------------------------

    @abstractmethod
    async def write_state(
        self, run_id: str, namespace: str, key: str, value: Any
    ) -> None:
        """Write one value into a namespace (usually a task id or agent id)."""

    @abstractmethod
    async def read_state(self, run_id: str, namespace: str) -> dict[str, Any]:
        """Every key/value written under one namespace."""

    @abstractmethod
    async def read_namespaces(
        self, run_id: str, namespaces: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Read several namespaces at once -- how a task collects the output
        of its dependencies before running."""

    @abstractmethod
    async def read_all_state(self, run_id: str) -> dict[str, dict[str, Any]]:
        """The whole shared state for a run, grouped by namespace."""
