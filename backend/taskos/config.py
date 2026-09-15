"""Central configuration, loaded from the environment (.env at repo root)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "")
    try:
        return int(raw) if raw.strip() else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # LLM
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    )

    # Tools
    tavily_api_key: str = field(default_factory=lambda: os.getenv("TAVILY_API_KEY", ""))
    search_mode: str = field(
        default_factory=lambda: os.getenv("TASKOS_SEARCH_MODE", "live").lower()
    )

    # State store
    mongodb_uri: str = field(default_factory=lambda: os.getenv("MONGODB_URI", ""))
    mongodb_db: str = field(default_factory=lambda: os.getenv("MONGODB_DB", "taskos"))

    # Runtime
    max_task_retries: int = field(default_factory=lambda: _int_env("MAX_TASK_RETRIES", 3))
    max_parallel_tasks: int = field(
        default_factory=lambda: _int_env("MAX_PARALLEL_TASKS", 4)
    )
    api_host: str = field(default_factory=lambda: os.getenv("API_HOST", "127.0.0.1"))
    api_port: int = field(default_factory=lambda: _int_env("API_PORT", 8000))

    @property
    def use_in_memory_store(self) -> bool:
        """No Mongo URI configured -> fall back to the in-process store."""
        return not self.mongodb_uri.strip()


settings = Settings()
