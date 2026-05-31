"""Structured error and validation primitives.

Every validation problem is reported as an :class:`Issue` with a stable
machine-readable ``code`` rather than a bare string, so the API and CLI can
surface rich, filterable diagnostics. The codes are documented in the README.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class Severity(StrEnum):
    """How serious a validation issue is."""

    ERROR = "error"
    WARNING = "warning"


class Issue(BaseModel):
    """A single validation finding.

    Attributes:
        severity: ``ERROR`` blocks execution; ``WARNING`` is advisory.
        code: Stable identifier, e.g. ``E_VOLUME_EXCEEDS_CAPACITY``.
        message: Human-readable explanation.
        step_index: Index into ``Protocol.steps`` when the issue is step-scoped.
        location: Free-form pointer (e.g. a well ref or labware id).
    """

    severity: Severity
    code: str
    message: str
    step_index: int | None = None
    location: str | None = None

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        where = ""
        if self.step_index is not None:
            where = f" [step {self.step_index}]"
        if self.location:
            where += f" ({self.location})"
        return f"{self.severity.value.upper()} {self.code}{where}: {self.message}"


class ValidationResult(BaseModel):
    """The outcome of validating a protocol."""

    issues: list[Issue] = []

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.WARNING]

    @property
    def ok(self) -> bool:
        """True when there are no blocking errors (warnings are allowed)."""
        return not self.errors


class BenchBotError(Exception):
    """Base class for BenchBot domain errors."""


class ProtocolValidationError(BenchBotError):
    """Raised when an invalid protocol is asked to execute."""

    def __init__(self, result: ValidationResult) -> None:
        self.result = result
        summary = "; ".join(str(i) for i in result.errors) or "invalid protocol"
        super().__init__(summary)
