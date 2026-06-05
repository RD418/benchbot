"""Labware definitions, the deck layout, and well addressing.

A *definition* describes a kind of labware (geometry + capacities); an
*instance* (see :mod:`benchbot.domain.protocol`) places one definition on a
deck slot. Well addresses use the standard ``<row letter><column number>``
convention, e.g. ``A1`` ... ``H12`` for a 96-well plate.
"""

from __future__ import annotations

import re
import string
from enum import StrEnum

from pydantic import BaseModel, Field

#: Number of addressable slots on the simulated deck.
DECK_SLOTS = 12

_WELL_RE = re.compile(r"^([A-Z]+)(\d+)$")


class LabwareKind(StrEnum):
    PLATE = "plate"
    TIPRACK = "tiprack"
    RESERVOIR = "reservoir"


class LabwareDefinition(BaseModel):
    """Geometry and capacity for a kind of labware.

    Attributes:
        name: Registry key, e.g. ``plate_96_wellplate_200ul``.
        kind: Category controlling how it may be used.
        rows: Number of rows (A, B, ...).
        columns: Number of columns (1, 2, ...).
        well_capacity_ul: Max volume a single well/tip/channel can hold.
    """

    name: str
    kind: LabwareKind
    rows: int = Field(gt=0)
    columns: int = Field(gt=0)
    well_capacity_ul: float = Field(gt=0)

    @property
    def well_count(self) -> int:
        return self.rows * self.columns

    def row_letters(self) -> list[str]:
        return list(string.ascii_uppercase[: self.rows])

    def has_well(self, address: str) -> bool:
        parsed = parse_well_address(address)
        if parsed is None:
            return False
        row, col = parsed
        return 0 <= row < self.rows and 0 <= col < self.columns

    def well_addresses(self) -> list[str]:
        return [
            f"{letter}{col}" for letter in self.row_letters() for col in range(1, self.columns + 1)
        ]


def parse_well_address(address: str) -> tuple[int, int] | None:
    """Return zero-based ``(row, column)`` for an address, or ``None`` if malformed.

    Only single-letter rows are supported (A-Z), which covers all standard
    SBS labware up to 26 rows.
    """
    match = _WELL_RE.match(address.strip().upper())
    if not match:
        return None
    letters, digits = match.groups()
    if len(letters) != 1:
        return None
    row = ord(letters) - ord("A")
    col = int(digits) - 1
    if col < 0:
        return None
    return row, col


# --- Standard labware registry -------------------------------------------------
# A small built-in catalog. Real systems load these from JSON definition files
# (as PyLabRobot/Opentrons do); a registry keeps M1 self-contained.

STANDARD_LABWARE: dict[str, LabwareDefinition] = {
    d.name: d
    for d in [
        LabwareDefinition(
            name="plate_96_wellplate_200ul",
            kind=LabwareKind.PLATE,
            rows=8,
            columns=12,
            well_capacity_ul=200.0,
        ),
        LabwareDefinition(
            name="plate_384_wellplate_50ul",
            kind=LabwareKind.PLATE,
            rows=16,
            columns=24,
            well_capacity_ul=50.0,
        ),
        LabwareDefinition(
            name="tiprack_300ul",
            kind=LabwareKind.TIPRACK,
            rows=8,
            columns=12,
            well_capacity_ul=300.0,
        ),
        LabwareDefinition(
            name="tiprack_1000ul",
            kind=LabwareKind.TIPRACK,
            rows=8,
            columns=12,
            well_capacity_ul=1000.0,
        ),
        LabwareDefinition(
            name="reservoir_12col_15ml",
            kind=LabwareKind.RESERVOIR,
            rows=1,
            columns=12,
            well_capacity_ul=15000.0,
        ),
    ]
}


def get_definition(name: str) -> LabwareDefinition | None:
    """Look up a labware definition by registry name."""
    return STANDARD_LABWARE.get(name)
