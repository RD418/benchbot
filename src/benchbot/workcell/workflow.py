"""The workflow model: a DAG of tasks across heterogeneous devices.

A :class:`Workflow` is the multi-instrument analogue of a single-device
``Protocol``. Each task targets a device by name and may declare ``depends_on``
edges (e.g. *read* must run after *incubate*). Tasks are a discriminated union
keyed on ``type`` — the same pattern used for protocol steps and events.

``validate_workflow`` performs static checks (unknown device, kind mismatch,
unknown/cyclic dependencies) before anything executes — the work-cell-level
counterpart to protocol validation.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from benchbot.domain.errors import Issue, Severity, ValidationResult
from benchbot.domain.protocol import Protocol
from benchbot.workcell.devices import DeviceKind


class _BaseTask(BaseModel):
    id: str
    device: str
    depends_on: list[str] = []


class RunProtocolTask(_BaseTask):
    type: Literal["run_protocol"] = "run_protocol"
    protocol: Protocol


class ReadPlateTask(_BaseTask):
    type: Literal["read_plate"] = "read_plate"
    plate: str
    wavelength_nm: int = 600


class IncubateTask(_BaseTask):
    type: Literal["incubate"] = "incubate"
    minutes: float
    celsius: float


Task = Annotated[
    RunProtocolTask | ReadPlateTask | IncubateTask,
    Field(discriminator="type"),
]


class Workflow(BaseModel):
    name: str = "untitled"
    tasks: list[Task] = []


#: Which device kind each task type must run on.
REQUIRED_KIND: dict[str, DeviceKind] = {
    "run_protocol": DeviceKind.LIQUID_HANDLER,
    "read_plate": DeviceKind.PLATE_READER,
    "incubate": DeviceKind.INCUBATOR,
}


def validate_workflow(workflow: Workflow, device_kinds: dict[str, DeviceKind]) -> ValidationResult:
    """Static checks against the available devices."""
    issues: list[Issue] = []
    ids: set[str] = set()

    for index, task in enumerate(workflow.tasks):
        if task.id in ids:
            _err(issues, "E_DUP_TASK_ID", f"Duplicate task id '{task.id}'.", index, task.id)
        ids.add(task.id)

        kind = device_kinds.get(task.device)
        if kind is None:
            _err(issues, "E_UNKNOWN_DEVICE", f"Unknown device '{task.device}'.", index, task.id)
        elif kind is not REQUIRED_KIND[task.type]:
            _err(
                issues,
                "E_DEVICE_KIND_MISMATCH",
                f"Task '{task.type}' needs a {REQUIRED_KIND[task.type].value}, "
                f"but '{task.device}' is a {kind.value}.",
                index,
                task.id,
            )

    # Dependencies must reference existing tasks and form no cycle.
    for index, task in enumerate(workflow.tasks):
        for dep in task.depends_on:
            if dep == task.id:
                _err(
                    issues,
                    "E_SELF_DEPENDENCY",
                    f"Task '{task.id}' depends on itself.",
                    index,
                    task.id,
                )
            elif dep not in ids:
                _err(
                    issues,
                    "E_UNKNOWN_DEPENDENCY",
                    f"Task '{task.id}' depends on unknown task '{dep}'.",
                    index,
                    task.id,
                )

    if _has_cycle(workflow.tasks):
        _err(issues, "E_DEPENDENCY_CYCLE", "Workflow dependencies contain a cycle.")

    return ValidationResult(issues=issues)


def topological_order(tasks: list[Task]) -> list[Task]:
    """Return tasks in dependency order (Kahn's algorithm), preserving input order.

    Assumes the workflow already passed :func:`validate_workflow` (no cycles,
    known dependencies).
    """
    by_id = {t.id: t for t in tasks}
    indegree = {t.id: 0 for t in tasks}
    successors: dict[str, list[str]] = {t.id: [] for t in tasks}
    for task in tasks:
        for dep in task.depends_on:
            successors[dep].append(task.id)
            indegree[task.id] += 1

    queue = [t.id for t in tasks if indegree[t.id] == 0]
    order: list[str] = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        for nxt in successors[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    return [by_id[i] for i in order]


# --- Helpers -------------------------------------------------------------------


def _has_cycle(tasks: list[Task]) -> bool:
    ids = {t.id for t in tasks}
    indegree = {t.id: 0 for t in tasks}
    successors: dict[str, list[str]] = {t.id: [] for t in tasks}
    for task in tasks:
        for dep in task.depends_on:
            if dep in ids:  # ignore unknown deps (reported separately)
                successors[dep].append(task.id)
                indegree[task.id] += 1
    queue = [tid for tid, d in indegree.items() if d == 0]
    visited = 0
    while queue:
        node = queue.pop()
        visited += 1
        for nxt in successors[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    return visited != len(tasks)


def _err(
    issues: list[Issue],
    code: str,
    message: str,
    step_index: int | None = None,
    location: str | None = None,
) -> None:
    issues.append(
        Issue(
            severity=Severity.ERROR,
            code=code,
            message=message,
            step_index=step_index,
            location=location,
        )
    )
