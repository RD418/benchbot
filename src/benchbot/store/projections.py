"""Read-model projections derived from the event stream.

This is the event-sourcing payoff: a run's status is a *function* of its
events, not an independently-mutated field. The ``runs.status`` column is just a
cached copy of :func:`project_status`, and tests assert the two agree.
"""

from __future__ import annotations

from benchbot.engine.events import Event, RunCompleted, RunFailed
from benchbot.engine.runner import RunStatus


def project_status(events: list[Event]) -> RunStatus:
    """Derive a run's terminal status from its events.

    A run with no events was rejected by static validation before execution
    (``INVALID``); otherwise the terminal ``run_completed`` / ``run_failed``
    event decides.
    """
    for event in events:
        if isinstance(event, RunCompleted):
            return RunStatus.COMPLETED
        if isinstance(event, RunFailed):
            return RunStatus.FAILED
    return RunStatus.INVALID
