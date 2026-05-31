from __future__ import annotations

from pathlib import Path

from benchbot.domain.loader import load_protocol_file
from benchbot.domain.protocol import ProtocolBuilder
from benchbot.domain.validation import validate

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _codes(protocol) -> set[str]:
    return {issue.code for issue in validate(protocol).issues}


def test_valid_protocol_has_no_errors() -> None:
    protocol = load_protocol_file(EXAMPLES / "serial_dilution.yaml")
    result = validate(protocol)
    assert result.ok, [str(i) for i in result.errors]
    assert result.errors == []


def test_invalid_example_reports_expected_codes() -> None:
    protocol = load_protocol_file(EXAMPLES / "invalid_protocol.yaml")
    codes = _codes(protocol)
    expected = {
        "E_DUP_LABWARE_ID",
        "E_SLOT_OCCUPIED",
        "E_UNKNOWN_LABWARE_TYPE",
        "E_VOLUME_EXCEEDS_CAPACITY",
        "E_INVALID_WELL",
        "E_SAME_SOURCE_DEST",
        "E_UNKNOWN_LABWARE_REF",
        "E_VOLUME_NOT_POSITIVE",
    }
    assert expected <= codes
    assert not validate(protocol).ok


def test_missing_tiprack_flagged() -> None:
    protocol = (
        ProtocolBuilder("no tips")
        .add_plate("p", "plate_96_wellplate_200ul", slot=1)
        .fill("p:A1", 100)
        .transfer("p:A1", "p:A2", 50, new_tip=True)
        .build()
    )
    assert "E_NO_TIPRACK" in _codes(protocol)


def test_tiprack_not_required_when_reusing_tip() -> None:
    protocol = (
        ProtocolBuilder("reuse tip")
        .add_plate("p", "plate_96_wellplate_200ul", slot=1)
        .fill("p:A1", 100)
        .transfer("p:A1", "p:A2", 50, new_tip=False)
        .build()
    )
    assert "E_NO_TIPRACK" not in _codes(protocol)


def test_slot_out_of_range() -> None:
    protocol = (
        ProtocolBuilder("bad slot")
        .add_plate("p", "plate_96_wellplate_200ul", slot=99)
        .build()
    )
    assert "E_SLOT_OUT_OF_RANGE" in _codes(protocol)


def test_volume_exceeds_smaller_of_two_wells() -> None:
    # 384-well capacity is 50uL; transferring 120uL into it must fail even though
    # the source 96-well plate could hold it.
    protocol = (
        ProtocolBuilder("capacity")
        .add_plate("big", "plate_96_wellplate_200ul", slot=1)
        .add_plate("small", "plate_384_wellplate_50ul", slot=2)
        .add_tiprack("t", "tiprack_300ul", slot=3)
        .fill("big:A1", 200)
        .transfer("big:A1", "small:A1", 120)
        .build()
    )
    assert "E_VOLUME_EXCEEDS_CAPACITY" in _codes(protocol)


def test_malformed_well_ref() -> None:
    protocol = (
        ProtocolBuilder("bad ref")
        .add_plate("p", "plate_96_wellplate_200ul", slot=1)
        .add_tiprack("t", "tiprack_300ul", slot=2)
        .mix("not-a-ref", 10)
        .build()
    )
    assert "E_BAD_WELL_REF" in _codes(protocol)


def test_validation_result_partitions_severity() -> None:
    protocol = load_protocol_file(EXAMPLES / "invalid_protocol.yaml")
    result = validate(protocol)
    assert len(result.errors) == len([i for i in result.issues if i.severity.value == "error"])
    assert all(i.severity.value == "warning" for i in result.warnings)
