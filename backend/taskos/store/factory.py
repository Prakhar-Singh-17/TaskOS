"""Picks a StateStore implementation based on configuration.

No MONGODB_URI -> MemoryStore (dev/demo, no database needed).
MONGODB_URI set -> MongoStore (Atlas in production).

This is the one place that decision is made, so the rest of the app just
asks for "a store" and never checks the environment itself.
"""

from __future__ import annotations

import logging

from taskos.config import settings
from taskos.store.base import StateStore
from taskos.store.memory import MemoryStore

logger = logging.getLogger(__name__)


async def create_store() -> StateStore:
    """Build and connect the configured StateStore."""
    if settings.use_in_memory_store:
        logger.info("No MONGODB_URI set -> using in-memory store (data is not persisted)")
        store: StateStore = MemoryStore()
    else:
        from taskos.store.mongo import MongoStore  # imported lazily: pymongo only needed here

        store = MongoStore(settings.mongodb_uri, settings.mongodb_db)

    await store.connect()
    return store
