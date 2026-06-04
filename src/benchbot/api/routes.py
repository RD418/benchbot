"""HTTP endpoints for run control and monitoring.

The router is deliberately thin: it builds a runner, executes the protocol,
persists the result, and exposes read views over the stored event stream. All
the real logic lives in the engine and store layers.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from benchbot.api.schemas import (
    Diagnostics,
    RunRequest,
    RunSummary,
)
from benchbot.domain.errors import Issue, Severity, ValidationResult
from benchbot.domain.protocol import Protocol
from benchbot.domain.validation import validate
from benchbot.engine.events import (
    CommandSent,
    Event,
    RecoveryFailed,
    RetryScheduled,
    StepCompleted,
    StepWarning,
)
from benchbot.engine.retry import RetryPolicy
from benchbot.engine.runner import RunResult, SimulationRunner
from benchbot.instruments.faults import FaultPolicy, NoFaults, RandomFaults
from benchbot.instruments.mock_serial import MockSerialInstrument
from benchbot.store.repository import RunStore, StoredRun

router = APIRouter()


def get_store(request: Request) -> RunStore:
    """Dependency: the application's run store (set during lifespan)."""
    store: RunStore = request.app.state.store
    return store


#: Reusable typed dependency for the run store.
StoreDep = Annotated[RunStore, Depends(get_store)]


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/protocols/validate", response_model=ValidationResult)
async def validate_protocol(protocol: Protocol) -> ValidationResult:
    return validate(protocol)


@router.post("/runs", response_model=RunSummary, status_code=201)
async def submit_run(
    request: RunRequest, store: StoreDep
) -> RunSummary:
    try:
        runner = _build_runner(request)
    except ValueError as exc:  # invalid fault rates
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    result = runner.run(request.protocol, run_validation=request.run_validation)
    run_id = await store.save_result(
        result,
        protocol_name=request.protocol.metadata.name,
        total_steps=len(request.protocol.steps),
    )
    return RunSummary(
        id=run_id,
        status=result.status,
        total_steps=len(request.protocol.steps),
        steps_completed=_count(result, StepCompleted),
        failure=result.failure,
    )


@router.get("/runs", response_model=list[StoredRun])
async def list_runs(store: StoreDep) -> list[StoredRun]:
    return await store.list_runs()


@router.get("/runs/{run_id}", response_model=StoredRun)
async def get_run(run_id: str, store: StoreDep) -> StoredRun:
    run = await store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.get("/runs/{run_id}/events", response_model=list[Event])
async def get_events(run_id: str, store: StoreDep) -> list[Event]:
    await _require_run(store, run_id)
    return await store.get_events(run_id)


@router.get("/runs/{run_id}/diagnostics", response_model=Diagnostics)
async def get_diagnostics(
    run_id: str, store: StoreDep
) -> Diagnostics:
    run = await _require_run(store, run_id)
    events = await store.get_events(run_id)
    failure = (
        Issue(severity=Severity.ERROR, code=run.failure_code, message=run.failure_message or "")
        if run.failure_code
        else None
    )
    warnings = [
        Issue(
            severity=Severity.WARNING,
            code=e.code,
            message=e.message,
            step_index=e.step_index,
        )
        for e in events
        if isinstance(e, StepWarning)
    ]
    return Diagnostics(
        id=run.id,
        status=run.status,
        failure=failure,
        command_count=sum(isinstance(e, CommandSent) for e in events),
        retry_count=sum(isinstance(e, RetryScheduled) for e in events),
        recovery_failures=sum(isinstance(e, RecoveryFailed) for e in events),
        warnings=warnings,
    )


# --- Helpers -------------------------------------------------------------------


async def _require_run(store: RunStore, run_id: str) -> StoredRun:
    run = await store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


def _build_runner(request: RunRequest) -> SimulationRunner:
    faults: FaultPolicy
    if request.faults is not None:
        faults = RandomFaults(
            seed=request.faults.seed,
            transient_rate=request.faults.transient_rate,
            timeout_rate=request.faults.timeout_rate,
            hard_rate=request.faults.hard_rate,
        )
    else:
        faults = NoFaults()
    retry = RetryPolicy(max_attempts=request.retry.max_attempts) if request.retry else RetryPolicy()
    return SimulationRunner(MockSerialInstrument(faults), retry)


def _count(result: RunResult, event_type: type) -> int:
    return sum(isinstance(e, event_type) for e in result.events)
