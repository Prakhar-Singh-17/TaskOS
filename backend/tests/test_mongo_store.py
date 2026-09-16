"""Tests for MongoStore that don't require a live Atlas connection.

The rest of MongoStore's behavior (round-tripping runs/tasks/events) is
exercised by hand against a real cluster (see test_store.py's docstring) --
this file only guards the specific timezone regression below, which needs
no real connection since it just checks what MongoStore asks pymongo for.
"""

from datetime import timezone
from unittest.mock import AsyncMock, patch

from taskos.store.mongo import MongoStore


async def test_connect_requests_timezone_aware_datetimes():
    """Regression test: pymongo defaults to handing back *naive* datetimes
    (tzinfo=None) even though BSON always stores UTC underneath. A naive
    value serializes to JSON with no UTC marker, and JavaScript's Date
    parser then reads it as local browser time -- silently shifting every
    timestamp (elapsed-time math, event ordering) by the viewer's UTC
    offset. Caught in production as a run's "Elapsed" stat inflated by
    exactly the browser's timezone offset (330 minutes for IST, UTC+5:30).
    tz_aware=True (with tzinfo=timezone.utc) is what fixes it -- this test
    just makes sure that request to pymongo can't silently disappear again.
    """
    with patch("taskos.store.mongo.AsyncMongoClient") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.admin.command = AsyncMock(return_value={"ok": 1})
        mock_client.__getitem__.return_value = mock_client  # db access, for _ensure_indexes
        mock_client.runs.create_index = AsyncMock()
        mock_client.tasks.create_index = AsyncMock()
        mock_client.events.create_index = AsyncMock()
        mock_client.state.create_index = AsyncMock()

        store = MongoStore("mongodb://example.invalid", "taskos_test")
        await store.connect()

        _, kwargs = mock_client_cls.call_args
        assert kwargs.get("tz_aware") is True
        assert kwargs.get("tzinfo") == timezone.utc
