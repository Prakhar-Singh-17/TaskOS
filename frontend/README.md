# TaskOS frontend

React + Vite + Tailwind CSS v4. See the [repo root README](../README.md) for
how to run the full stack (backend + frontend) and environment variables.

## Notes on this UI

- **Tailwind v4, CSS-first config** — no `tailwind.config.js`; all theme
  tokens (colors, fonts, animation keyframes) live in `src/index.css` as
  plain CSS custom properties, exposed to Tailwind via `@theme inline`.
- **Dark/light theme** — toggled via a `.dark` class on `<html>`, persisted
  to `localStorage` (`taskos-theme`). `index.html` sets the class before
  first paint to avoid a flash.
- **Real node graph** (`TaskGraph.jsx`) — tasks are absolutely positioned per
  DAG layer (computed by the backend, not re-derived here) with actual SVG
  bezier edges between dependencies, not a static box layout.
- Motion respects `prefers-reduced-motion`.

Component props and the `api.js`/`socket.js` contract are unchanged from the
backend's REST/Socket.io shape (see `backend/taskos/api/app.py`) — nothing
here assumes a different response format.
