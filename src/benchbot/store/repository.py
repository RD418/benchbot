"""The persistence API: save runs, load events, reconstruct status.

:class:`RunStore` is the only object the rest of the app needs. It serializes
events through a Pydantic ``TypeAdapter`` (so the discriminated union round-trips
losslessly) and exposes both the cached status projection and a live
reconstruction from the stored event stream.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from benchbot.engine.events import Event
from benchbot.engine.runner import RunResult, RunStatus
from benchbot.store.models import EventRow, RunRow
from benchbot.store.projections import project_status

#: Round-trips any concrete event through the discriminated union.
_EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)


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
