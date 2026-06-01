"""The virtual deck: live well volumes, tip inventory, and the pipette.

This is the stateful core that lets BenchBot catch problems a static checker
can't — e.g. aspirating more liquid than a well currently holds, overfilling a
destination after several transfers, or running out of tips mid-run. Each such
problem is raised as a :class:`SimulationError` carrying a stable code, which
the runner turns into a ``StepFailed`` event.
"""

from __future__ import annotations

from dataclasses import dataclass

from benchbot.domain.errors import BenchBotError
from benchbot.domain.labware import LabwareDefinition, LabwareKind, get_definition
from benchbot.domain.protocol import Protocol, split_well_ref

#: Floating-point tolerance for volume comparisons (microliters).
EPSILON = 1e-9


class SimulationError(BenchBotError):
    """A dynamic (runtime) validation failure during simulation."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass
class Pipette:
    """A single-channel pipette and the tip currently mounted on it."""

    has_tip: bool = False
    tip_id: str | None = None
    tip_capacity_ul: float = 0.0
    tip_volume_ul: float = 0.0
    #: True immediately after a fresh tip is mounted, until the first aspirate.
    fresh: bool = False
    #: Last well aspirated from, used to detect cross-contamination on tip reuse.
    last_source: str | None = None


@dataclass
class _TipRack:
    labware_id: str
    addresses: list[str]
    capacity_ul: float
    used: int = 0

    @property
    def remaining(self) -> int:
        return len(self.addresses) - self.used


class DeckState:
    """Mutable simulation state built from a (statically valid) protocol."""

    def __init__(self) -> None:
        self._defs: dict[str, LabwareDefinition] = {}
        self._volumes: dict[str, float] = {}  # "labware:well" -> volume
        self._tipracks: list[_TipRack] = []
        self.pipette = Pipette()

    # --- Construction ---------------------------------------------------------

    @classmethod
    def from_protocol(cls, protocol: Protocol) -> DeckState:
        deck = cls()
        for placement in protocol.labware:
            definition = get_definition(placement.type)
            if definition is None:
                # Should be caught by static validation; guard defensively.
                raise SimulationError(
                    "E_UNKNOWN_LABWARE_TYPE",
                    f"Unknown labware type '{placement.type}'.",
                )
            deck._defs[placement.id] = definition
            if definition.kind is LabwareKind.TIPRACK:
                deck._tipracks.append(
                    _TipRack(
                        labware_id=placement.id,
                        addresses=definition.well_addresses(),
                        capacity_ul=definition.well_capacity_ul,
                    )
                )
        for liquid in protocol.liquids:
            deck._volumes[liquid.well] = deck._volumes.get(liquid.well, 0.0) + liquid.volume_ul
        return deck

    # --- Wells ----------------------------------------------------------------

    def _definition_for(self, ref: str) -> LabwareDefinition:
        parsed = split_well_ref(ref)
        if parsed is None or parsed[0] not in self._defs:
            raise SimulationError("E_UNKNOWN_LABWARE_REF", f"Unknown well '{ref}'.")
        return self._defs[parsed[0]]

    def volume(self, ref: str) -> float:
        return self._volumes.get(ref, 0.0)

    def capacity(self, ref: str) -> float:
        return self._definition_for(ref).well_capacity_ul

    def remove_liquid(self, ref: str, volume_ul: float) -> None:
        current = self.volume(ref)
        if volume_ul > current + EPSILON:
            raise SimulationError(
                "E_INSUFFICIENT_VOLUME",
                f"Cannot aspirate {volume_ul}uL from '{ref}' holding {current}uL.",
            )
        self._volumes[ref] = current - volume_ul

    def add_liquid(self, ref: str, volume_ul: float) -> None:
        current = self.volume(ref)
        capacity = self.capacity(ref)
        if current + volume_ul > capacity + EPSILON:
            raise SimulationError(
                "E_OVERFILL",
                f"Dispensing {volume_ul}uL into '{ref}' "
                f"(holds {current}uL) exceeds capacity {capacity}uL.",
            )
        self._volumes[ref] = current + volume_ul

    # --- Tips -----------------------------------------------------------------

    def take_tip(self) -> tuple[str, float]:
        """Consume the next available tip; return ``(tip_id, capacity_ul)``."""
        for rack in self._tipracks:
            if rack.remaining > 0:
                address = rack.addresses[rack.used]
                rack.used += 1
                return f"{rack.labware_id}:{address}", rack.capacity_ul
        raise SimulationError("E_NO_TIP_AVAILABLE", "No tips remaining on the deck.")

    @property
    def tips_remaining(self) -> int:
        return sum(rack.remaining for rack in self._tipracks)

    # --- Snapshot -------------------------------------------------------------

    def snapshot(self) -> dict[str, float]:
        """Return non-empty well volumes, rounded for readability."""
        return {
            ref: round(vol, 6)
            for ref, vol in sorted(self._volumes.items())
            if abs(vol) > EPSILON
        }
