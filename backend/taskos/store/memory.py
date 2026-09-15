"""In-process implementation of StateStore.

Used when MONGODB_URI is unset and by the test suite. Everything is deep-copied
on the way in and out so callers cannot mutate stored state by accident -- the
same isolation the Mongo store gets for free.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from copy import deepcopy
from typing import Any

from taskos.core.models import Event, Run, Task
from taskos.store.base import StateStore


class MemoryStore(StateStore):
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._tasks: dict[str, dict[str, Task]] = defaultdict(dict)
        self._events: dict[str, list[Event]] = defaultdict(list)
        self._state: dict[str, dict[str, dict[str, Any]]] = defaultdict(
            lambda: defaultdict(dict)
        )
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    # -- runs --------------------------------------------------------------

    async def create_run(self, run: Run) -> None:
        async with self._lock:
            stored = run.model_copy(deep=True)
            tasks = stored.tasks
            stored.tasks = []
            self._runs[run.run_id] = stored
            for task in tasks:
                self._tasks[run.run_id][task.task_id] = task

    async def get_run(self, run_id: str) -> Run | None:
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            hydrated = run.model_copy(deep=True)
            hydrated.tasks = [
                t.model_copy(deep=True) for t in self._tasks[run_id].values()
            ]
            return hydrated

    async def list_runs(self, limit: int = 25) -> list[Run]:
        async with self._lock:
            runs = sorted(
                self._runs.values(), key=lambda r: r.created_at, reverse=True
            )
            return [r.model_copy(deep=True) for r in runs[:limit]]

    async def update_run(self, run_id: str, **fields: Any) -> None:
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            for key, value in fields.items():
                setattr(run, key, deepcopy(value))

    # -- tasks -------------------------------------------------------------

    async def save_task(self, task: Task) -> None:
        async with self._lock:
            self._tasks[task.run_id][task.task_id] = task.model_copy(deep=True)

    async def get_tasks(self, run_id: str) -> list[Task]:
        async with self._lock:
            return [t.model_copy(deep=True) for t in self._tasks[run_id].values()]

    # -- events ------------------------------------------------------------

    async def append_event(self, event: Event) -> None:
        async with self._lock:
            self._events[event.run_id].append(event.model_copy(deep=True))

    async def get_events(self, run_id: str, limit: int = 1000) -> list[Event]:
        async with self._lock:
            return [e.model_copy(deep=True) for e in self._events[run_id][:limit]]

    # -- shared state ------------------------------------------------------

    async def write_state(
        self, run_id: str, namespace: str, key: str, value: Any
    ) -> None:
        async with self._lock:
            self._state[run_id][namespace][key] = deepcopy(value)

    async def read_state(self, run_id: str, namespace: str) -> dict[str, Any]:
        async with self._lock:
            return deepcopy(self._state[run_id].get(namespace, {}))

    async def read_namespaces(
        self, run_id: str, namespaces: list[str]
    ) -> dict[str, dict[str, Any]]:
        async with self._lock:
            run_state = self._state[run_id]
            return {ns: deepcopy(run_state.get(ns, {})) for ns in namespaces}

    async def read_all_state(self, run_id: str) -> dict[str, dict[str, Any]]:
        async with self._lock:
            return deepcopy(dict(self._state[run_id]))
