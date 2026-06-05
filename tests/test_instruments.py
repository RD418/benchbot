from __future__ import annotations

import pytest

from benchbot.instruments.base import (
    Command,
    HardwareError,
    InstrumentTimeout,
    NakError,
)
from benchbot.instruments.faults import (
    NoFaults,
    Outcome,
    RandomFaults,
    ScriptedFaults,
)
from benchbot.instruments.mock_serial import MockSerialInstrument


def test_command_frame_format() -> None:
    cmd = Command(name="ASPIRATE", params={"vol": 100, "well": "p:A1"})
    assert cmd.frame() == ">ASPIRATE vol=100 well=p:A1"
    assert Command(name="HOME").frame() == ">HOME"


def test_no_faults_always_acks() -> None:
    inst = MockSerialInstrument(NoFaults())
    ack = inst.send(Command(name="PICK_UP_TIP"))
    assert ack.ok and ack.code == "ACK"
    assert inst.sent == [">PICK_UP_TIP"]


def test_scripted_faults_map_to_exceptions() -> None:
    inst = MockSerialInstrument(ScriptedFaults([Outcome.TRANSIENT, Outcome.TIMEOUT, Outcome.HARD]))
    with pytest.raises(NakError):
        inst.send(Command(name="A"))
    with pytest.raises(InstrumentTimeout):
        inst.send(Command(name="B"))
    with pytest.raises(HardwareError):
        inst.send(Command(name="C"))
    # Exhausted -> succeeds.
    assert inst.send(Command(name="D")).ok
    # Every attempt was recorded, including the failed ones.
    assert inst.sent == [">A", ">B", ">C", ">D"]


def test_random_faults_are_deterministic_for_a_seed() -> None:
    a = RandomFaults(seed=42, transient_rate=0.3, hard_rate=0.1)
    b = RandomFaults(seed=42, transient_rate=0.3, hard_rate=0.1)
    seq_a = [a.decide() for _ in range(50)]
    seq_b = [b.decide() for _ in range(50)]
    assert seq_a == seq_b
    # Different seed should (with overwhelming probability) differ.
    c = RandomFaults(seed=99, transient_rate=0.3, hard_rate=0.1)
    assert [c.decide() for _ in range(50)] != seq_a


def test_random_faults_reject_impossible_rates() -> None:
    with pytest.raises(ValueError):
        RandomFaults(transient_rate=0.7, timeout_rate=0.7)


def test_random_faults_can_force_each_outcome() -> None:
    assert RandomFaults(hard_rate=1.0).decide() is Outcome.HARD
    assert RandomFaults(timeout_rate=1.0).decide() is Outcome.TIMEOUT
    assert RandomFaults(transient_rate=1.0).decide() is Outcome.TRANSIENT
    assert RandomFaults().decide() is Outcome.OK
