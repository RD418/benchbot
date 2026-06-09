# BenchBot dashboard

A small **read-only** observability UI for the BenchBot work cell, built with
React + TypeScript + Vite. It lists persisted workflow runs and, for any run you
select, draws the workflow as a **directed graph** (nodes colored by outcome, the
failure path highlighted) alongside device health and the event stream.

> Experiments are authored as code / YAML / API, not in the UI — the lab is
> agent- and code-driven. This dashboard is purely a monitoring lens: it observes
> whatever runs the CLI, API, or agents submit. The "run workflow" button just
> triggers a sample run (`POST /workflows/demo`) so there's something to look at.

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

- Click **run workflow** — a run appears in the list; select it to see the graph
  (three devices, dependency-ordered, all green).
- Drag **incubator fault rate** to `1.0` and run — the new run is `degraded`:
  `inc1` goes **down**, its dependent task (`read`) is **skipped** (grey, dashed)
  with a **red broken edge** marking the failure path, while the independent
  liquid-handler task still **completes**. One instrument failing does not cascade.
- Tick **halt on failure** — the same fault stops the whole workflow (`halted`).

## How it works

The dashboard reads the persisted-run endpoints (`GET /workflows`,
`/workflows/{id}`, `/workflows/{id}/events`). `src/dag.ts` does a dependency-depth
(longest-path) layout with no graph library; `DagView` renders it as SVG, coloring
nodes by outcome and drawing edges downstream of a non-completed task as a broken
red path. Device health is reconstructed from the run's stored events.
