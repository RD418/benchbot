"""Fault injection policies for the mock instrument.

The headline feature: failures are **deterministic**. :class:`RandomFaults`
draws every outcome from a seeded RNG, so a given ``(seed, command sequence)``
always produces the same run — which makes retry and recovery behavior
reproducible and unit-testable. :class:`ScriptedFaults` gives tests exact
control, and :class:`NoFaults` is the perfect-hardware default.
"""

from __future__ import annotations

import random
from enum import StrEnum
from typing import Protocol


class Outcome(StrEnum):
    OK = "ok"
    TRANSIENT = "transient"  # -> retryable NAK
    TIMEOUT = "timeout"  # -> retryable timeout
    HARD = "hard"  # -> fatal hardware fault


class FaultPolicy(Protocol):
    """Decides the outcome of the next command attempt."""

    def decide(self) -> Outcome: ...


class NoFaults:
    """Every command succeeds (perfect hardware)."""

    def decide(self) -> Outcome:
        return Outcome.OK


class RandomFaults:
    """Seeded, probabilistic faults.

    Rates are independent probabilities checked in priority order
    (hard, timeout, transient); the remainder succeeds. The RNG advances once
    per attempt, so retries can succeed even when the rates are high.
    """

    def __init__(
        self,
        *,
        seed: int = 0,
        transient_rate: float = 0.0,
        timeout_rate: float = 0.0,
        hard_rate: float = 0.0,
    ) -> None:
        total = transient_rate + timeout_rate + hard_rate
        if not (0.0 <= total <= 1.0):
            raise ValueError("fault rates must sum to a value in [0, 1]")
        self._rng = random.Random(seed)
        self._hard = hard_rate
        self._timeout = timeout_rate
        self._transient = transient_rate

    def decide(self) -> Outcome:
        x = self._rng.random()
        if x < self._hard:
            return Outcome.HARD
        if x < self._hard + self._timeout:
            return Outcome.TIMEOUT
        if x < self._hard + self._timeout + self._transient:
            return Outcome.TRANSIENT
        return Outcome.OK


class ScriptedFaults:
    """Replays a fixed list of outcomes, then succeeds (``OK``) forever.

    Useful for deterministic tests of specific retry/recovery paths.
    """

    def __init__(self, outcomes: list[Outcome]) -> None:
        self._queue = list(outcomes)
        self._i = 0

    def decide(self) -> Outcome:
        if self._i < len(self._queue):
            outcome = self._queue[self._i]
            self._i += 1
            return outcome
        return Outcome.OK
