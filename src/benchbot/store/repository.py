"""The persistence API: save runs, load events, reconstruct status.

:class:`RunStore` is the only object the rest of the app needs. It serializes
events through a Pydantic ``TypeAdapter`` (so the discriminated union round-trips
losslessly) and exposes both the cached status projection and a live
reconstruction from the stored event stream.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from benchbot.engine.events import Event
from benchbot.engine.runner import RunResult, RunStatus
from benchbot.store.models import EventRow, RunRow, WorkflowEventRow, WorkflowRunRow
from benchbot.store.projections import project_status, project_workflow_status
from benchbot.workcell.cell import WorkflowResult, WorkflowStatus
from benchbot.workcell.events import (
    DeviceQuarantined,
    TaskFailed,
    TaskRetry,
    WorkflowEvent,
)
from benchbot.workcell.workflow import Workflow

#: Round-trips any concrete event through the discriminated union.
_EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)
_WF_EVENT_ADAPTER: TypeAdapter[WorkflowEvent] = TypeAdapter(WorkflowEvent)


class StoredRun(BaseModel):
    """Metadata view of a persisted run (without its events)."""

    id: str
    protocol_name: str
    total_steps: int
    status: RunStatus
    failure_code: str | None = None
    failure_message: str | None = None
    created_at: datetime


class RunStore:
    """Async repository for runs and their event streams."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def save_result(self, result: RunResult, *, protocol_name: str, total_steps: int) -> str:
        """Persist a completed :class:`RunResult`; return the new run id."""
        run_id = str(uuid4())
        async with self._sf() as session, session.begin():
            session.add(
                RunRow(
                    id=run_id,
                    protocol_name=protocol_name,
                    total_steps=total_steps,
                    status=result.status.value,
                    failure_code=result.failure.code if result.failure else None,
                    failure_message=result.failure.message if result.failure else None,
                    created_at=datetime.now(UTC),
                )
            )
            for event in result.events:
                session.add(
                    EventRow(
                        run_id=run_id,
                        seq=event.seq,
                        type=event.type,
                        timestamp=event.timestamp,
                        payload=_EVENT_ADAPTER.dump_python(event, mode="json"),
                    )
                )
        return run_id

    async def get_run(self, run_id: str) -> StoredRun | None:
        async with self._sf() as session:
            row = await session.get(RunRow, run_id)
            return _to_stored(row) if row is not None else None

    async def list_runs(self) -> list[StoredRun]:
        async with self._sf() as session:
            stmt = select(RunRow).order_by(RunRow.created_at.desc())
            rows = (await session.scalars(stmt)).all()
            return [_to_stored(row) for row in rows]

    async def get_events(self, run_id: str) -> list[Event]:
        async with self._sf() as session:
            stmt = select(EventRow).where(EventRow.run_id == run_id).order_by(EventRow.seq)
            rows = (await session.scalars(stmt)).all()
            return [_EVENT_ADAPTER.validate_python(row.payload) for row in rows]

    async def reconstruct_status(self, run_id: str) -> RunStatus:
        """Re-derive status from the stored event stream (event sourcing)."""
        return project_status(await self.get_events(run_id))


def _to_stored(row: RunRow) -> StoredRun:
    return StoredRun(
        id=row.id,
        protocol_name=row.protocol_name,
        total_steps=row.total_steps,
        status=RunStatus(row.status),
        failure_code=row.failure_code,
        failure_message=row.failure_message,
        created_at=row.created_at,
    )


# --- Workflow runs ------------------------------------------------------------


class WorkflowRunSummary(BaseModel):
    """Lightweight list view of a persisted workflow run (no definition/events)."""

    id: str
    name: str
    status: WorkflowStatus
    task_count: int
    created_at: datetime


class StoredWorkflowRun(BaseModel):
    """Full view of a persisted workflow run, minus its event stream.

    ``workflow`` is the submitted definition (task ids, devices, ``depends_on``)
    so a client can draw the DAG; ``tasks`` carries the per-task outcomes.
    """

    id: str
    name: str
    status: WorkflowStatus
    workflow: dict[str, Any]
    tasks: list[dict[str, Any]]
    device_health: dict[str, str]
    created_at: datetime


class DeviceMetrics(BaseModel):
    """Per-device counters derived from a run's event stream."""

    name: str
    health: str
    retries: int
    errors: int
    quarantined: bool


class WorkflowRunPackage(BaseModel):
    """A self-contained, exportable record of a workflow run.

    The honest "data package": the run's definition and outcomes, metrics derived
    from the event stream, and the full stream itself — enough to reproduce and
    audit the run offline.
    """

    package_version: int = 1
    generated_at: datetime
    run: StoredWorkflowRun
    device_metrics: list[DeviceMetrics]
    task_totals: dict[str, int]
    events: list[WorkflowEvent]


def _device_metrics(run: StoredWorkflowRun, events: list[WorkflowEvent]) -> list[DeviceMetrics]:
    names = list(run.device_health.keys())
    retries = dict.fromkeys(names, 0)
    errors = dict.fromkeys(names, 0)
    quarantined = dict.fromkeys(names, False)
    for event in events:
        if isinstance(event, TaskRetry) and event.device in retries:
            retries[event.device] += 1
            errors[event.device] += 1
        elif isinstance(event, TaskFailed) and event.device in errors:
            errors[event.device] += 1
        elif isinstance(event, DeviceQuarantined) and event.device in quarantined:
            quarantined[event.device] = True
    return [
        DeviceMetrics(
            name=name,
            health=run.device_health[name],
            retries=retries[name],
            errors=errors[name],
            quarantined=quarantined[name],
        )
        for name in names
    ]


def _task_totals(run: StoredWorkflowRun) -> dict[str, int]:
    totals = {"completed": 0, "failed": 0, "skipped": 0}
    for task in run.tasks:
        outcome = str(task.get("outcome", ""))
        totals[outcome] = totals.get(outcome, 0) + 1
    return totals


class WorkflowStore:
    """Async repository for workflow runs and their event streams."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def save_result(self, result: WorkflowResult, *, workflow: Workflow) -> str:
        """Persist a workflow run (definition + outcomes + events); return its id."""
        run_id = str(uuid4())
        async with self._sf() as session, session.begin():
            session.add(
                WorkflowRunRow(
                    id=run_id,
                    name=workflow.name,
                    status=result.status.value,
                    workflow=workflow.model_dump(mode="json"),
                    tasks=[t.model_dump(mode="json") for t in result.tasks],
                    device_health={name: h.value for name, h in result.device_health.items()},
                    created_at=datetime.now(UTC),
                )
            )
            for event in result.events:
                session.add(
                    WorkflowEventRow(
                        workflow_run_id=run_id,
                        seq=event.seq,
                        type=event.type,
                        timestamp=event.timestamp,
                        payload=_WF_EVENT_ADAPTER.dump_python(event, mode="json"),
                    )
                )
        return run_id

    async def get_run(self, run_id: str) -> StoredWorkflowRun | None:
        async with self._sf() as session:
            row = await session.get(WorkflowRunRow, run_id)
            if row is None:
                return None
            return StoredWorkflowRun(
                id=row.id,
                name=row.name,
                status=WorkflowStatus(row.status),
                workflow=row.workflow,
                tasks=row.tasks,
                device_health=row.device_health,
                created_at=row.created_at,
            )

    async def list_runs(self) -> list[WorkflowRunSummary]:
        async with self._sf() as session:
            stmt = select(WorkflowRunRow).order_by(WorkflowRunRow.created_at.desc())
            rows = (await session.scalars(stmt)).all()
            return [
                WorkflowRunSummary(
                    id=row.id,
                    name=row.name,
                    status=WorkflowStatus(row.status),
                    task_count=len(row.tasks),
                    created_at=row.created_at,
                )
                for row in rows
            ]

    async def get_events(self, run_id: str) -> list[WorkflowEvent]:
        async with self._sf() as session:
            stmt = (
                select(WorkflowEventRow)
                .where(WorkflowEventRow.workflow_run_id == run_id)
                .order_by(WorkflowEventRow.seq)
            )
            rows = (await session.scalars(stmt)).all()
            return [_WF_EVENT_ADAPTER.validate_python(row.payload) for row in rows]

    async def reconstruct_status(self, run_id: str) -> WorkflowStatus:
        """Re-derive status from the stored event stream (event sourcing)."""
        return project_workflow_status(await self.get_events(run_id))

    async def export_package(self, run_id: str) -> WorkflowRunPackage | None:
        """Assemble a complete, downloadable data package for a run."""
        run = await self.get_run(run_id)
        if run is None:
            return None
        events = await self.get_events(run_id)
        return WorkflowRunPackage(
            generated_at=datetime.now(UTC),
            run=run,
            device_metrics=_device_metrics(run, events),
            task_totals=_task_totals(run),
            events=events,
        )
