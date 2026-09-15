# TaskOS

A mini Agentic Operating System: give it a goal, a Supervisor agent breaks it
into a task DAG, specialized agents execute it (in parallel where the DAG
allows), failures are classified and retried, and a live dashboard shows the
whole thing happen in real time.

## Architecture

```
Goal ──▶ Supervisor (Gemini) ──▶ task DAG ──▶ Task Runner
                                                  │
                       ┌──────────────────────────┼──────────────────────────┐
                       ▼                          ▼                          ▼
                 Research agent             Synthesis agent             Writer agent
                 (search MCP tool)       (merges research)          (drafts from findings)
                       │                          │                          │
                       └──────────────┬───────────┴──────────────────────────┘
                                       ▼
                              Shared state (Mongo / in-memory)
                                       │
                                       ▼
                          Event bus ──▶ Socket.io ──▶ React dashboard
```

- **Backend** (`backend/`): FastAPI + Socket.io. Python, custom DAG runner
  (no LangGraph -- the Supervisor generates the DAG at runtime, which doesn't
  fit a compile-time graph framework).
- **Frontend** (`frontend/`): React (Vite), plain CSS, `socket.io-client`.
- **LLM**: Gemini, via the `google-genai` SDK.
- **Tools**: MCP (Model Context Protocol) servers, spoken over stdio. One
  tool today (`search`, backed by Tavily with an offline mock mode); adding
  another tool means adding another MCP server, no core code changes.
- **State**: MongoDB Atlas, or an in-memory store when `MONGODB_URI` is unset
  (handy for local dev/demo with no database).

See `backend/taskos/` for the full module layout -- each file's docstring
explains what it does and why.

## Running locally

**Backend:**
```bash
cd backend
python -m venv .venv
.venv/Scripts/activate        # .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp ../.env.example ../.env    # fill in GEMINI_API_KEY at minimum
uvicorn taskos.api.app:asgi_app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
cp .env.example .env          # points at the backend; default is fine locally
npm run dev
```

Open the printed Vite URL (typically http://localhost:5173).

## Environment variables

See `.env.example` (backend, at the repo root) and `frontend/.env.example`.
Only `GEMINI_API_KEY` is required to run agents at all; `TAVILY_API_KEY` and
`MONGODB_URI` both have working fallbacks (mock search results, in-memory
store) so the whole system runs and demos with just a Gemini key.

## Tests

```bash
cd backend
pytest
```

All backend tests are hermetic -- no real network calls, no Gemini/Tavily/Mongo
required. Manual live-integration scripts (real API calls) live in
`backend/scripts/smoke_*.py` and are run by hand, not part of the suite.

## Deploying

Backend and frontend are two independent services (e.g. two Render
services): the backend as a Python web service (`uvicorn taskos.api.app:asgi_app`),
the frontend as a static site (`npm run build`, publish `frontend/dist`) with
`VITE_API_URL` pointed at the deployed backend's URL.
