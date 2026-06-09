"""The ``benchbot`` command-line interface.

A thin Typer wrapper over the same engine and store used by the API. Commands:

* ``validate`` — static-check a protocol file.
* ``run``      — simulate a protocol (with optional seeded faults), optionally save.
* ``list`` / ``show`` / ``events`` — query persisted runs.
* ``serve``    — launch the HTTP API.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypeVar

import typer

from benchbot.domain.loader import load_protocol_file
from benchbot.domain.validation import validate as validate_protocol
from benchbot.engine.events import Event
from benchbot.engine.retry import RetryPolicy
from benchbot.engine.runner import RunResult, SimulationRunner
from benchbot.instruments.faults import FaultPolicy, NoFaults, RandomFaults
from benchbot.instruments.mock_serial import MockSerialInstrument
from benchbot.store.db import create_all, make_engine, make_session_factory
from benchbot.store.repository import RunStore
from benchbot.workcell.cell import (
    WorkflowStatus,
    build_default_workcell,
    build_demo_workflow,
)
from benchbot.workcell.events import WorkflowEvent
from benchbot.workcell.recovery import Disposition, RecoveryPolicy

app = typer.Typer(
    help="BenchBot - simulated lab-automation protocol runner.",
    no_args_is_help=True,
    add_completion=False,
)

T = TypeVar("T")


@app.command()
def validate(path: Path) -> None:
    """Statically validate a protocol file."""
    result = validate_protocol(load_protocol_file(path))
    for issue in result.issues:
        typer.echo(str(issue))
    if result.ok:
        typer.secho("OK: protocol is valid", fg=typer.colors.GREEN)
    else:
        typer.secho(f"INVALID: {len(result.errors)} error(s)", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)


@app.command()
def run(
    path: Path,
    seed: int = typer.Option(0, help="RNG seed for deterministic fault injection."),
    transient_rate: float = typer.Option(0.0, help="Probability of a transient NAK."),
    timeout_rate: float = typer.Option(0.0, help="Probability of a timeout."),
    hard_rate: float = typer.Option(0.0, help="Probability of a fatal hardware fault."),
    max_attempts: int = typer.Option(3, help="Retry attempts per command."),
    save: bool = typer.Option(False, help="Persist the run to the database."),
) -> None:
    """Simulate a protocol, printing its event stream."""
    protocol = load_protocol_file(path)
    faults: FaultPolicy
    if transient_rate or timeout_rate or hard_rate:
        faults = RandomFaults(
            seed=seed,
            transient_rate=transient_rate,
            timeout_rate=timeout_rate,
            hard_rate=hard_rate,
        )
    else:
        faults = NoFaults()
    runner = SimulationRunner(MockSerialInstrument(faults), RetryPolicy(max_attempts=max_attempts))
    result = runner.run(protocol)

    for event in result.events:
        typer.echo(_format_event(event))
    _print_outcome(result)

    if save:
        run_id = _run_async(
            lambda store: store.save_result(
                result, protocol_name=protocol.metadata.name, total_steps=len(protocol.steps)
            )
        )
        typer.echo(f"saved run: {run_id}")

    if not result.ok:
        raise typer.Exit(code=1)


@app.command(name="list")
def list_runs() -> None:
    """List persisted runs (most recent first)."""
    runs = _run_async(lambda store: store.list_runs())
    if not runs:
        typer.echo("(no runs)")
        return
    for r in runs:
        typer.echo(f"{r.id}  {r.status.value:<10} {r.protocol_name}")


@app.command()
def show(run_id: str) -> None:
    """Show a persisted run's summary."""
    run = _run_async(lambda store: store.get_run(run_id))
    if run is None:
        typer.secho("run not found", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.echo(f"id:        {run.id}")
    typer.echo(f"protocol:  {run.protocol_name}")
    typer.echo(f"status:    {run.status.value}")
    typer.echo(f"steps:     {run.total_steps}")
    if run.failure_code:
        typer.echo(f"failure:   {run.failure_code} - {run.failure_message}")


@app.command()
def events(run_id: str) -> None:
    """Print the stored event stream for a run."""
    stored = _run_async(lambda store: store.get_events(run_id))
    if not stored:
        typer.echo("(no events)")
        return
    for event in stored:
        typer.echo(_format_event(event))


@app.command(name="workcell-demo")
def workcell_demo(
    seed: int = typer.Option(0, help="RNG seed for deterministic fault injection."),
    hard_rate: float = typer.Option(
        0.0, help="Hard-fault rate injected into the incubator (inc1)."
    ),
    halt: bool = typer.Option(False, help="Use a HALT recovery policy instead of SKIP."),
) -> None:
    """Run a 3-device sample workflow (liquid handler + incubator + plate reader)."""
    cell = build_default_workcell()
    if hard_rate:
        cell.devices["inc1"].set_faults(RandomFaults(seed=seed, hard_rate=hard_rate))
    recovery = RecoveryPolicy(default=Disposition.HALT) if halt else None

    result = cell.run_workflow(build_demo_workflow(), recovery)

    for event in result.events:
        typer.echo(_format_wf_event(event))
    typer.echo("")
    for task in result.tasks:
        note = task.detail or (task.failure.code if task.failure else "")
        typer.echo(f"  task {task.id:<10} {task.outcome.value:<10} {note}")
    typer.echo("")
    for device in cell.health().devices:
        typer.echo(
            f"  {device.name:<8} {device.health.value:<9} "
            f"commands={device.commands} errors={device.errors} rate={device.error_rate}"
        )

    ok = result.status is WorkflowStatus.COMPLETED
    typer.secho(
        f"workflow: {result.status.value}",
        fg=typer.colors.GREEN if ok else typer.colors.YELLOW,
    )
    if result.status in (WorkflowStatus.HALTED, WorkflowStatus.INVALID):
        raise typer.Exit(code=1)


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Launch the HTTP API with uvicorn."""
    import uvicorn

    from benchbot.api.app import create_app

    uvicorn.run(create_app(), host=host, port=port)


# --- Helpers -------------------------------------------------------------------


def _run_async(operation: Callable[[RunStore], Awaitable[T]]) -> T:
    """Run an async store operation against the configured database."""

    async def _inner() -> T:
        engine = make_engine()
        await create_all(engine)
        store = RunStore(make_session_factory(engine))
        try:
            return await operation(store)
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def _format_event(event: Event) -> str:
    fields = ("action", "detail", "command", "attempt", "code", "message", "steps_completed")
    parts = [str(getattr(event, f)) for f in fields if getattr(event, f, None) is not None]
    return f"[{event.seq:>3}] {event.type:<16} " + "  ".join(parts)


def _format_wf_event(event: WorkflowEvent) -> str:
    fields = ("task_id", "device", "action", "detail", "reason", "attempt", "code", "status")
    parts = [str(getattr(event, f)) for f in fields if getattr(event, f, None) is not None]
    return f"[{event.seq:>3}] {event.type:<19} " + "  ".join(parts)


def _print_outcome(result: RunResult) -> None:
    color = typer.colors.GREEN if result.ok else typer.colors.RED
    typer.secho(f"status: {result.status.value}", fg=color)
    if result.failure is not None:
        typer.secho(f"failure: {result.failure.code} - {result.failure.message}", fg=color)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
