# BenchBot

A Python protocol runner and **work-cell orchestrator** for simulated lab
automation. BenchBot models robotic liquid-handling — plates, wells, tip racks,
transfers — runs protocols against a deterministic software simulation, and
coordinates **multiple heterogeneous instruments** (liquid handler, incubator,
plate reader) through dependency-ordered workflows with error recovery and
graceful degradation. It's inspired by open-source lab-automation tooling
such as [PyLabRobot](https://github.com/PyLabRobot/pylabrobot) and
[PyHamilton](https://github.com/dgretton/pyhamilton), but is a self-contained
simulator with **no hardware required**.

## Why it's interesting

- **Deterministic, seeded fault injection** (engine milestone) makes hardware
  errors, retries, and recovery reproducible and testable.
- **Event-sourced run logs** persisted to SQLite — run state is *derived* from
  an immutable event stream, giving free replay and audit trails.
- **Stateful virtual deck** tracking per-well volumes and tip state, enabling
  validation a naive simulator can't do.
- **Validate-only / dry-run** mode separating "is this protocol legal?" from
  "run it."
- **Two authoring paths** — declarative YAML/JSON *and* a fluent Python builder —
  that compile to the same validated model.
- **Multi-device orchestration with graceful degradation** — a work cell runs
  dependency-ordered workflows across several instruments; when one device fails
  it is quarantined and its dependents skipped, while independent work continues
  (no cascading failure).
- **Observability dashboard** — a React/TypeScript UI lists persisted runs and
  draws each workflow as a DAG with the failure path highlighted, alongside
  device health and the event stream (see [`web/`](web/)).

## Tech stack

| Concern | Choice |
| --- | --- |
| Packaging / venv | [uv](https://docs.astral.sh/uv/) |
| Models & validation | Pydantic v2 |
| Lint + format | Ruff |
| Type checking | mypy (strict) |
| Tests | pytest + coverage |
| Persistence | SQLAlchemy 2.0 async + Alembic + aiosqlite |
| API | FastAPI + uvicorn |
| CLI | Typer |

## Quickstart

```bash
uv sync                 # create the venv and install everything
uv run pytest           # run the test suite with coverage
uv run ruff check .     # lint
uv run mypy             # type-check (strict)
```

Validate a protocol programmatically:

```python
from benchbot.domain import load_protocol_file, validate

protocol = load_protocol_file("examples/serial_dilution.yaml")
result = validate(protocol)
print("ok:", result.ok)
for issue in result.issues:
    print(issue)
```

Or build one fluently:

```python
from benchbot.domain import ProtocolBuilder, validate

protocol = (
    ProtocolBuilder("Serial dilution")
    .add_plate("plate1", "plate_96_wellplate_200ul", slot=1)
    .add_tiprack("tips1", "tiprack_300ul", slot=2)
    .fill("plate1:A1", 200)
    .transfer("plate1:A1", "plate1:A2", 100)
    .mix("plate1:A2", 50, repeats=3)
    .build()
)
assert validate(protocol).ok
```

Run a protocol through the simulator:

```python
from benchbot.domain import load_protocol_file
from benchbot.engine import SimulationRunner

result = SimulationRunner().run(load_protocol_file("examples/serial_dilution.yaml"))
print(result.status.value)        # "completed" | "failed" | "invalid"
for event in result.events:
    print(event.seq, event.type)
print(result.final_state)         # {"plate1:A1": 100.0, ...}
```

A run has three terminal statuses: `invalid` (rejected by static validation, never
executed), `failed` (a dynamic error stopped it mid-run — see `result.failure`),
and `completed`. Every run produces an ordered **event stream**
(`run_started`, `step_started`, `step_completed`, `step_warning`, `step_failed`,
`run_failed`, `run_completed`) and a final deck snapshot.

### Injecting faults (deterministic)

Physical actions are routed through a mock serial instrument. Inject reproducible
faults to exercise retry and recovery:

```python
from benchbot.engine import SimulationRunner, RetryPolicy
from benchbot.instruments import MockSerialInstrument, RandomFaults

instrument = MockSerialInstrument(RandomFaults(seed=7, transient_rate=0.2, hard_rate=0.02))
runner = SimulationRunner(instrument, RetryPolicy(max_attempts=3))
result = runner.run(protocol)   # same seed -> byte-for-byte same run
```

The instrument frames each command (`>ASPIRATE vol=100 well=p:A1`), returns
ACK/NAK, and raises transient (NAK), timeout, or fatal hardware faults per its
`FaultPolicy`. Transient/timeout faults are retried with exponential backoff
(`RetryScheduled` events); a hardware fault or exhausted retries emits
`RecoveryFailed` and aborts the run. Because faults come from a seeded RNG, a
given `(seed, protocol)` always produces the identical event stream — failures
are reproducible and unit-testable. Use `ScriptedFaults([...])` for exact
control in tests, or `NoFaults()` (the default) for perfect hardware.

### Persisting runs (event-sourced)

Runs are stored in SQLite as an **append-only event stream**; a run's status is
derived from its events, not stored as independent mutable state. The schema is
managed by Alembic migrations.

```bash
export BENCHBOT_DATABASE_URL="sqlite+aiosqlite:///benchbot.db"
uv run alembic upgrade head     # create/upgrade the schema
```

```python
import asyncio
from benchbot.domain import load_protocol_file
from benchbot.engine import SimulationRunner
from benchbot.store import make_engine, make_session_factory, RunStore

async def main() -> None:
    store = RunStore(make_session_factory(make_engine()))
    protocol = load_protocol_file("examples/serial_dilution.yaml")
    result = SimulationRunner().run(protocol)
    run_id = await store.save_result(
        result, protocol_name=protocol.metadata.name, total_steps=len(protocol.steps)
    )
    print(await store.get_run(run_id))            # cached status projection
    print(await store.reconstruct_status(run_id)) # re-derived from the events

asyncio.run(main())
```

Persistence uses **SQLAlchemy 2.0 (async)** with `aiosqlite`. The `runs.status`
column is a read-model projection of `project_status(events)`; tests assert the
two always agree. Because the only coupling to SQLite is `BENCHBOT_DATABASE_URL`,
moving to Postgres is a one-line change.

## Command-line interface

The `benchbot` CLI wraps the same engine and store:

```bash
uv run benchbot validate examples/serial_dilution.yaml      # static check
uv run benchbot run examples/serial_dilution.yaml           # simulate + print events
uv run benchbot run examples/serial_dilution.yaml \
    --seed 7 --transient-rate 0.3 --max-attempts 5 --save   # faults + persist
uv run benchbot list                                        # persisted runs
uv run benchbot show <run_id>                               # run summary
uv run benchbot events <run_id>                             # stored event stream
uv run benchbot workcell-demo                               # multi-device workflow demo
uv run benchbot workcell-demo --hard-rate 1.0 --seed 1      # ... with a failing device
uv run benchbot serve --port 8000                           # launch the HTTP API
```

`validate` and `run` exit non-zero on invalid/failed runs, so they compose in
scripts and CI.

## HTTP API

```bash
uv run benchbot serve            # or: uv run uvicorn benchbot.api.app:create_app --factory
```

Interactive docs are served at `/docs`. Endpoints:

| Method & path | Purpose |
| --- | --- |
| `GET /health` | Liveness check. |
| `POST /protocols/validate` | Static-validate a protocol; returns issues. |
| `POST /runs` | Submit + simulate a protocol; returns a run summary. |
| `GET /runs` | List persisted runs (most recent first). |
| `GET /runs/{id}` | Run status + metadata. |
| `GET /runs/{id}/events` | The full event stream. |
| `GET /runs/{id}/diagnostics` | Command/retry/recovery counts + failure + warnings. |
| `POST /workflows` | Run a multi-device workflow; persists it and returns per-task outcomes. |
| `GET /workflows` | List persisted workflow runs (most recent first). |
| `GET /workflows/{id}` | A workflow run: status, the DAG definition, per-task outcomes, device health. |
| `GET /workflows/{id}/events` | The workflow's event stream. |
| `GET /workcell/health` | Per-device status, error rates, and quarantine state. |

A `POST /runs` body can tune deterministic faults and retries:

```jsonc
{
  "protocol": { "version": 1, "labware": [...], "liquids": [...], "steps": [...] },
  "faults":   { "seed": 7, "transient_rate": 0.3, "hard_rate": 0.02 },
  "retry":    { "max_attempts": 5 }
}
```

The diagnostics response makes retry/recovery observable, e.g.
`{"command_count": 5, "retry_count": 2, "recovery_failures": 0, ...}`.

For live monitoring, `GET /stream/demo` is a **Server-Sent Events** stream of a
work-cell run (paced so a browser can animate it); the
[dashboard](web/) consumes it.

## Live dashboard

A read-only **React + TypeScript** observability UI lives in [`web/`](web/). It
lists persisted workflow runs and, for any run, draws the workflow as a
**directed graph** — nodes colored by outcome with the **failure path
highlighted** — next to device health and the event stream. Drag the *incubator
fault rate* to `1.0` and run: the new run is `degraded`, the incubator node is
red, its dependent is skipped down a broken edge, and the independent task still
completes (graceful degradation, visible).

```bash
uv run benchbot serve --port 8000     # API
cd web && npm install && npm run dev   # dashboard on http://localhost:5173
```

Experiments are authored as code / YAML / API, not in the UI — the lab is
agent- and code-driven, so the dashboard is purely a monitoring lens.

## Protocol format

A protocol is a YAML/JSON document with four sections:

```yaml
version: 1
metadata: { name: "Serial dilution", author: "you" }
labware:
  - { id: plate1, type: plate_96_wellplate_200ul, slot: 1 }
  - { id: tips1,  type: tiprack_300ul,            slot: 2 }
liquids:
  - { well: "plate1:A1", volume_ul: 200 }
steps:
  - transfer: { source: "plate1:A1", dest: "plate1:A2", volume_ul: 100, new_tip: true }
  - mix:      { well: "plate1:A2", volume_ul: 50, repeats: 3 }
```

- **Well references** are `"<labware id>:<well address>"`, e.g. `plate1:A1`.
- **Steps** accept the shorthand above *or* an explicit `{ type: transfer, ... }`.
- Step kinds: `transfer`, `aspirate`, `dispense`, `mix`.

### Built-in labware

| Type | Geometry | Well capacity |
| --- | --- | --- |
| `plate_96_wellplate_200ul` | 8 × 12 | 200 µL |
| `plate_384_wellplate_50ul` | 16 × 24 | 50 µL |
| `tiprack_300ul` | 8 × 12 | 300 µL |
| `tiprack_1000ul` | 8 × 12 | 1000 µL |
| `reservoir_12col_15ml` | 1 × 12 | 15 000 µL |

The simulated deck has slots **1–12**; each slot holds one labware instance.

## Validation codes

Validation never raises bare strings — every finding is an `Issue` with a stable
`code`, `severity`, optional `step_index`, and `location`.

| Code | Meaning |
| --- | --- |
| `E_DUP_LABWARE_ID` | Two labware share an id. |
| `E_UNKNOWN_LABWARE_TYPE` | Labware `type` is not in the registry. |
| `E_SLOT_OUT_OF_RANGE` | Slot is outside 1–12. |
| `E_SLOT_OCCUPIED` | Two labware placed on the same slot. |
| `E_BAD_WELL_REF` | Well reference is not `labware:well`. |
| `E_UNKNOWN_LABWARE_REF` | Well references a labware id that isn't placed. |
| `E_INVALID_WELL` | Well address doesn't exist for that labware's geometry. |
| `E_VOLUME_NOT_POSITIVE` | A volume is ≤ 0. |
| `E_VOLUME_EXCEEDS_CAPACITY` | A volume exceeds the (smaller) well capacity. |
| `E_SAME_SOURCE_DEST` | Transfer source equals destination. |
| `E_NO_TIPRACK` | Protocol needs fresh tips but no tip rack is placed. |

See `examples/invalid_protocol.yaml` for a document that trips most of these.

### Dynamic codes (raised by the engine during a run)

These depend on live deck state and can only be caught while executing:

| Code | Severity | Meaning |
| --- | --- | --- |
| `E_INSUFFICIENT_VOLUME` | error | Aspirated more than the well currently holds. |
| `E_OVERFILL` | error | A dispense pushed a well past its capacity. |
| `E_TIP_OVERFLOW` | error | Aspirated more than the mounted tip can hold. |
| `E_INSUFFICIENT_TIP_VOLUME` | error | Dispensed more than the tip is carrying. |
| `E_NO_TIP_AVAILABLE` | error | All tips on the deck have been used. |
| `E_NO_TIP_MOUNTED` | error | Aspirate/dispense attempted without a tip. |
| `W_TIP_CARRYOVER` | warning | A reused tip crossed wells; possible carryover. |
| `E_INSTRUMENT_NAK` | error | Instrument NAK'd after retries were exhausted. |
| `E_INSTRUMENT_TIMEOUT` | error | Instrument timed out after retries were exhausted. |
| `E_HARDWARE_FAILURE` | error | Fatal hardware fault (never retried). |

## Work-cell orchestration

A single liquid handler is rarely the whole story — real assays span several
instruments. The **work cell** coordinates multiple devices behind one
abstraction and runs a *workflow*: a DAG of tasks, each targeting a device, with
`depends_on` edges for timing (e.g. *read* must run after *incubate*).

Devices and transports (all behind the same `Instrument` seam):

| Device | Kind | Transport (mock) | Tasks |
| --- | --- | --- | --- |
| `lh1` | liquid handler | serial framing (`>ASPIRATE …`) | `run_protocol` |
| `inc1` | incubator | TCP/JSON | `incubate` |
| `reader1` | plate reader | TCP/JSON | `read_plate` |

Three layers of failure handling, from narrow to broad:

1. **Command retry** (per device) — transient NAK/timeout retried with backoff.
2. **Task recovery** (`RecoveryPolicy`) — when a task fails after retries, decide
   per failure code: `RETRY` the task, `SKIP` it (quarantine the device, keep
   going), or `HALT` the workflow. Default is `SKIP`.
3. **Device quarantine** — a `SKIP`'d failure marks the device `DOWN`; its
   dependent tasks are skipped, but **independent tasks keep running**. One
   instrument failing never cascades through the cell.

```python
from benchbot.workcell import WorkCell, Workflow, IncubateTask, ReadPlateTask, build_default_workcell

cell = build_default_workcell()
workflow = Workflow(name="assay", tasks=[
    IncubateTask(id="incubate", device="inc1", minutes=30, celsius=37),
    ReadPlateTask(id="read", device="reader1", plate="p", depends_on=["incubate"]),
])
result = cell.run_workflow(workflow)
print(result.status)          # completed | degraded | halted | invalid
print(cell.health())          # per-device status + error rates
```

Try `uv run benchbot workcell-demo --hard-rate 1.0` to watch the incubator fail,
get quarantined, its dependent get skipped, and the independent liquid-handler
task still complete (status `degraded`, not `failed`). Workflow validation has
its own codes: `E_UNKNOWN_DEVICE`, `E_DEVICE_KIND_MISMATCH`,
`E_UNKNOWN_DEPENDENCY`, `E_DEPENDENCY_CYCLE`, `E_DUP_TASK_ID`, `E_SELF_DEPENDENCY`.

## Simulated work-cell assumptions

The simulation is intentionally a faithful-but-bounded model. Explicit
assumptions:

- A single deck with **12 slots**; exactly one labware instance per slot.
- **Single-channel** pipetting — one well aspirated/dispensed at a time.
- One mounted tip at a time; a fresh tip starts empty. Reusing a tip across
  different source wells is allowed but flagged (`W_TIP_CARRYOVER`).
- Volumes are in **microliters**; well geometry uses single-letter rows (A–Z).
- Liquids are tracked only by **volume**, not by species/concentration; there is
  no evaporation, mixing kinetics, or temperature.
- **No physical timing or collision modeling** — steps execute logically, not in
  wall-clock time. Instrument latency is abstracted into the fault policy.
- The mock instrument models the **communication channel** (frames, ACK/NAK,
  faults), not motor kinematics.
- The work cell executes tasks **sequentially in dependency order** — the focus
  is dependency ordering and failure isolation, not a real-time scheduler for
  overlapping device operations.
- Live work-cell state (device health, counters) is **in-memory**, but workflow
  runs are **persisted** to SQLite via the same event-sourced approach as
  single-device runs (the submitted DAG, per-task outcomes, device-health
  snapshot, and the event stream), so they can be listed and inspected later.

## Failure cases & reproduction

BenchBot is designed so every failure is reproducible. Static failures are
deterministic by construction; runtime/hardware failures are deterministic given
a seed.

| Scenario | How to reproduce |
| --- | --- |
| Static validation errors | `uv run benchbot validate examples/invalid_protocol.yaml` (exits 1, prints every `E_*` code). |
| Aspirate from an (under-filled) well | A `transfer` whose volume exceeds the source's current volume → `E_INSUFFICIENT_VOLUME`. |
| Overfill a destination | Transfer into a well already near capacity → `E_OVERFILL`. |
| Tip carryover warning | Reuse a tip across two source wells (`new_tip: false`) → `W_TIP_CARRYOVER` (run still completes). |
| Transient fault that recovers | `uv run benchbot run examples/serial_dilution.yaml --seed 7 --transient-rate 0.3` → watch `retry_scheduled` events; run completes. |
| Unrecoverable hardware fault | `uv run benchbot run examples/serial_dilution.yaml --seed 1 --hard-rate 1.0` → `recovery_failed`, exits 1. |
| Retries exhausted | `--transient-rate 1.0 --max-attempts 2` → every attempt NAKs → `E_INSTRUMENT_NAK`. |

Because faults come from a seeded RNG, re-running any command with the same
`--seed` (and rates) reproduces the identical event stream — including over the
HTTP API via the `faults`/`retry` request fields.

## Running with Docker

```bash
docker compose up --build      # builds, migrates, serves on :8000
curl localhost:8000/health
```

The image installs dependencies from `uv.lock` (reproducible), runs
`alembic upgrade head` on startup, then serves via uvicorn. Run history is
persisted to a named volume (`benchbot-data` → `/data/benchbot.db`), so it
survives restarts. A `HEALTHCHECK` probes `/health`.

## Development

```bash
uv sync                       # install runtime + dev dependencies
uv run pytest                 # tests + coverage
uv run ruff check . && uv run ruff format --check .   # lint + format
uv run mypy                   # strict type check
uv run alembic revision --autogenerate -m "msg"       # new migration
uv run alembic upgrade head   # apply migrations
```

## Continuous integration

`.github/workflows/ci.yml` runs on every push/PR: ruff lint, ruff format check,
mypy (strict), the pytest suite, and an `alembic upgrade head` + `alembic check`
step that fails the build if the migrations ever drift from the ORM models.

## Project layout

```
src/benchbot/domain/    # pure models + validation (no I/O)
  errors.py             # Issue / ValidationResult / exceptions
  labware.py            # labware definitions, geometry, registry
  protocol.py           # protocol model + fluent builder
  loader.py             # YAML/JSON parsing
  validation.py         # static validation
src/benchbot/engine/    # stateful simulation (depends only on domain)
  deck.py               # virtual deck: well volumes, tips, pipette
  events.py             # run event types + in-memory event log
  runner.py             # step executor + dynamic validation + instrument I/O
  retry.py              # retry policy with exponential backoff
src/benchbot/instruments/  # the hardware seam (depends on domain)
  base.py               # Instrument interface, Command/Ack frames, error types
  faults.py             # deterministic fault policies (seeded / scripted)
  mock_base.py          # shared fault/ACK semantics for mock instruments
  mock_serial.py        # serial-framed instrument (liquid handler)
  mock_tcp.py           # TCP/JSON instrument (reader, incubator)
src/benchbot/workcell/  # multi-device orchestration (depends on engine)
  devices.py            # Device: instrument + kind + health + counters
  workflow.py           # Workflow DAG, tasks, validation, topological order
  recovery.py           # per-failure-mode recovery policy (retry/skip/halt)
  cell.py               # WorkCell: schedule, recover, quarantine, health
  events.py             # workflow event types + log
src/benchbot/store/     # persistence (depends on engine + domain)
  models.py             # SQLAlchemy ORM: runs + workflow_runs + event tables
  db.py                 # async engine / session / URL config
  repository.py         # RunStore + WorkflowStore: save, load events, reconstruct
  projections.py        # derive run/workflow status from the event stream
src/benchbot/api/       # FastAPI service (thin adapter over engine + store)
  app.py                # application factory + lifespan-managed store
  routes.py             # endpoints
  schemas.py            # request/response models
src/benchbot/cli.py     # Typer CLI (validate / run / list / show / events / serve)
migrations/             # Alembic migrations (async env, initial schema)
web/                    # React + TypeScript live observability dashboard (SSE)
examples/               # sample protocols (one valid, one broken)
tests/                  # pytest suite
Dockerfile              # uv-based image: migrate then serve
docker-compose.yml      # one-command stack with a persistent volume
docker/entrypoint.sh    # alembic upgrade head + uvicorn
.github/workflows/ci.yml  # ruff + mypy + pytest + migration drift check
```

## License

MIT
