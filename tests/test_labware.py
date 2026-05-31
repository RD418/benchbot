from __future__ import annotations

import pytest

from benchbot.domain.labware import get_definition, parse_well_address


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("A1", (0, 0)),
        ("a1", (0, 0)),
        ("H12", (7, 11)),
        (" B3 ", (1, 2)),
    ],
)
def test_parse_well_address_ok(address: str, expected: tuple[int, int]) -> None:
    assert parse_well_address(address) == expected


@pytest.mark.parametrize("address", ["", "1A", "AA1", "A", "A0", "12", "A-1"])
def test_parse_well_address_rejects_malformed(address: str) -> None:
    assert parse_well_address(address) is None


def test_has_well_respects_geometry() -> None:
    plate = get_definition("plate_96_wellplate_200ul")
    assert plate is not None
    assert plate.has_well("A1")
    assert plate.has_well("H12")
    assert not plate.has_well("I1")  # row 9 does not exist on an 8-row plate
    assert not plate.has_well("A13")  # column 13 does not exist on a 12-col plate


def test_well_addresses_count() -> None:
    plate = get_definition("plate_96_wellplate_200ul")
    assert plate is not None
    assert plate.well_count == 96
    assert len(plate.well_addresses()) == 96
    assert plate.well_addresses()[0] == "A1"


def test_unknown_definition_is_none() -> None:
    assert get_definition("does_not_exist") is None
