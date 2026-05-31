"""The protocol model: labware placements, initial liquids, and steps.

A :class:`Protocol` can be authored two ways that compile to the same model:

* declaratively from YAML/JSON (see :mod:`benchbot.domain.loader`), or
* programmatically via the fluent :class:`ProtocolBuilder`.

Steps are a discriminated union keyed on ``type`` so new step kinds can be
added without touching the parser.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

#: A reference to a single well, formatted ``<labware id>:<well address>``.
WellRef = str


def split_well_ref(ref: WellRef) -> tuple[str, str] | None:
    """Split ``"plate1:A1"`` into ``("plate1", "A1")``; ``None`` if malformed."""
    parts = ref.split(":")
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        return None
    return parts[0].strip(), parts[1].strip()


class LabwarePlacement(BaseModel):
    """A labware instance placed on a deck slot."""

    id: str
    type: str
    slot: int


class Liquid(BaseModel):
    """An initial volume of liquid pre-loaded into a well."""

    well: WellRef
    volume_ul: float


# --- Steps ---------------------------------------------------------------------


class _BaseStep(BaseModel):
    pass


class TransferStep(_BaseStep):
    type: Literal["transfer"] = "transfer"
    source: WellRef
    dest: WellRef
    volume_ul: float
    new_tip: bool = True


class AspirateStep(_BaseStep):
    type: Literal["aspirate"] = "aspirate"
    well: WellRef
    volume_ul: float


class DispenseStep(_BaseStep):
    type: Literal["dispense"] = "dispense"
    well: WellRef
    volume_ul: float


class MixStep(_BaseStep):
    type: Literal["mix"] = "mix"
    well: WellRef
    volume_ul: float
    repeats: int = Field(default=1, ge=1)


Step = Annotated[
    TransferStep | AspirateStep | DispenseStep | MixStep,
    Field(discriminator="type"),
]


class ProtocolMetadata(BaseModel):
    name: str = "untitled"
    author: str | None = None
    description: str | None = None


class Protocol(BaseModel):
    """A complete, parseable protocol document."""

    version: Literal[1] = 1
    metadata: ProtocolMetadata = Field(default_factory=ProtocolMetadata)
    labware: list[LabwarePlacement] = []
    liquids: list[Liquid] = []
    steps: list[Step] = []


# --- Fluent builder ------------------------------------------------------------


class ProtocolBuilder:
    """Imperative helper that produces an identical :class:`Protocol`.

    Example::

        p = (
            ProtocolBuilder("Serial dilution")
            .add_plate("plate1", "plate_96_wellplate_200ul", slot=1)
            .add_tiprack("tips1", "tiprack_300ul", slot=2)
            .fill("plate1:A1", 200)
            .transfer("plate1:A1", "plate1:A2", 100)
            .build()
        )
    """

    def __init__(self, name: str = "untitled", author: str | None = None) -> None:
        self._meta = ProtocolMetadata(name=name, author=author)
        self._labware: list[LabwarePlacement] = []
        self._liquids: list[Liquid] = []
        self._steps: list[Step] = []

    def add_labware(self, id: str, type: str, slot: int) -> ProtocolBuilder:
        self._labware.append(LabwarePlacement(id=id, type=type, slot=slot))
        return self

    # Convenience aliases (purely cosmetic; same as add_labware).
    add_plate = add_labware
    add_tiprack = add_labware
    add_reservoir = add_labware

    def fill(self, well: WellRef, volume_ul: float) -> ProtocolBuilder:
        self._liquids.append(Liquid(well=well, volume_ul=volume_ul))
        return self

    def transfer(
        self, source: WellRef, dest: WellRef, volume_ul: float, *, new_tip: bool = True
    ) -> ProtocolBuilder:
        self._steps.append(
            TransferStep(source=source, dest=dest, volume_ul=volume_ul, new_tip=new_tip)
        )
        return self

    def aspirate(self, well: WellRef, volume_ul: float) -> ProtocolBuilder:
        self._steps.append(AspirateStep(well=well, volume_ul=volume_ul))
        return self

    def dispense(self, well: WellRef, volume_ul: float) -> ProtocolBuilder:
        self._steps.append(DispenseStep(well=well, volume_ul=volume_ul))
        return self

    def mix(self, well: WellRef, volume_ul: float, repeats: int = 1) -> ProtocolBuilder:
        self._steps.append(MixStep(well=well, volume_ul=volume_ul, repeats=repeats))
        return self

    def build(self) -> Protocol:
        return Protocol(
            metadata=self._meta,
            labware=list(self._labware),
            liquids=list(self._liquids),
            steps=list(self._steps),
        )
