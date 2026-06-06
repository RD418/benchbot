"""Per-failure-mode recovery policy.

When a task fails *after* the device has exhausted its own command-level retries,
the work cell must decide what to do with the **task**. That decision is separate
from (and sits above) the instrument retry policy:

* ``RETRY`` — re-run the whole task once more (then fall back to ``SKIP``).
* ``SKIP``  — quarantine the device and skip dependent tasks, but keep running
  everything independent (graceful degradation; the default).
* ``HALT``  — stop the whole workflow.

The disposition is chosen per failure code, so different faults can be handled
differently (e.g. retry a flaky comms timeout, but halt on a safety fault).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from benchbot.domain.errors import Issue


class Disposition(StrEnum):
    RETRY = "retry"
    SKIP = "skip"
    HALT = "halt"


class RecoveryPolicy(BaseModel):
    """Maps a failure to a disposition, with per-code overrides."""

    default: Disposition = Disposition.SKIP
    overrides: dict[str, Disposition] = {}

    def decide(self, issue: Issue) -> Disposition:
        return self.overrides.get(issue.code, self.default)
