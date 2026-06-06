from __future__ import annotations

import json

import pytest

from benchbot.instruments.base import Command, HardwareError, NakError
from benchbot.instruments.faults import NoFaults, Outcome, ScriptedFaults
from benchbot.instruments.mock_tcp import MockTcpInstrument


def test_tcp_frames_as_json() -> None:
    inst = MockTcpInstrument(NoFaults())
    inst.send(Command(name="READ_PLATE", params={"plate": "p", "nm": 600}))
    assert json.loads(inst.sent[0]) == {"cmd": "READ_PLATE", "args": {"plate": "p", "nm": 600}}


def test_tcp_shares_fault_semantics() -> None:
    inst = MockTcpInstrument(ScriptedFaults([Outcome.TRANSIENT, Outcome.HARD]))
    with pytest.raises(NakError):
        inst.send(Command(name="A"))
    with pytest.raises(HardwareError):
        inst.send(Command(name="B"))
    assert inst.send(Command(name="C")).ok  # exhausted -> OK
