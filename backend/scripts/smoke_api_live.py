"""Manual, live smoke test for the API + Socket.io layer.

Connects a real Socket.io client to a running server, submits a goal over
HTTP, and prints every event as it arrives in realtime -- proving the whole
wire is connected: HTTP -> orchestrator -> runner -> EventBus -> Socket.io ->
client, exactly the path the React dashboard will use.

Requires the server already running:
    uvicorn taskos.api.app:asgi_app --port 8000

    python -m scripts.smoke_api_live "<goal>"
"""

from __future__ import annotations

import asyncio
import sys

import httpx
import socketio

API_BASE = "http://127.0.0.1:8000"


async def main() -> None:
    goal = sys.argv[1] if len(sys.argv) > 1 else "Write a short overview of what Anthropic does"

    sio = socketio.AsyncSimpleClient()
    await sio.connect(API_BASE)
    print(f"Connected to {API_BASE} (sid={sio.sid})\n")

    async def watch_events():
        while True:
            event_name, data = await sio.receive()
            payload_preview = str(data.get("payload"))[:120]
            print(f"[{data['eventType']:16s}] task={data.get('taskId')}  {payload_preview}")
            if data["eventType"] == "run_completed":
                break

    watcher = asyncio.create_task(watch_events())

    async with httpx.AsyncClient() as client:
        response = await client.post(f"{API_BASE}/api/runs", json={"goal": goal})
        response.raise_for_status()
        run_id = response.json()["runId"]
        print(f"Submitted goal, run_id={run_id}\n")

    await asyncio.wait_for(watcher, timeout=120)

    async with httpx.AsyncClient() as client:
        detail = (await client.get(f"{API_BASE}/api/runs/{run_id}")).json()
    print(f"\nFinal run status: {detail['status']}")
    for t in detail["tasks"]:
        print(f"  [{t['assignedAgent']:9s}] {t['status']:8s} attempts={len(t['attempts'])}  {t['description'][:60]}")

    await sio.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
