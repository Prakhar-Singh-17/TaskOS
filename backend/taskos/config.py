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


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "")
    try:
        return float(raw) if raw.strip() else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # LLM
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    )

    # Tools
    tavily_api_key: str = field(default_factory=lambda: os.getenv("TAVILY_API_KEY", ""))
    search_mode: str = field(
        default_factory=lambda: os.getenv("TASKOS_SEARCH_MODE", "live").lower()
    )
    # Pollinations.ai is free and needs no API key, so live can be the default
    # (unlike search_mode, which defaults live but still needs TAVILY_API_KEY
    # to actually call out). Tests still force this to "mock" -- see
    # tests/conftest.py -- so the suite never depends on a live network call.
    image_mode: str = field(
        default_factory=lambda: os.getenv("TASKOS_IMAGE_MODE", "live").lower()
    )
    # Judge0 CE's public instance is also free and keyless, so this defaults
    # live too. It's a free community instance backing a paid SaaS tier
    # (same relationship Pollinations has to a paid image API) -- no uptime
    # guarantee, so tests still force this to "mock".
    code_mode: str = field(
        default_factory=lambda: os.getenv("TASKOS_CODE_MODE", "live").lower()
    )

    # State store
    mongodb_uri: str = field(default_factory=lambda: os.getenv("MONGODB_URI", ""))
    mongodb_db: str = field(default_factory=lambda: os.getenv("MONGODB_DB", "taskos"))

    # Runtime
    max_task_retries: int = field(default_factory=lambda: _int_env("MAX_TASK_RETRIES", 3))
    max_parallel_tasks: int = field(
        default_factory=lambda: _int_env("MAX_PARALLEL_TASKS", 4)
    )
    # Base delay before a retried attempt, doubled per attempt (1x, 2x, 4x...).
    # Third-party tools (Pollinations, Tavily) rate-limit or briefly 500 under
    # load -- retrying instantly just resends into the same limit window, so
    # tests force this to 0 for speed/determinism (see tests/conftest.py).
    retry_backoff_seconds: float = field(
        default_factory=lambda: _float_env("RETRY_BACKOFF_SECONDS", 2.0)
    )
    api_host: str = field(default_factory=lambda: os.getenv("API_HOST", "127.0.0.1"))
    api_port: int = field(default_factory=lambda: _int_env("API_PORT", 8000))

    # Comma-separated list of origins allowed to call the API/websocket, e.g.
    # "https://taskos-frontend.onrender.com". No wildcard fallback on purpose:
    # if this is unset, allowed_origins is an empty list and nothing can call
    # the API cross-origin -- fails closed, not open. Set it explicitly, both
    # locally (e.g. http://localhost:5173) and in production.
    allowed_origins_raw: str = field(
        default_factory=lambda: os.getenv("ALLOWED_ORIGINS", "")
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins_raw.split(",") if o.strip()]

    @property
    def use_in_memory_store(self) -> bool:
        """No Mongo URI configured -> fall back to the in-process store."""
        return not self.mongodb_uri.strip()


settings = Settings()
