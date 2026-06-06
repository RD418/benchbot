"""Workflow-level events.

Mirrors the engine's event model one level up: instead of pipetting steps, these
record the lifecycle of *tasks* across *devices* — started, retried, completed,
failed, skipped — plus device quarantine. Same append-only, seq-stamped log
shape, so the same patterns (replay, diagnostics) apply to the work cell.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(UTC)


class _WfBaseEvent(BaseModel):
    seq: int = -1
    timestamp: datetime = Field(default_factory=_now)


class WorkflowStarted(_WfBaseEvent):
    type: Literal["workflow_started"] = "workflow_started"
    workflow_name: str
    total_tasks: int


class TaskStarted(_WfBaseEvent):
    type: Literal["task_started"] = "task_started"
    task_id: str
    device: str
    action: str


class TaskRetry(_WfBaseEvent):
    type: Literal["task_retry"] = "task_retry"
    task_id: str
    device: str
    attempt: int
    code: str
    message: str


class TaskCompleted(_WfBaseEvent):
    type: Literal["task_completed"] = "task_completed"
    task_id: str
    detail: str


class TaskFailed(_WfBaseEvent):
    type: Literal["task_failed"] = "task_failed"
    task_id: str
    device: str
    code: str
    message: str


class TaskSkipped(_WfBaseEvent):
    type: Literal["task_skipped"] = "task_skipped"
    task_id: str
    reason: str


class DeviceQuarantined(_WfBaseEvent):
    type: Literal["device_quarantined"] = "device_quarantined"
    device: str
    code: str
    message: str


class WorkflowFinished(_WfBaseEvent):
    type: Literal["workflow_finished"] = "workflow_finished"
    status: str


WorkflowEvent = Annotated[
    WorkflowStarted
    | TaskStarted
    | TaskRetry
    | TaskCompleted
    | TaskFailed
    | TaskSkipped
    | DeviceQuarantined
    | WorkflowFinished,
    Field(discriminator="type"),
]


class WorkflowEventLog:
    """Append-only recorder that stamps each event with a sequence number."""

    def __init__(self) -> None:
        self._events: list[WorkflowEvent] = []

    def emit(self, event: WorkflowEvent) -> WorkflowEvent:
        event.seq = len(self._events)
        self._events.append(event)
        return event

    @property
    def events(self) -> list[WorkflowEvent]:
        return list(self._events)
