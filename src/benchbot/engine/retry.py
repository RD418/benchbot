"""A small, dependency-free retry policy with exponential backoff.

It retries only :class:`~benchbot.instruments.base.RetryableError` (NAKs and
timeouts); a :class:`~benchbot.instruments.base.HardwareError` propagates
immediately. The policy is pure — it emits nothing itself. Callers pass an
``on_retry`` callback so the runner can record ``RetryScheduled`` events
without coupling this module to the event log.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

from benchbot.instruments.base import RetryableError

T = TypeVar("T")

#: Callback invoked before each re-attempt: ``(attempt_number, error)``.
OnRetry = Callable[[int, RetryableError], None]


class RetryPolicy:
    """Re-attempts an operation on retryable errors with exponential backoff."""

    def __init__(self, *, max_attempts: int = 3, backoff_base_s: float = 0.0) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.max_attempts = max_attempts
        self.backoff_base_s = backoff_base_s

    def run(self, operation: Callable[[], T], on_retry: OnRetry) -> T:
        """Call ``operation`` until it succeeds or attempts/recoverability run out."""
        last_error: RetryableError | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return operation()
            except RetryableError as exc:
                last_error = exc
                if attempt >= self.max_attempts:
                    raise
                on_retry(attempt, exc)
                self._sleep(attempt)
        # Unreachable: the loop either returns or raises.
        raise last_error  # type: ignore[misc]  # pragma: no cover

    def _sleep(self, attempt: int) -> None:
        if self.backoff_base_s > 0:
            time.sleep(self.backoff_base_s * (2 ** (attempt - 1)))
