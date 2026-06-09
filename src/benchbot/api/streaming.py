"""Server-Sent Events (SSE) stream of a work-cell run, for the live dashboard.

The simulation completes near-instantly, so "live" streaming means pacing the
recorded event stream out to the browser one message at a time (a small delay
between events) so the dashboard can animate task progress, retries, and device
quarantine as they happen. Each demo run uses a *fresh* work cell so it is
independent and repeatable.

Wire format (one JSON object per SSE ``data:`` line):

* ``{"kind": "event", "event": {...}}``  — one workflow event
* ``{"kind": "done",  "result": {...}}`` — the final WorkflowResult
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from benchbot.instruments.faults import RandomFaults
from benchbot.workcell.cell import build_default_workcell, build_demo_workflow
from benchbot.workcell.recovery import Disposition, RecoveryPolicy


async def stream_demo(
    *, seed: int, hard_rate: float, halt: bool, delay: float
) -> AsyncIterator[str]:
    """Run the demo workflow and yield its events as SSE messages."""
    cell = build_default_workcell()
    if hard_rate > 0:
        cell.devices["inc1"].set_faults(RandomFaults(seed=seed, hard_rate=hard_rate))
    recovery = RecoveryPolicy(default=Disposition.HALT) if halt else None

    result = cell.run_workflow(build_demo_workflow(), recovery)

    for event in result.events:
        yield _sse({"kind": "event", "event": json.loads(event.model_dump_json())})
        if delay > 0:
            await asyncio.sleep(delay)

    yield _sse({"kind": "done", "result": json.loads(result.model_dump_json())})


def _sse(obj: dict[str, object]) -> str:
    return f"data: {json.dumps(obj)}\n\n"
