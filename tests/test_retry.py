from __future__ import annotations

import pytest

from benchbot.engine.retry import RetryPolicy
from benchbot.instruments.base import HardwareError, NakError, RetryableError


def test_max_attempts_must_be_positive() -> None:
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)


def test_succeeds_on_first_attempt() -> None:
    retries: list[int] = []
    result = RetryPolicy().run(lambda: 7, lambda n, e: retries.append(n))
    assert result == 7
    assert retries == []


def test_retries_then_succeeds() -> None:
    calls = {"n": 0}
    retries: list[int] = []

    def op() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise NakError("flaky")
        return "ok"

    result = RetryPolicy(max_attempts=3).run(op, lambda n, e: retries.append(n))
    assert result == "ok"
    assert calls["n"] == 3
    assert retries == [1, 2]  # two re-attempts scheduled


def test_exhausts_attempts_and_reraises() -> None:
    retries: list[int] = []

    def op() -> str:
        raise NakError("always")

    with pytest.raises(NakError):
        RetryPolicy(max_attempts=2).run(op, lambda n, e: retries.append(n))
    assert retries == [1]  # only one retry between two attempts


def test_hardware_error_is_not_retried() -> None:
    retries: list[int] = []

    def op() -> str:
        raise HardwareError("fatal")

    with pytest.raises(HardwareError):
        RetryPolicy(max_attempts=5).run(op, lambda n, e: retries.append(n))
    assert retries == []


def test_on_retry_receives_the_error() -> None:
    seen: list[RetryableError] = []
    calls = {"n": 0}

    def op() -> int:
        calls["n"] += 1
        if calls["n"] == 1:
            raise NakError("first")
        return 1

    RetryPolicy().run(op, lambda n, e: seen.append(e))
    assert len(seen) == 1 and isinstance(seen[0], NakError)
