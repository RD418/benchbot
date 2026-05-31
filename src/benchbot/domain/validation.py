"""Static (pre-run) validation of a protocol.

This catches everything checkable without executing the protocol: unknown
labware, slot collisions, malformed well references, non-positive or
over-capacity volumes, source==destination transfers, and missing tip racks.
Dynamic checks that depend on live deck state (e.g. aspirating more than is
present) are handled by the engine in a later milestone.

Each finding is an :class:`Issue` with a stable ``code``; the codes are
documented in the project README.
"""

from __future__ import annotations

from benchbot.domain.errors import Issue, Severity, ValidationResult
from benchbot.domain.labware import (
    DECK_SLOTS,
    LabwareDefinition,
    LabwareKind,
    get_definition,
)
from benchbot.domain.protocol import (
    AspirateStep,
    DispenseStep,
    LabwarePlacement,
    MixStep,
    Protocol,
    TransferStep,
    split_well_ref,
)


def validate(protocol: Protocol) -> ValidationResult:
    """Run all static checks and return the collected issues."""
    issues: list[Issue] = []

    placements = _validate_labware(protocol, issues)
    _validate_liquids(protocol, placements, issues)
    _validate_steps(protocol, placements, issues)

    return ValidationResult(issues=issues)


# --- Labware -------------------------------------------------------------------


def _validate_labware(
    protocol: Protocol, issues: list[Issue]
) -> dict[str, tuple[LabwarePlacement, LabwareDefinition]]:
    """Validate placements and return the resolvable ones, keyed by id."""
    resolved: dict[str, tuple[LabwarePlacement, LabwareDefinition]] = {}
    seen_ids: set[str] = set()
    slot_owner: dict[int, str] = {}

    for placement in protocol.labware:
        if placement.id in seen_ids:
            issues.append(
                Issue(
                    severity=Severity.ERROR,
                    code="E_DUP_LABWARE_ID",
                    message=f"Duplicate labware id '{placement.id}'.",
                    location=placement.id,
                )
            )
            continue
        seen_ids.add(placement.id)

        definition = get_definition(placement.type)
        if definition is None:
            issues.append(
                Issue(
                    severity=Severity.ERROR,
                    code="E_UNKNOWN_LABWARE_TYPE",
                    message=f"Unknown labware type '{placement.type}'.",
                    location=placement.id,
                )
            )
            continue

        if not (1 <= placement.slot <= DECK_SLOTS):
            issues.append(
                Issue(
                    severity=Severity.ERROR,
                    code="E_SLOT_OUT_OF_RANGE",
                    message=(
                        f"Slot {placement.slot} is out of range "
                        f"(deck has slots 1-{DECK_SLOTS})."
                    ),
                    location=placement.id,
                )
            )
        elif placement.slot in slot_owner:
            issues.append(
                Issue(
                    severity=Severity.ERROR,
                    code="E_SLOT_OCCUPIED",
                    message=(
                        f"Slot {placement.slot} already used by "
                        f"'{slot_owner[placement.slot]}'."
                    ),
                    location=placement.id,
                )
            )
        else:
            slot_owner[placement.slot] = placement.id

        resolved[placement.id] = (placement, definition)

    return resolved


# --- Liquids -------------------------------------------------------------------


def _validate_liquids(
    protocol: Protocol,
    placements: dict[str, tuple[LabwarePlacement, LabwareDefinition]],
    issues: list[Issue],
) -> None:
    for liquid in protocol.liquids:
        definition = _resolve_well(liquid.well, placements, issues, location=liquid.well)
        if definition is None:
            continue
        if liquid.volume_ul <= 0:
            issues.append(
                Issue(
                    severity=Severity.ERROR,
                    code="E_VOLUME_NOT_POSITIVE",
                    message=f"Liquid volume must be > 0, got {liquid.volume_ul}.",
                    location=liquid.well,
                )
            )
        elif liquid.volume_ul > definition.well_capacity_ul:
            issues.append(
                Issue(
                    severity=Severity.ERROR,
                    code="E_VOLUME_EXCEEDS_CAPACITY",
                    message=(
                        f"Liquid volume {liquid.volume_ul}uL exceeds well capacity "
                        f"{definition.well_capacity_ul}uL."
                    ),
                    location=liquid.well,
                )
            )


# --- Steps ---------------------------------------------------------------------


def _validate_steps(
    protocol: Protocol,
    placements: dict[str, tuple[LabwarePlacement, LabwareDefinition]],
    issues: list[Issue],
) -> None:
    has_tiprack = any(
        defn.kind is LabwareKind.TIPRACK for _, defn in placements.values()
    )
    needs_tip = False

    for index, step in enumerate(protocol.steps):
        if isinstance(step, TransferStep):
            needs_tip = needs_tip or step.new_tip
            src = _resolve_well(step.source, placements, issues, index, step.source)
            dst = _resolve_well(step.dest, placements, issues, index, step.dest)
            if step.source == step.dest:
                issues.append(
                    Issue(
                        severity=Severity.ERROR,
                        code="E_SAME_SOURCE_DEST",
                        message="Transfer source and destination are the same well.",
                        step_index=index,
                        location=step.source,
                    )
                )
            # Volume must fit the smaller of the two wells involved.
            capacities = [d.well_capacity_ul for d in (src, dst) if d is not None]
            _check_volume(
                step.volume_ul,
                min(capacities) if capacities else None,
                issues,
                index,
                step.dest,
            )
        elif isinstance(step, (AspirateStep, DispenseStep, MixStep)):
            defn = _resolve_well(step.well, placements, issues, index, step.well)
            _check_volume(
                step.volume_ul,
                defn.well_capacity_ul if defn else None,
                issues,
                index,
                step.well,
            )

    if needs_tip and not has_tiprack:
        issues.append(
            Issue(
                severity=Severity.ERROR,
                code="E_NO_TIPRACK",
                message="Protocol uses fresh tips but no tip rack is placed on the deck.",
            )
        )


# --- Helpers -------------------------------------------------------------------


def _resolve_well(
    ref: str,
    placements: dict[str, tuple[LabwarePlacement, LabwareDefinition]],
    issues: list[Issue],
    step_index: int | None = None,
    location: str | None = None,
) -> LabwareDefinition | None:
    """Resolve a well ref to its labware definition, recording issues if invalid."""
    parsed = split_well_ref(ref)
    if parsed is None:
        issues.append(
            Issue(
                severity=Severity.ERROR,
                code="E_BAD_WELL_REF",
                message=f"Malformed well reference '{ref}' (expected 'labware:well').",
                step_index=step_index,
                location=location or ref,
            )
        )
        return None

    labware_id, address = parsed
    entry = placements.get(labware_id)
    if entry is None:
        issues.append(
            Issue(
                severity=Severity.ERROR,
                code="E_UNKNOWN_LABWARE_REF",
                message=f"Reference to unknown labware '{labware_id}'.",
                step_index=step_index,
                location=location or ref,
            )
        )
        return None

    _, definition = entry
    if not definition.has_well(address):
        issues.append(
            Issue(
                severity=Severity.ERROR,
                code="E_INVALID_WELL",
                message=(
                    f"Well '{address}' does not exist on '{labware_id}' "
                    f"({definition.rows}x{definition.columns})."
                ),
                step_index=step_index,
                location=location or ref,
            )
        )
        return None

    return definition


def _check_volume(
    volume_ul: float,
    capacity_ul: float | None,
    issues: list[Issue],
    step_index: int,
    location: str,
) -> None:
    if volume_ul <= 0:
        issues.append(
            Issue(
                severity=Severity.ERROR,
                code="E_VOLUME_NOT_POSITIVE",
                message=f"Volume must be > 0, got {volume_ul}.",
                step_index=step_index,
                location=location,
            )
        )
    elif capacity_ul is not None and volume_ul > capacity_ul:
        issues.append(
            Issue(
                severity=Severity.ERROR,
                code="E_VOLUME_EXCEEDS_CAPACITY",
                message=f"Volume {volume_ul}uL exceeds well capacity {capacity_ul}uL.",
                step_index=step_index,
                location=location,
            )
        )
