"""MongoDB implementation of StateStore (pymongo's native async client).

Collection layout:
    runs    one document per run (goal, status, final output)
    tasks   one document per task, keyed by (run_id, task_id)
    events  append-only observability log
    state   shared agent state, keyed by (run_id, namespace, key)

Tasks and state values are separate documents, so two agents running in
parallel branches of the DAG never write to the same document.
"""

from __future__ import annotations

import logging
from datetime import timezone
from typing import Any

from pymongo import AsyncMongoClient, ASCENDING, DESCENDING, ReturnDocument

from taskos.core.models import Event, Run, Task
from taskos.store.base import StateStore

logger = logging.getLogger(__name__)

NO_ID = {"_id": 0}


class MongoStore(StateStore):
    def __init__(self, uri: str, database: str = "taskos") -> None:
        self._uri = uri
        self._database = database
        self._client: AsyncMongoClient | None = None

    # -- lifecycle ---------------------------------------------------------

    async def connect(self) -> None:
        if self._client is not None:
            return
        # tz_aware=True: BSON always stores datetimes as UTC, but pymongo's
        # default is to hand them back as naive Python datetimes (tzinfo=None).
        # A naive value serializes to JSON with no UTC marker (no "Z"/"+00:00"),
        # and JavaScript's Date parser then reads that as *local browser time*
        # -- silently shifting every timestamp by the viewer's UTC offset. Hit
        # in production: run.createdAt came back naive, so the frontend's
        # elapsed-time calculation (comparing it against the correctly-UTC
        # Date.now()) was off by exactly the browser's timezone offset.
        self._client = AsyncMongoClient(
            self._uri, serverSelectionTimeoutMS=8000, tz_aware=True, tzinfo=timezone.utc
        )
        await self._client.admin.command("ping")
        await self._ensure_indexes()
        logger.info("Connected to MongoDB database %r", self._database)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    @property
    def _db(self):
        if self._client is None:
            raise RuntimeError("MongoStore.connect() has not been called")
        return self._client[self._database]

    async def _ensure_indexes(self) -> None:
        db = self._db
        await db.runs.create_index([("run_id", ASCENDING)], unique=True)
        await db.runs.create_index([("created_at", DESCENDING)])
        await db.tasks.create_index(
            [("run_id", ASCENDING), ("task_id", ASCENDING)], unique=True
        )
        await db.events.create_index([("run_id", ASCENDING), ("timestamp", ASCENDING)])
        await db.state.create_index(
            [("run_id", ASCENDING), ("namespace", ASCENDING), ("key", ASCENDING)],
            unique=True,
        )

    # -- runs --------------------------------------------------------------

    async def create_run(self, run: Run) -> None:
        document = run.model_dump()
        tasks = document.pop("tasks", [])
        await self._db.runs.insert_one(document)
        if tasks:
            await self._db.tasks.insert_many(tasks)

    async def get_run(self, run_id: str) -> Run | None:
        document = await self._db.runs.find_one({"run_id": run_id}, NO_ID)
        if document is None:
            return None
        document["tasks"] = [t.model_dump() for t in await self.get_tasks(run_id)]
        return Run.model_validate(document)

    async def list_runs(self, limit: int = 25) -> list[Run]:
        cursor = (
            self._db.runs.find({}, NO_ID).sort("created_at", DESCENDING).limit(limit)
        )
        return [Run.model_validate(doc) async for doc in cursor]

    async def update_run(self, run_id: str, **fields: Any) -> None:
        if not fields:
            return
        await self._db.runs.update_one({"run_id": run_id}, {"$set": fields})

    # -- tasks -------------------------------------------------------------

    async def save_task(self, task: Task) -> None:
        await self._db.tasks.find_one_and_replace(
            {"run_id": task.run_id, "task_id": task.task_id},
            task.model_dump(),
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

    async def get_tasks(self, run_id: str) -> list[Task]:
        cursor = self._db.tasks.find({"run_id": run_id}, NO_ID).sort(
            "created_at", ASCENDING
        )
        return [Task.model_validate(doc) async for doc in cursor]

    # -- events ------------------------------------------------------------

    async def append_event(self, event: Event) -> None:
        await self._db.events.insert_one(event.model_dump())

    async def get_events(self, run_id: str, limit: int = 1000) -> list[Event]:
        cursor = (
            self._db.events.find({"run_id": run_id}, NO_ID)
            .sort("timestamp", ASCENDING)
            .limit(limit)
        )
        return [Event.model_validate(doc) async for doc in cursor]

    # -- shared state ------------------------------------------------------

    async def write_state(
        self, run_id: str, namespace: str, key: str, value: Any
    ) -> None:
        await self._db.state.update_one(
            {"run_id": run_id, "namespace": namespace, "key": key},
            {"$set": {"value": value}},
            upsert=True,
        )

    async def read_state(self, run_id: str, namespace: str) -> dict[str, Any]:
        cursor = self._db.state.find({"run_id": run_id, "namespace": namespace}, NO_ID)
        return {doc["key"]: doc["value"] async for doc in cursor}

    async def read_namespaces(
        self, run_id: str, namespaces: list[str]
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {ns: {} for ns in namespaces}
        if not namespaces:
            return result
        cursor = self._db.state.find(
            {"run_id": run_id, "namespace": {"$in": namespaces}}, NO_ID
        )
        async for doc in cursor:
            result[doc["namespace"]][doc["key"]] = doc["value"]
        return result

    async def read_all_state(self, run_id: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        cursor = self._db.state.find({"run_id": run_id}, NO_ID)
        async for doc in cursor:
            result.setdefault(doc["namespace"], {})[doc["key"]] = doc["value"]
        return result
