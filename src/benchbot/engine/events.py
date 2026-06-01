"""Run events and the in-memory event log.

A run is represented as an ordered stream of immutable-ish events. In M2 the
log lives in memory; in M4 the same event types are persisted to SQLite so run
state can be reconstructed (event sourcing). Keeping the event shapes stable
now is what makes that later step cheap.

Events are a discriminated union keyed on ``type`` so new event kinds can be
added without breaking serialization.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(UTC)


class _BaseEvent(BaseModel):
    #: Monotonic position in the run, assigned by :class:`EventLog` on emit.
    seq: int = -1
    timestamp: datetime = Field(default_factory=_now)


class RunStarted(_BaseEvent):
    type: Literal["run_started"] = "run_started"
    protocol_name: str
    total_steps: int


class StepStarted(_BaseEvent):
    type: Literal["step_started"] = "step_started"
    step_index: int
    action: str
    detail: str


class StepCompleted(_BaseEvent):
    type: Literal["step_completed"] = "step_completed"
    step_index: int


class StepWarning(_BaseEvent):
    type: Literal["step_warning"] = "step_warning"
    step_index: int
    code: str
    message: str


class StepFailed(_BaseEvent):
    type: Literal["step_failed"] = "step_failed"
    step_index: int
    code: str
    message: str


class RunCompleted(_BaseEvent):
    type: Literal["run_completed"] = "run_completed"
    steps_completed: int


class RunFailed(_BaseEvent):
    type: Literal["run_failed"] = "run_failed"
    step_index: int | None
    code: str
    message: str


Event = Annotated[
    RunStarted
    | StepStarted
    | StepCompleted
    | StepWarning
    | StepFailed
    | RunCompleted
    | RunFailed,
    Field(discriminator="type"),
]


class EventLog:
    """Append-only recorder that stamps each event with a sequence number."""

    def __init__(self) -> None:
        self._events: list[Event] = []

    def emit(self, event: Event) -> Event:
        event.seq = len(self._events)
        self._events.append(event)
        return event

    @property
    def events(self) -> list[Event]:
        return list(self._events)

    def of_type(self, *types: type) -> list[Event]:
        return [e for e in self._events if isinstance(e, types)]
