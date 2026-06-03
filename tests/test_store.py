from __future__ import annotations

from pathlib import Path

from benchbot.domain.loader import load_protocol_file
from benchbot.domain.protocol import Protocol, ProtocolBuilder
from benchbot.engine.events import RunStarted
from benchbot.engine.runner import RunStatus, SimulationRunner
from benchbot.instruments.faults import Outcome, ScriptedFaults
from benchbot.instruments.mock_serial import MockSerialInstrument
from benchbot.store.projections import project_status
from benchbot.store.repository import RunStore

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _serial() -> Protocol:
    return load_protocol_file(EXAMPLES / "serial_dilution.yaml")


def _single_transfer() -> Protocol:
    return (
        ProtocolBuilder("one")
        .add_plate("p", "plate_96_wellplate_200ul", slot=1)
        .add_tiprack("t", "tiprack_300ul", slot=2)
        .fill("p:A1", 100)
        .transfer("p:A1", "p:A2", 50)
        .build()
    )


async def _save(store: RunStore, protocol: Protocol, runner: SimulationRunner) -> str:
    result = runner.run(protocol)
    return await store.save_result(
        result, protocol_name=protocol.metadata.name, total_steps=len(protocol.steps)
    )


async def test_save_and_get_run(store: RunStore) -> None:
    protocol = _serial()
    run_id = await _save(store, protocol, SimulationRunner())
    run = await store.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.COMPLETED
    assert run.protocol_name == "Serial dilution"
    assert run.total_steps == len(protocol.steps)
    assert run.failure_code is None


async def test_events_round_trip_losslessly(store: RunStore) -> None:
    protocol = _serial()
    result = SimulationRunner().run(protocol)
    run_id = await store.save_result(
        result, protocol_name=protocol.metadata.name, total_steps=len(protocol.steps)
    )
    stored = await store.get_events(run_id)
    assert [e.type for e in stored] == [e.type for e in result.events]  # type: ignore[attr-defined]
    assert [e.seq for e in stored] == list(range(len(stored)))
    assert isinstance(stored[0], RunStarted)


async def test_status_reconstructs_from_events(store: RunStore) -> None:
    run_id = await _save(store, _serial(), SimulationRunner())
    run = await store.get_run(run_id)
    assert run is not None
    # The cached projection and the live reconstruction must agree.
    assert await store.reconstruct_status(run_id) is RunStatus.COMPLETED
    assert await store.reconstruct_status(run_id) is run.status


async def test_failed_run_persists_failure(store: RunStore) -> None:
    runner = SimulationRunner(MockSerialInstrument(ScriptedFaults([Outcome.HARD])))
    run_id = await _save(store, _single_transfer(), runner)
    run = await store.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.FAILED
    assert run.failure_code == "E_HARDWARE_FAILURE"
    assert await store.reconstruct_status(run_id) is RunStatus.FAILED


async def test_invalid_run_persists_without_events(store: RunStore) -> None:
    protocol = load_protocol_file(EXAMPLES / "invalid_protocol.yaml")
    run_id = await _save(store, protocol, SimulationRunner())
    run = await store.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.INVALID
    assert await store.get_events(run_id) == []
    assert await store.reconstruct_status(run_id) is RunStatus.INVALID


async def test_list_runs_returns_all_saved(store: RunStore) -> None:
    runner = SimulationRunner()
    first = await _save(store, _single_transfer(), runner)
    second = await _save(store, _serial(), runner)
    runs = await store.list_runs()
    assert {r.id for r in runs} == {first, second}


async def test_missing_run_is_none_and_has_no_events(store: RunStore) -> None:
    assert await store.get_run("does-not-exist") is None
    assert await store.get_events("does-not-exist") == []


def test_project_status_with_no_events_is_invalid() -> None:
    assert project_status([]) is RunStatus.INVALID
