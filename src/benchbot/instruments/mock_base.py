"""Shared behavior for mock instruments.

Real instruments speak different wire protocols (serial framing, TCP/JSON, …)
but share the same *semantics*: send a command, get an ACK, or fail with a
NAK / timeout / hardware fault. This base captures that shared semantics and
the seeded fault injection, leaving only the wire framing to each subclass
(:meth:`_frame`). It's the concrete embodiment of the ``Instrument`` seam:
one abstraction, many transports.
"""

from __future__ import annotations

from benchbot.instruments.base import (
    Ack,
    Command,
    HardwareError,
    InstrumentTimeout,
    NakError,
)
from benchbot.instruments.faults import FaultPolicy, NoFaults, Outcome


class BaseMockInstrument:
    """A simulated instrument: records frames, injects faults, returns ACKs."""

    def __init__(self, faults: FaultPolicy | None = None) -> None:
        self.faults: FaultPolicy = faults or NoFaults()
        #: Every request frame transmitted, in order (for diagnostics).
        self.sent: list[str] = []

    def _frame(self, command: Command) -> str:
        """Render a command into this transport's wire format."""
        raise NotImplementedError

    def send(self, command: Command) -> Ack:
        self.sent.append(self._frame(command))
        outcome = self.faults.decide()
        if outcome is Outcome.OK:
            return Ack(code="ACK", message=command.name)
        if outcome is Outcome.TRANSIENT:
            raise NakError(f"NAK returned for {command.name}")
        if outcome is Outcome.TIMEOUT:
            raise InstrumentTimeout(f"No response (timeout) for {command.name}")
        raise HardwareError(f"Hardware fault during {command.name}")
