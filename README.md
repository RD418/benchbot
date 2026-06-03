# BenchBot

A Python protocol runner for **simulated lab automation**. BenchBot models
robotic liquid-handling work-cells — plates, wells, tip racks, transfers — and
runs protocols against a deterministic software simulation, with structured
validation and run logs. It's inspired by open-source lab-automation tooling
such as [PyLabRobot](https://github.com/PyLabRobot/pylabrobot) and
[PyHamilton](https://github.com/dgretton/pyhamilton), but is a self-contained
simulator with **no hardware required**.

> **Status:** Milestones 1–4 (domain core + validation, simulation engine, mock
> instruments + seeded faults + retry/recovery, event-sourced SQLite
> persistence) are implemented. The API and CLI land in later milestones — see
> the roadmap below.

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

## Tech stack

| Concern | Choice |
| --- | --- |
| Packaging / venv | [uv](https://docs.astral.sh/uv/) |
| Models & validation | Pydantic v2 |
| Lint + format | Ruff |
| Type checking | mypy (strict) |
| Tests | pytest + coverage |
| Persistence | SQLAlchemy 2.0 async + Alembic + aiosqlite |
| API *(later)* | FastAPI |
| CLI *(later)* | Typer |

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

## Simulated work-cell assumptions

- A single deck with 12 slots; one labware instance per slot.
- Single-channel pipetting semantics (one well at a time).
- Volumes are in microliters; geometry uses single-letter rows (A–Z).
- No physical timing/collision modeling in M1 — that arrives with the engine.

## Roadmap

1. **M1 — Domain core + validation** ✅
2. **M2 — Simulation engine + virtual deck state + event emission** ✅
3. **M3 — Mock serial instruments + seeded faults + retry/recovery** ✅
4. **M4 — SQLite persistence (event-sourced run log via SQLAlchemy/Alembic)** ✅
5. **M5 — FastAPI service + Typer CLI**
6. **M6 — Docker, CI, expanded docs**

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
  mock_serial.py        # simulated serial instrument
src/benchbot/store/     # persistence (depends on engine + domain)
  models.py             # SQLAlchemy ORM: runs + append-only events tables
  db.py                 # async engine / session / URL config
  repository.py         # RunStore: save runs, load events, reconstruct status
  projections.py        # derive run status from the event stream
migrations/             # Alembic migrations (async env, initial schema)
examples/               # sample protocols (one valid, one broken)
tests/                  # pytest suite
```

## License

MIT
