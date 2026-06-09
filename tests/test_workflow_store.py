from __future__ import annotations

from benchbot.instruments.faults import Outcome, ScriptedFaults
from benchbot.store.repository import WorkflowStore
from benchbot.workcell.cell import WorkflowStatus, build_default_workcell, build_demo_workflow
from benchbot.workcell.events import WorkflowStarted
from benchbot.workcell.workflow import Workflow


async def _save_demo(store: WorkflowStore, *, fault: bool = False) -> tuple[str, Workflow]:
    cell = build_default_workcell()
    if fault:
        cell.devices["inc1"].set_faults(ScriptedFaults([Outcome.HARD]))
    workflow = build_demo_workflow()
    result = cell.run_workflow(workflow)
    run_id = await store.save_result(result, workflow=workflow)
    return run_id, workflow


async def test_save_and_get_workflow_run(workflow_store: WorkflowStore) -> None:
    run_id, _ = await _save_demo(workflow_store)
    run = await workflow_store.get_run(run_id)
    assert run is not None
    assert run.name == "assay"
    assert run.status is WorkflowStatus.COMPLETED
    assert {t["id"] for t in run.tasks} == {"prep", "incubate", "read"}
    # The definition is stored so the DAG can be drawn (depends_on preserved).
    read = next(t for t in run.workflow["tasks"] if t["id"] == "read")
    assert read["depends_on"] == ["incubate"]


async def test_events_round_trip(workflow_store: WorkflowStore) -> None:
    run_id, _ = await _save_demo(workflow_store)
    events = await workflow_store.get_events(run_id)
    assert isinstance(events[0], WorkflowStarted)
    assert [e.seq for e in events] == list(range(len(events)))


async def test_status_reconstructs_from_events(workflow_store: WorkflowStore) -> None:
    run_id, _ = await _save_demo(workflow_store, fault=True)
    run = await workflow_store.get_run(run_id)
    assert run is not None and run.status is WorkflowStatus.DEGRADED
    assert await workflow_store.reconstruct_status(run_id) is WorkflowStatus.DEGRADED
    assert run.device_health["inc1"] == "down"


async def test_list_runs_returns_summaries(workflow_store: WorkflowStore) -> None:
    a, _ = await _save_demo(workflow_store)
    b, _ = await _save_demo(workflow_store, fault=True)
    runs = await workflow_store.list_runs()
    assert {r.id for r in runs} == {a, b}
    assert all(r.task_count == 3 for r in runs)


async def test_missing_run_is_none(workflow_store: WorkflowStore) -> None:
    assert await workflow_store.get_run("nope") is None
    assert await workflow_store.get_events("nope") == []


async def test_export_package_includes_metrics_and_events(workflow_store: WorkflowStore) -> None:
    run_id, _ = await _save_demo(workflow_store, fault=True)
    package = await workflow_store.export_package(run_id)
    assert package is not None
    assert package.run.id == run_id
    assert package.task_totals == {"completed": 1, "failed": 1, "skipped": 1}
    inc1 = next(m for m in package.device_metrics if m.name == "inc1")
    assert inc1.quarantined is True
    assert inc1.errors >= 1
    assert len(package.events) == len(await workflow_store.get_events(run_id))


async def test_export_missing_run_is_none(workflow_store: WorkflowStore) -> None:
    assert await workflow_store.export_package("nope") is None
