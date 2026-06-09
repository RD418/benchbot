# BenchBot dashboard

A small **read-only** observability UI for the BenchBot work cell, built with
React + TypeScript + Vite. It streams a work-cell run over Server-Sent Events and
animates device health, task progress, and the event timeline as they happen —
so you can *watch* the orchestration (and graceful degradation) live.

> Experiments are authored as code / YAML / API, not in the UI — the lab is
> agent- and code-driven. This dashboard is purely a monitoring lens.

## Run it

Start the API (from the repo root):

```bash
uv run benchbot serve --port 8000
```

Then the dashboard:

```bash
cd web
npm install
npm run dev          # http://localhost:5173
```

The API base URL defaults to `http://localhost:8000`; override with
`VITE_API_URL` if needed. CORS for `localhost:5173` is enabled by the API.

## What to try

- Click **run workflow** — three devices, dependency-ordered, all complete.
- Drag **incubator fault rate** to `1.0` and run — watch `inc1` go **down**, its
  dependent task (`read`) get **skipped**, and the independent liquid-handler task
  still **complete** (status `degraded`). That is graceful degradation: one
  instrument failing does not cascade.
- Tick **halt on failure** — the same fault stops the whole workflow (`halted`).

## How it works

`EventSource` consumes `GET /stream/demo`; pure reducers in `src/state.ts`
*derive* live device and task views from the event stream (the same
"reconstruct state from events" idea the backend uses for run status). The final
`done` message carries the authoritative `WorkflowResult`.
