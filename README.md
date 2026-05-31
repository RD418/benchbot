# BenchBot

A Python protocol runner for **simulated lab automation**. BenchBot models
robotic liquid-handling work-cells — plates, wells, tip racks, transfers — and
runs protocols against a deterministic software simulation, with structured
validation and run logs. It's inspired by open-source lab-automation tooling
such as [PyLabRobot](https://github.com/PyLabRobot/pylabrobot) and
[PyHamilton](https://github.com/dgretton/pyhamilton), but is a self-contained
simulator with **no hardware required**.

> **Status:** Milestone 1 (domain core + validation) is implemented. The engine,
> mock instruments, persistence, API, and CLI land in later milestones — see the
> roadmap below.

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
| Persistence *(later)* | SQLAlchemy 2.0 async + Alembic + aiosqlite |
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

## Simulated work-cell assumptions

- A single deck with 12 slots; one labware instance per slot.
- Single-channel pipetting semantics (one well at a time).
- Volumes are in microliters; geometry uses single-letter rows (A–Z).
- No physical timing/collision modeling in M1 — that arrives with the engine.

## Roadmap

1. **M1 — Domain core + validation** ✅ (this milestone)
2. **M2 — Simulation engine + virtual deck state** (event emission)
3. **M3 — Mock serial instruments + seeded faults + retry/recovery**
4. **M4 — SQLite persistence (event-sourced run log via SQLAlchemy/Alembic)**
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
examples/               # sample protocols (one valid, one broken)
tests/                  # pytest suite
```

## License

MIT
