"""Devices: a named instrument in the work cell, with health and counters.

A :class:`Device` wraps an :class:`~benchbot.instruments.base.Instrument` (the
driver) with the bookkeeping the orchestrator needs: what kind of instrument it
is, its current health, and rolling command/error/retry counts that feed the
observability endpoint. Health is the lever for *graceful degradation* — a
quarantined (``DOWN``) device is skipped rather than allowed to fail the cell.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from benchbot.engine.retry import RetryPolicy
from benchbot.instruments.base import Instrument
from benchbot.instruments.faults import FaultPolicy
from benchbot.instruments.mock_base import BaseMockInstrument


class DeviceKind(StrEnum):
    LIQUID_HANDLER = "liquid_handler"
    PLATE_READER = "plate_reader"
    INCUBATOR = "incubator"


class DeviceHealth(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"  # completed work but saw recoverable errors
    DOWN = "down"  # quarantined after an unrecoverable failure


@dataclass
class Device:
    """A single instrument in the work cell."""

    name: str
    kind: DeviceKind
    instrument: Instrument
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    quarantined: bool = False
    commands: int = 0
    errors: int = 0
    retries: int = 0

    def set_faults(self, policy: FaultPolicy) -> None:
        """Swap the fault policy if the underlying instrument supports it (mocks)."""
        if isinstance(self.instrument, BaseMockInstrument):
            self.instrument.faults = policy

    @property
    def health(self) -> DeviceHealth:
        """Derive health: DOWN if quarantined, DEGRADED if it saw errors, else OK."""
        if self.quarantined:
            return DeviceHealth.DOWN
        if self.errors > 0:
            return DeviceHealth.DEGRADED
        return DeviceHealth.OK

    @property
    def error_rate(self) -> float:
        return self.errors / self.commands if self.commands else 0.0
