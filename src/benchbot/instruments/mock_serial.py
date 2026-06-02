"""A software instrument that simulates a serial-style liquid handler.

It does not model liquid (the :class:`~benchbot.engine.deck.DeckState` owns
that); its job is to simulate the *communication channel* — framing commands,
returning ACKs, and raising NAK/timeout/hardware faults according to its
:class:`~benchbot.instruments.faults.FaultPolicy`. Every frame it sends is
recorded for diagnostics.
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


class MockSerialInstrument:
    """Simulated serial instrument with injectable faults."""

    def __init__(self, faults: FaultPolicy | None = None) -> None:
        self.faults: FaultPolicy = faults or NoFaults()
        #: Every request frame transmitted, in order (for diagnostics).
        self.sent: list[str] = []

    def send(self, command: Command) -> Ack:
        self.sent.append(command.frame())
        outcome = self.faults.decide()
        if outcome is Outcome.OK:
            return Ack(code="ACK", message=command.name)
        if outcome is Outcome.TRANSIENT:
            raise NakError(f"NAK returned for {command.name}")
        if outcome is Outcome.TIMEOUT:
            raise InstrumentTimeout(f"No response (timeout) for {command.name}")
        raise HardwareError(f"Hardware fault during {command.name}")
