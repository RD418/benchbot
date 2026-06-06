"""The work cell: orchestrates a multi-device workflow with graceful degradation.

This is the M7 centerpiece. It schedules tasks in dependency order and, for each:

* skips it if a dependency failed/was skipped, or its device is quarantined;
* otherwise executes it on the target device, routing every instrument command
  through the device's :class:`RetryPolicy` (command-level recovery);
* on failure, consults the :class:`RecoveryPolicy` (task-level recovery) to
  RETRY, SKIP (quarantine the device, keep going), or HALT the workflow.

The defining property: **one device failing does not cascade** — independent
branches keep running, only the failed device's dependents are skipped. Two
recovery layers (command retry vs task disposition) and a third isolation layer
(device quarantine) keep partial failures contained.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from benchbot.domain.errors import BenchBotError, Issue, Severity, ValidationResult
from benchbot.engine.events import CommandSent, RecoveryFailed, RetryScheduled
from benchbot.engine.runner import SimulationRunner
from benchbot.instruments.base import Ack, Command, InstrumentError, RetryableError
from benchbot.instruments.mock_serial import MockSerialInstrument
from benchbot.instruments.mock_tcp import MockTcpInstrument
from benchbot.workcell.devices import Device, DeviceHealth, DeviceKind
from benchbot.workcell.events import (
    DeviceQuarantined,
    TaskCompleted,
    TaskFailed,
    TaskRetry,
    TaskSkipped,
    TaskStarted,
    WorkflowEvent,
    WorkflowEventLog,
    WorkflowFinished,
    WorkflowStarted,
)
from benchbot.workcell.recovery import Disposition, RecoveryPolicy
from benchbot.workcell.workflow import (
    IncubateTask,
    ReadPlateTask,
    RunProtocolTask,
    Task,
    Workflow,
    topological_order,
    validate_workflow,
)


class WorkflowStatus(StrEnum):
    COMPLETED = "completed"  # every task succeeded
    DEGRADED = "degraded"  # finished, but some tasks failed/were skipped
    HALTED = "halted"  # stopped early by a HALT disposition
    INVALID = "invalid"  # rejected by static validation


class TaskOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskState(BaseModel):
    id: str
    device: str
    outcome: TaskOutcome
    detail: str | None = None
    failure: Issue | None = None


class DeviceStatus(BaseModel):
    name: str
    kind: DeviceKind
    health: DeviceHealth
    commands: int
    errors: int
    retries: int
    error_rate: float


class WorkCellHealth(BaseModel):
    devices: list[DeviceStatus] = []


class WorkflowResult(BaseModel):
    status: WorkflowStatus
    tasks: list[TaskState] = []
    events: list[WorkflowEvent] = []
    device_health: dict[str, DeviceHealth] = {}
    validation: ValidationResult | None = None

    @property
    def ok(self) -> bool:
        return self.status is WorkflowStatus.COMPLETED


class TaskError(BenchBotError):
    """A task failed after the device exhausted command-level recovery."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class WorkCell:
    """Holds devices and executes workflows over them."""

    def __init__(self, devices: dict[str, Device], recovery: RecoveryPolicy | None = None) -> None:
        self.devices = devices
        self.recovery = recovery or RecoveryPolicy()

    # --- Public API -----------------------------------------------------------

    def health(self) -> WorkCellHealth:
        """Current per-device status and rolling error rates."""
        return WorkCellHealth(
            devices=[
                DeviceStatus(
                    name=d.name,
                    kind=d.kind,
                    health=d.health,
                    commands=d.commands,
                    errors=d.errors,
                    retries=d.retries,
                    error_rate=round(d.error_rate, 4),
                )
                for d in self.devices.values()
            ]
        )

    def run_workflow(
        self, workflow: Workflow, recovery: RecoveryPolicy | None = None
    ) -> WorkflowResult:
        recovery = recovery or self.recovery
        kinds = {name: d.kind for name, d in self.devices.items()}

        validation = validate_workflow(workflow, kinds)
        if not validation.ok:
            return WorkflowResult(status=WorkflowStatus.INVALID, validation=validation)

        log = WorkflowEventLog()
        log.emit(WorkflowStarted(workflow_name=workflow.name, total_tasks=len(workflow.tasks)))

        outcomes: dict[str, TaskOutcome] = {}
        states: dict[str, TaskState] = {}
        halted = False

        for task in topological_order(workflow.tasks):
            state = self._run_one(task, outcomes, log, recovery, halted=halted)
            states[task.id] = state
            outcomes[task.id] = state.outcome
            if (
                state.outcome is TaskOutcome.FAILED
                and state.failure is not None
                and recovery.decide(state.failure) is Disposition.HALT
            ):
                halted = True

        status = self._final_status(halted, outcomes)
        log.emit(WorkflowFinished(status=status.value))
        return WorkflowResult(
            status=status,
            tasks=[states[t.id] for t in workflow.tasks],
            events=log.events,
            device_health={name: d.health for name, d in self.devices.items()},
        )

    # --- Per-task scheduling --------------------------------------------------

    def _run_one(
        self,
        task: Task,
        outcomes: dict[str, TaskOutcome],
        log: WorkflowEventLog,
        recovery: RecoveryPolicy,
        *,
        halted: bool,
    ) -> TaskState:
        if halted:
            return self._skip(task, log, "workflow halted")

        blocking = next(
            (d for d in task.depends_on if outcomes.get(d) is not TaskOutcome.COMPLETED), None
        )
        if blocking is not None:
            return self._skip(task, log, f"dependency '{blocking}' did not complete")

        device = self.devices[task.device]
        if device.quarantined:
            return self._skip(task, log, f"device '{device.name}' quarantined")

        log.emit(TaskStarted(task_id=task.id, device=device.name, action=_describe(task)))
        try:
            detail = self._execute(task, device, log)
            log.emit(TaskCompleted(task_id=task.id, detail=detail))
            return TaskState(
                id=task.id, device=task.device, outcome=TaskOutcome.COMPLETED, detail=detail
            )
        except TaskError as exc:
            return self._handle_failure(task, device, exc, log, recovery)

    def _handle_failure(
        self,
        task: Task,
        device: Device,
        exc: TaskError,
        log: WorkflowEventLog,
        recovery: RecoveryPolicy,
    ) -> TaskState:
        issue = Issue(severity=Severity.ERROR, code=exc.code, message=exc.message)
        log.emit(
            TaskFailed(task_id=task.id, device=device.name, code=exc.code, message=exc.message)
        )
        disposition = recovery.decide(issue)

        if disposition is Disposition.RETRY:
            try:
                detail = self._execute(task, device, log)
                log.emit(TaskCompleted(task_id=task.id, detail=detail))
                return TaskState(
                    id=task.id, device=task.device, outcome=TaskOutcome.COMPLETED, detail=detail
                )
            except TaskError as retry_exc:
                exc = retry_exc
                issue = Issue(severity=Severity.ERROR, code=exc.code, message=exc.message)
                log.emit(
                    TaskFailed(
                        task_id=task.id, device=device.name, code=exc.code, message=exc.message
                    )
                )
                disposition = Disposition.SKIP  # retry exhausted -> isolate

        if disposition is Disposition.SKIP:
            device.quarantined = True
            log.emit(DeviceQuarantined(device=device.name, code=exc.code, message=exc.message))

        return TaskState(id=task.id, device=task.device, outcome=TaskOutcome.FAILED, failure=issue)

    def _skip(self, task: Task, log: WorkflowEventLog, reason: str) -> TaskState:
        log.emit(TaskSkipped(task_id=task.id, reason=reason))
        return TaskState(id=task.id, device=task.device, outcome=TaskOutcome.SKIPPED)

    # --- Task execution -------------------------------------------------------

    def _execute(self, task: Task, device: Device, log: WorkflowEventLog) -> str:
        if isinstance(task, RunProtocolTask):
            return self._run_protocol(task, device, log)
        if isinstance(task, IncubateTask):
            self._send(
                device, Command(name="SET_TEMP", params={"celsius": task.celsius}), log, task.id
            )
            self._send(
                device, Command(name="INCUBATE", params={"minutes": task.minutes}), log, task.id
            )
            return f"incubated {task.minutes} min at {task.celsius}C"
        if isinstance(task, ReadPlateTask):
            self._send(
                device,
                Command(name="READ_PLATE", params={"plate": task.plate, "nm": task.wavelength_nm}),
                log,
                task.id,
            )
            return f"read {task.plate} at {task.wavelength_nm}nm"
        raise TaskError("E_UNKNOWN_TASK", "Unknown task type.")  # pragma: no cover

    def _run_protocol(self, task: RunProtocolTask, device: Device, log: WorkflowEventLog) -> str:
        # Reuse the full single-device engine; fold its command stats into the device.
        runner = SimulationRunner(device.instrument, device.retry)
        result = runner.run(task.protocol)
        for event in result.events:
            if isinstance(event, CommandSent):
                device.commands += 1
            elif isinstance(event, RetryScheduled):
                device.retries += 1
                device.errors += 1
            elif isinstance(event, RecoveryFailed):
                device.errors += 1
        if not result.ok:
            failure = result.failure
            code = failure.code if failure else "E_RUN_FAILED"
            message = failure.message if failure else "protocol run failed"
            raise TaskError(code, message)
        return f"protocol '{task.protocol.metadata.name}' completed ({len(result.events)} events)"

    def _send(self, device: Device, command: Command, log: WorkflowEventLog, task_id: str) -> Ack:
        attempt = 0

        def attempt_once() -> Ack:
            nonlocal attempt
            attempt += 1
            device.commands += 1
            return device.instrument.send(command)

        def on_retry(attempt_number: int, error: RetryableError) -> None:
            device.retries += 1
            device.errors += 1
            log.emit(
                TaskRetry(
                    task_id=task_id,
                    device=device.name,
                    attempt=attempt_number,
                    code=error.code,
                    message=str(error),
                )
            )

        try:
            return device.retry.run(attempt_once, on_retry)
        except InstrumentError as exc:
            device.errors += 1
            raise TaskError(exc.code, str(exc)) from exc

    @staticmethod
    def _final_status(halted: bool, outcomes: dict[str, TaskOutcome]) -> WorkflowStatus:
        if halted:
            return WorkflowStatus.HALTED
        if any(o is not TaskOutcome.COMPLETED for o in outcomes.values()):
            return WorkflowStatus.DEGRADED
        return WorkflowStatus.COMPLETED


def _describe(task: Task) -> str:
    if isinstance(task, RunProtocolTask):
        return f"run protocol '{task.protocol.metadata.name}'"
    if isinstance(task, IncubateTask):
        return f"incubate {task.minutes}min @ {task.celsius}C"
    if isinstance(task, ReadPlateTask):
        return f"read {task.plate} @ {task.wavelength_nm}nm"
    return "unknown"  # pragma: no cover


def build_default_workcell() -> WorkCell:
    """A canonical 3-device cell: liquid handler (serial), reader + incubator (TCP)."""
    devices = {
        "lh1": Device("lh1", DeviceKind.LIQUID_HANDLER, MockSerialInstrument()),
        "reader1": Device("reader1", DeviceKind.PLATE_READER, MockTcpInstrument()),
        "inc1": Device("inc1", DeviceKind.INCUBATOR, MockTcpInstrument()),
    }
    return WorkCell(devices)
