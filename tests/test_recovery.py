"""Integration tests: the runner driving the mock instrument through faults."""

from __future__ import annotations

from benchbot.domain.protocol import Protocol, ProtocolBuilder
from benchbot.engine.events import (
    CommandAcked,
    CommandSent,
    RecoveryFailed,
    RetryScheduled,
)
from benchbot.engine.retry import RetryPolicy
from benchbot.engine.runner import RunStatus, SimulationRunner
from benchbot.instruments.faults import Outcome, RandomFaults, ScriptedFaults
from benchbot.instruments.mock_serial import MockSerialInstrument


def _single_transfer() -> Protocol:
    return (
        ProtocolBuilder("one transfer")
        .add_plate("p", "plate_96_wellplate_200ul", slot=1)
        .add_tiprack("t", "tiprack_300ul", slot=2)
        .fill("p:A1", 100)
        .transfer("p:A1", "p:A2", 50)
        .build()
    )


def _multi_step() -> Protocol:
    return (
        ProtocolBuilder("many")
        .add_plate("p", "plate_96_wellplate_200ul", slot=1)
        .add_tiprack("t", "tiprack_300ul", slot=2)
        .fill("p:A1", 200)
        .transfer("p:A1", "p:A2", 40)
        .transfer("p:A1", "p:A3", 40)
        .mix("p:A2", 20, repeats=2)
        .transfer("p:A2", "p:A4", 20)
        .build()
    )


def test_clean_run_emits_command_events() -> None:
    result = SimulationRunner().run(_single_transfer())
    assert result.status is RunStatus.COMPLETED
    assert any(isinstance(e, CommandSent) for e in result.events)
    assert any(isinstance(e, CommandAcked) for e in result.events)
    assert not any(isinstance(e, (RetryScheduled, RecoveryFailed)) for e in result.events)


def test_transient_fault_recovers() -> None:
    # First command attempt NAKs, then everything succeeds.
    instrument = MockSerialInstrument(ScriptedFaults([Outcome.TRANSIENT]))
    result = SimulationRunner(instrument).run(_single_transfer())
    assert result.status is RunStatus.COMPLETED
    retries = [e for e in result.events if isinstance(e, RetryScheduled)]
    assert len(retries) == 1
    assert retries[0].code == "E_INSTRUMENT_NAK"


def test_hard_error_aborts_run() -> None:
    instrument = MockSerialInstrument(ScriptedFaults([Outcome.HARD]))
    result = SimulationRunner(instrument).run(_single_transfer())
    assert result.status is RunStatus.FAILED
    assert result.failure is not None and result.failure.code == "E_HARDWARE_FAILURE"
    assert any(isinstance(e, RecoveryFailed) for e in result.events)
    # A hardware fault is never retried.
    assert not any(isinstance(e, RetryScheduled) for e in result.events)


def test_retries_exhausted_aborts_run() -> None:
    instrument = MockSerialInstrument(ScriptedFaults([Outcome.TRANSIENT, Outcome.TRANSIENT]))
    runner = SimulationRunner(instrument, RetryPolicy(max_attempts=2))
    result = runner.run(_single_transfer())
    assert result.status is RunStatus.FAILED
    assert result.failure is not None and result.failure.code == "E_INSTRUMENT_NAK"
    assert len([e for e in result.events if isinstance(e, RetryScheduled)]) == 1
    assert any(isinstance(e, RecoveryFailed) for e in result.events)


def test_same_seed_produces_identical_runs() -> None:
    def run_once() -> tuple[str, list[str], dict[str, float]]:
        instrument = MockSerialInstrument(RandomFaults(seed=7, transient_rate=0.3))
        result = SimulationRunner(instrument).run(_multi_step())
        return (
            result.status.value,
            [e.type for e in result.events],  # type: ignore[attr-defined]
            result.final_state,
        )

    assert run_once() == run_once()
