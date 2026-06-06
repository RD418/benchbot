"""BenchBot instruments layer: the hardware seam and its mock implementation."""

from __future__ import annotations

from benchbot.instruments.base import (
    Ack,
    Command,
    HardwareError,
    Instrument,
    InstrumentError,
    InstrumentTimeout,
    NakError,
    RetryableError,
)
from benchbot.instruments.faults import (
    FaultPolicy,
    NoFaults,
    Outcome,
    RandomFaults,
    ScriptedFaults,
)
from benchbot.instruments.mock_base import BaseMockInstrument
from benchbot.instruments.mock_serial import MockSerialInstrument
from benchbot.instruments.mock_tcp import MockTcpInstrument

__all__ = [
    "Ack",
    "BaseMockInstrument",
    "Command",
    "FaultPolicy",
    "HardwareError",
    "Instrument",
    "InstrumentError",
    "InstrumentTimeout",
    "MockSerialInstrument",
    "MockTcpInstrument",
    "NakError",
    "NoFaults",
    "Outcome",
    "RandomFaults",
    "RetryableError",
    "ScriptedFaults",
]
