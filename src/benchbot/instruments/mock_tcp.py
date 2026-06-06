"""A software instrument that simulates a TCP/JSON device (e.g. a plate reader).

Same :class:`~benchbot.instruments.base.Instrument` interface and the same
``Command``/``Ack`` model as the serial mock, but a different wire format:
newline-delimited JSON. This is the point of the abstraction — the orchestrator
sends transport-agnostic ``Command``s and each driver handles its own framing.
"""

from __future__ import annotations

import json

from benchbot.instruments.base import Command
from benchbot.instruments.mock_base import BaseMockInstrument


class MockTcpInstrument(BaseMockInstrument):
    """Simulated TCP/JSON instrument with injectable faults."""

    def _frame(self, command: Command) -> str:
        return json.dumps({"cmd": command.name, "args": command.params}, sort_keys=True)
