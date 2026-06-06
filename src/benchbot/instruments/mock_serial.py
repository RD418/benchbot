"""A software instrument that simulates a serial-style liquid handler.

Wire format: framed serial lines like ``>ASPIRATE vol=100 well=p:A1``. All the
fault/ACK behavior lives in :class:`BaseMockInstrument`; this subclass only
supplies the serial framing.
"""

from __future__ import annotations

from benchbot.instruments.base import Command
from benchbot.instruments.mock_base import BaseMockInstrument


class MockSerialInstrument(BaseMockInstrument):
    """Simulated serial instrument with injectable faults."""

    def _frame(self, command: Command) -> str:
        return command.frame()
