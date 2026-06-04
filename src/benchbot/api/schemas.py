"""Request/response models for the HTTP API.

These reuse the domain/engine/store models wherever possible so the API stays a
thin adapter — the protocol body *is* the domain :class:`Protocol`, issues are
domain :class:`Issue`s, and so on.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from benchbot.domain.errors import Issue
from benchbot.domain.protocol import Protocol
from benchbot.engine.runner import RunStatus


class FaultConfig(BaseModel):
    """Deterministic fault-injection settings for a run."""

    seed: int = 0
    transient_rate: float = 0.0
    timeout_rate: float = 0.0
    hard_rate: float = 0.0


class RetryConfig(BaseModel):
    max_attempts: int = Field(default=3, ge=1)


class RunRequest(BaseModel):
    """Submit a protocol for execution, optionally with faults/retry tuning."""

    protocol: Protocol
    faults: FaultConfig | None = None
    retry: RetryConfig | None = None
    run_validation: bool = True


class RunSummary(BaseModel):
    """Returned when a run is submitted."""

    id: str
    status: RunStatus
    total_steps: int
    steps_completed: int
    failure: Issue | None = None


class Diagnostics(BaseModel):
    """Failure-focused view of a run, computed from its event stream."""

    id: str
    status: RunStatus
    failure: Issue | None = None
    command_count: int
    retry_count: int
    recovery_failures: int
    warnings: list[Issue] = []
