from __future__ import annotations

from pathlib import Path

from benchbot.domain.loader import load_protocol_file
from benchbot.domain.protocol import ProtocolBuilder
from benchbot.engine.events import RunStarted, StepFailed, StepWarning
from benchbot.engine.runner import RunStatus, SimulationRunner

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_serial_dilution_completes_with_expected_state() -> None:
    protocol = load_protocol_file(EXAMPLES / "serial_dilution.yaml")
    result = SimulationRunner().run(protocol)
    assert result.status is RunStatus.COMPLETED
    assert result.ok
    assert result.final_state == {
        "plate1:A1": 100.0,
        "plate1:A2": 100.0,
        "plate1:A3": 200.0,
        "trough:A1": 9800.0,
    }


def test_event_sequence_is_monotonic() -> None:
    protocol = load_protocol_file(EXAMPLES / "serial_dilution.yaml")
    result = SimulationRunner().run(protocol)
    seqs = [e.seq for e in result.events]
    assert seqs == list(range(len(seqs)))
    assert isinstance(result.events[0], RunStarted)


def test_invalid_protocol_is_not_executed() -> None:
    protocol = load_protocol_file(EXAMPLES / "invalid_protocol.yaml")
    result = SimulationRunner().run(protocol)
    assert result.status is RunStatus.INVALID
    assert result.validation is not None and not result.validation.ok
    assert result.events == []  # never started
    assert result.failure is not None


def test_insufficient_volume_fails_run() -> None:
    protocol = (
        ProtocolBuilder("drain")
        .add_plate("p", "plate_96_wellplate_200ul", slot=1)
        .add_tiprack("t", "tiprack_300ul", slot=2)
        .fill("p:A1", 50)
        .transfer("p:A1", "p:A2", 100)  # only 50uL available
        .build()
    )
    result = SimulationRunner().run(protocol)
    assert result.status is RunStatus.FAILED
    assert result.failure is not None
    assert result.failure.code == "E_INSUFFICIENT_VOLUME"
    assert result.failure.step_index == 0
    assert any(isinstance(e, StepFailed) for e in result.events)


def test_overfill_fails_run() -> None:
    protocol = (
        ProtocolBuilder("flood")
        .add_plate("p", "plate_96_wellplate_200ul", slot=1)
        .add_tiprack("t", "tiprack_1000ul", slot=2)
        .fill("p:A1", 200)
        .fill("p:A2", 180)
        .transfer("p:A1", "p:A2", 100)  # 180 + 100 > 200 capacity
        .build()
    )
    result = SimulationRunner().run(protocol)
    assert result.status is RunStatus.FAILED
    assert result.failure is not None and result.failure.code == "E_OVERFILL"


def test_tip_overflow_fails_run() -> None:
    protocol = (
        ProtocolBuilder("big gulp")
        .add_reservoir("r", "reservoir_12col_15ml", slot=1)
        .add_reservoir("r2", "reservoir_12col_15ml", slot=2)
        .add_tiprack("t", "tiprack_300ul", slot=3)
        .fill("r:A1", 5000)
        .transfer("r:A1", "r2:A1", 500)  # 500uL into a 300uL tip
        .build()
    )
    result = SimulationRunner().run(protocol)
    assert result.status is RunStatus.FAILED
    assert result.failure is not None and result.failure.code == "E_TIP_OVERFLOW"


def test_tip_carryover_warning_on_reuse() -> None:
    protocol = (
        ProtocolBuilder("reuse")
        .add_plate("p", "plate_96_wellplate_200ul", slot=1)
        .add_tiprack("t", "tiprack_300ul", slot=2)
        .fill("p:A1", 100)
        .fill("p:A2", 100)
        .transfer("p:A1", "p:A3", 50, new_tip=True)
        .transfer("p:A2", "p:A3", 50, new_tip=False)  # reuses tip across wells
        .build()
    )
    result = SimulationRunner().run(protocol)
    assert result.status is RunStatus.COMPLETED  # warning does not fail the run
    warnings = [e for e in result.events if isinstance(e, StepWarning)]
    assert any(w.code == "W_TIP_CARRYOVER" for w in warnings)
