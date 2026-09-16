"""Core schema: runs, DAG tasks, and observability events.

The task graph is a DAG from day one -- `depends_on` is a list even where a
plan happens to be sequential -- so parallel execution needs no schema change.
Events carry an untyped `payload` dict so new result types (code, images,
tables) flow to the dashboard without touching this file.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class TaskStatus(str, Enum):
    PENDING = "pending"      # waiting on dependencies
    READY = "ready"          # dependencies satisfied, queued
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"        # exhausted its retries
    BLOCKED = "blocked"      # an upstream dependency failed
    CANCELLED = "cancelled"


TERMINAL_STATUSES = {
    TaskStatus.DONE,
    TaskStatus.FAILED,
    TaskStatus.BLOCKED,
    TaskStatus.CANCELLED,
}


class RunStatus(str, Enum):
    PLANNING = "planning"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"      # finished, but some tasks failed
    FAILED = "failed"


class AgentType(str, Enum):
    SUPERVISOR = "supervisor"
    RESEARCH = "research"
    WRITER = "writer"
    SYNTHESIS = "synthesis"
    ILLUSTRATOR = "illustrator"


class FailureKind(str, Enum):
    """Why a task attempt failed -- drives the retry strategy."""

    TOOL_FAILURE = "tool_failure"        # MCP call errored / transport broke
    EMPTY_RESULT = "empty_result"        # tool worked, found nothing -> reword
    MALFORMED_OUTPUT = "malformed_output"  # agent returned unparseable output
    TIMEOUT = "timeout"
    LLM_ERROR = "llm_error"
    DEPENDENCY_FAILED = "dependency_failed"  # never retried
    UNKNOWN = "unknown"


RETRYABLE_FAILURES = {
    FailureKind.TOOL_FAILURE,
    FailureKind.EMPTY_RESULT,
    FailureKind.MALFORMED_OUTPUT,
    FailureKind.TIMEOUT,
    FailureKind.LLM_ERROR,
}


class EventType(str, Enum):
    RUN_CREATED = "run_created"
    PLAN_CREATED = "plan_created"
    TASK_READY = "task_ready"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_RETRYING = "task_retrying"
    TASK_BLOCKED = "task_blocked"
    TOOL_CALL = "tool_call"
    AGENT_MESSAGE = "agent_message"
    STATE_WRITTEN = "state_written"
    RUN_COMPLETED = "run_completed"


class Attempt(BaseModel):
    """One execution attempt of a task -- the retry history the dashboard shows."""

    number: int
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    ok: bool = False
    failure_kind: FailureKind | None = None
    error: str | None = None
    note: str | None = None  # e.g. "retrying with reworded query"


class Task(BaseModel):
    # Both Task and Run get mutated via plain attribute assignment throughout
    # the runner/store (e.g. `task.status = TaskStatus.RUNNING`, or a store's
    # generic `setattr(run, field, value)` for a partial update). Without
    # validate_assignment, Pydantic only validates at construction time --
    # assigning a raw string to an enum field would silently store the wrong
    # type instead of coercing or rejecting it.
    model_config = ConfigDict(validate_assignment=True)

    task_id: str = Field(default_factory=lambda: new_id("task"))
    run_id: str
    description: str
    assigned_agent: AgentType
    depends_on: list[str] = Field(default_factory=list)

    status: TaskStatus = TaskStatus.PENDING
    attempts: list[Attempt] = Field(default_factory=list)
    max_attempts: int = 3

    result: Any = None
    error: str | None = None
    failure_kind: FailureKind | None = None

    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)

    @property
    def retries_left(self) -> int:
        return max(0, self.max_attempts - self.attempt_count)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def duration_ms(self) -> int | None:
        if self.started_at is None or self.finished_at is None:
            return None
        return int((self.finished_at - self.started_at).total_seconds() * 1000)


class Run(BaseModel):
    model_config = ConfigDict(validate_assignment=True)  # see Task's comment above

    run_id: str = Field(default_factory=lambda: new_id("run"))
    goal: str
    status: RunStatus = RunStatus.PLANNING
    tasks: list[Task] = Field(default_factory=list)
    final_output: Any = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None


class Event(BaseModel):
    """One entry in the observability log.

    `payload` is deliberately unconstrained: the dashboard renders it
    generically, so a new agent or tool needs no frontend change.
    """

    event_id: str = Field(default_factory=lambda: new_id("evt"))
    run_id: str
    timestamp: datetime = Field(default_factory=utcnow)
    event_type: EventType
    agent_id: str | None = None
    task_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_wire(self) -> dict[str, Any]:
        """camelCase shape pushed over Socket.io to the dashboard."""
        return {
            "eventId": self.event_id,
            "runId": self.run_id,
            "timestamp": self.timestamp.isoformat(),
            "eventType": self.event_type.value,
            "agentId": self.agent_id,
            "taskId": self.task_id,
            "payload": self.payload,
        }
