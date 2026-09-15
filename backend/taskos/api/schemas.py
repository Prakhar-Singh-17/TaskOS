"""Request/response shapes for the HTTP API. Kept separate from core/models.py
on purpose: these describe the wire format, not the domain -- e.g. the DAG
"layers" field below is a view convenience for the dashboard, not part of the
Run/Task domain model itself."""

from __future__ import annotations

from pydantic import BaseModel


class CreateRunRequest(BaseModel):
    goal: str


class CreateRunResponse(BaseModel):
    runId: str
