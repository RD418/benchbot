"""BenchBot domain layer: pure models and validation, no I/O."""

from __future__ import annotations

from benchbot.domain.errors import (
    BenchBotError,
    Issue,
    ProtocolValidationError,
    Severity,
    ValidationResult,
)
from benchbot.domain.labware import (
    DECK_SLOTS,
    STANDARD_LABWARE,
    LabwareDefinition,
    LabwareKind,
    get_definition,
)
from benchbot.domain.loader import load_protocol_file, load_protocol_text
from benchbot.domain.protocol import (
    AspirateStep,
    DispenseStep,
    LabwarePlacement,
    Liquid,
    MixStep,
    Protocol,
    ProtocolBuilder,
    ProtocolMetadata,
    TransferStep,
)
from benchbot.domain.validation import validate

__all__ = [
    "DECK_SLOTS",
    "STANDARD_LABWARE",
    "AspirateStep",
    "BenchBotError",
    "DispenseStep",
    "Issue",
    "LabwareDefinition",
    "LabwareKind",
    "LabwarePlacement",
    "Liquid",
    "MixStep",
    "Protocol",
    "ProtocolBuilder",
    "ProtocolMetadata",
    "ProtocolValidationError",
    "Severity",
    "TransferStep",
    "ValidationResult",
    "get_definition",
    "load_protocol_file",
    "load_protocol_text",
    "validate",
]
