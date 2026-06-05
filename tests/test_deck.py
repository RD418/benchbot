from __future__ import annotations

import pytest

from benchbot.domain.protocol import ProtocolBuilder
from benchbot.engine.deck import DeckState, SimulationError


def _deck() -> DeckState:
    protocol = (
        ProtocolBuilder("deck")
        .add_plate("p", "plate_96_wellplate_200ul", slot=1)
        .add_tiprack("t", "tiprack_300ul", slot=2)
        .fill("p:A1", 150)
        .build()
    )
    return DeckState.from_protocol(protocol)


def test_initial_volume_and_capacity() -> None:
    deck = _deck()
    assert deck.volume("p:A1") == 150
    assert deck.volume("p:A2") == 0
    assert deck.capacity("p:A1") == 200


def test_remove_then_add_liquid() -> None:
    deck = _deck()
    deck.remove_liquid("p:A1", 50)
    assert deck.volume("p:A1") == 100
    deck.add_liquid("p:A2", 50)
    assert deck.volume("p:A2") == 50


def test_insufficient_volume_raises() -> None:
    deck = _deck()
    with pytest.raises(SimulationError) as exc:
        deck.remove_liquid("p:A1", 999)
    assert exc.value.code == "E_INSUFFICIENT_VOLUME"


def test_overfill_raises() -> None:
    deck = _deck()
    with pytest.raises(SimulationError) as exc:
        deck.add_liquid("p:A1", 999)  # already holds 150, capacity 200
    assert exc.value.code == "E_OVERFILL"


def test_tip_inventory_depletes() -> None:
    deck = _deck()
    assert deck.tips_remaining == 96
    tip_id, capacity = deck.take_tip()
    assert tip_id == "t:A1"
    assert capacity == 300
    assert deck.tips_remaining == 95


def test_running_out_of_tips_raises() -> None:
    protocol = ProtocolBuilder("tiny").add_tiprack("t", "tiprack_300ul", slot=1).build()
    deck = DeckState.from_protocol(protocol)
    for _ in range(96):
        deck.take_tip()
    with pytest.raises(SimulationError) as exc:
        deck.take_tip()
    assert exc.value.code == "E_NO_TIP_AVAILABLE"


def test_snapshot_hides_empty_wells() -> None:
    deck = _deck()
    deck.remove_liquid("p:A1", 150)
    deck.add_liquid("p:B2", 25)
    assert deck.snapshot() == {"p:B2": 25.0}
