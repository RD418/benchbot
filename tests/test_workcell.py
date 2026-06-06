from __future__ import annotations

from benchbot.domain.protocol import Protocol, ProtocolBuilder
from benchbot.instruments.faults import Outcome, RandomFaults, ScriptedFaults
from benchbot.workcell.cell import (
    TaskOutcome,
    WorkflowStatus,
    build_default_workcell,
)
from benchbot.workcell.devices import DeviceHealth
from benchbot.workcell.recovery import Disposition, RecoveryPolicy
from benchbot.workcell.workflow import (
    IncubateTask,
    ReadPlateTask,
    RunProtocolTask,
    Workflow,
)


def _protocol() -> Protocol:
    return (
        ProtocolBuilder("prep")
        .add_plate("p", "plate_96_wellplate_200ul", 1)
        .add_tiprack("t", "tiprack_300ul", 2)
        .fill("p:A1", 200)
        .transfer("p:A1", "p:A2", 100)
        .build()
    )


def _workflow(*, incubate_first: bool = False) -> Workflow:
    prep = RunProtocolTask(id="prep", device="lh1", protocol=_protocol())
    incubate = IncubateTask(id="incubate", device="inc1", minutes=30, celsius=37)
    read = ReadPlateTask(id="read", device="reader1", plate="p", depends_on=["incubate"])
    tasks = [incubate, prep, read] if incubate_first else [prep, incubate, read]
    return Workflow(name="assay", tasks=tasks)


def _outcomes(result) -> dict[str, TaskOutcome]:
    return {t.id: t.outcome for t in result.tasks}


def test_happy_path_completes_all_tasks() -> None:
    cell = build_default_workcell()
    result = cell.run_workflow(_workflow())
    assert result.status is WorkflowStatus.COMPLETED
    assert _outcomes(result) == {
        "prep": TaskOutcome.COMPLETED,
        "incubate": TaskOutcome.COMPLETED,
        "read": TaskOutcome.COMPLETED,
    }
    assert all(h is DeviceHealth.OK for h in result.device_health.values())


def test_failed_device_does_not_cascade() -> None:
    # The incubator dies; its dependent (read) is skipped, but the independent
    # liquid-handler task still completes. This is graceful degradation.
    cell = build_default_workcell()
    cell.devices["inc1"].set_faults(ScriptedFaults([Outcome.HARD]))
    result = cell.run_workflow(_workflow())

    assert result.status is WorkflowStatus.DEGRADED
    outcomes = _outcomes(result)
    assert outcomes["incubate"] is TaskOutcome.FAILED
    assert outcomes["read"] is TaskOutcome.SKIPPED  # depends on incubate
    assert outcomes["prep"] is TaskOutcome.COMPLETED  # independent, unaffected
    assert result.device_health["inc1"] is DeviceHealth.DOWN
    assert result.device_health["lh1"] is DeviceHealth.OK


def test_skip_reason_names_the_dependency() -> None:
    cell = build_default_workcell()
    cell.devices["inc1"].set_faults(ScriptedFaults([Outcome.HARD]))
    result = cell.run_workflow(_workflow())
    skips = [e for e in result.events if e.type == "task_skipped"]  # type: ignore[attr-defined]
    assert any("incubate" in e.reason for e in skips)  # type: ignore[attr-defined]


def test_halt_policy_stops_the_workflow() -> None:
    cell = build_default_workcell()
    cell.devices["inc1"].set_faults(ScriptedFaults([Outcome.HARD]))
    result = cell.run_workflow(
        _workflow(incubate_first=True), RecoveryPolicy(default=Disposition.HALT)
    )
    assert result.status is WorkflowStatus.HALTED
    outcomes = _outcomes(result)
    assert outcomes["incubate"] is TaskOutcome.FAILED
    assert outcomes["prep"] is TaskOutcome.SKIPPED  # halted before it could run


def test_retry_disposition_recovers() -> None:
    # One hard fault, then the scripted queue is exhausted; task-level RETRY
    # re-runs the whole task and it succeeds.
    cell = build_default_workcell()
    cell.devices["inc1"].set_faults(ScriptedFaults([Outcome.HARD]))
    result = cell.run_workflow(_workflow(), RecoveryPolicy(default=Disposition.RETRY))
    assert result.status is WorkflowStatus.COMPLETED
    assert _outcomes(result)["incubate"] is TaskOutcome.COMPLETED


def test_transient_faults_recover_but_mark_degraded() -> None:
    cell = build_default_workcell()
    # Two transient NAKs then OK: the device's own retry recovers each command.
    cell.devices["inc1"].set_faults(ScriptedFaults([Outcome.TRANSIENT, Outcome.TRANSIENT]))
    result = cell.run_workflow(_workflow())
    assert result.status is WorkflowStatus.COMPLETED
    inc1 = next(d for d in cell.health().devices if d.name == "inc1")
    assert inc1.retries >= 1
    assert inc1.errors >= 1
    assert inc1.error_rate > 0
    assert inc1.health is DeviceHealth.DEGRADED


def test_invalid_workflow_is_rejected() -> None:
    cell = build_default_workcell()
    bad = Workflow(
        tasks=[
            # wrong device kind: a protocol task on the plate reader
            RunProtocolTask(id="x", device="reader1", protocol=_protocol()),
            # dependency on a task that doesn't exist
            IncubateTask(id="y", device="inc1", minutes=1, celsius=37, depends_on=["ghost"]),
        ]
    )
    result = cell.run_workflow(bad)
    assert result.status is WorkflowStatus.INVALID
    assert result.validation is not None
    codes = {i.code for i in result.validation.issues}
    assert "E_DEVICE_KIND_MISMATCH" in codes
    assert "E_UNKNOWN_DEPENDENCY" in codes


def test_dependency_cycle_is_rejected() -> None:
    cell = build_default_workcell()
    cyclic = Workflow(
        tasks=[
            IncubateTask(id="a", device="inc1", minutes=1, celsius=37, depends_on=["b"]),
            IncubateTask(id="b", device="inc1", minutes=1, celsius=37, depends_on=["a"]),
        ]
    )
    result = cell.run_workflow(cyclic)
    assert result.status is WorkflowStatus.INVALID
    assert any(i.code == "E_DEPENDENCY_CYCLE" for i in result.validation.issues)  # type: ignore[union-attr]


def test_same_seed_is_deterministic() -> None:
    def run_once() -> tuple[str, list[str], int]:
        cell = build_default_workcell()
        cell.devices["inc1"].set_faults(RandomFaults(seed=11, transient_rate=0.5))
        result = cell.run_workflow(_workflow())
        inc1 = next(d for d in cell.health().devices if d.name == "inc1")
        return (
            result.status.value,
            [e.type for e in result.events],  # type: ignore[attr-defined]
            inc1.errors,
        )

    assert run_once() == run_once()
