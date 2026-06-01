"""The synchronous simulation runner.

Executes a protocol step-by-step against a :class:`DeckState`, emitting events
as it goes and stopping on the first dynamic failure. Static validation runs
first by default, so a run that starts is guaranteed structurally sound; what
the runner adds is *stateful* checking (volumes, tips, carryover).

The runner is intentionally synchronous in M2. Async orchestration (queuing,
cancellation, retries) arrives with the instrument layer and API.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from benchbot.domain.errors import Issue, Severity, ValidationResult
from benchbot.domain.protocol import (
    AspirateStep,
    DispenseStep,
    MixStep,
    Protocol,
    Step,
    TransferStep,
)
from benchbot.domain.validation import validate
from benchbot.engine.deck import EPSILON, DeckState, SimulationError
from benchbot.engine.events import (
    Event,
    EventLog,
    RunCompleted,
    RunFailed,
    RunStarted,
    StepCompleted,
    StepFailed,
    StepStarted,
    StepWarning,
)


class RunStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    INVALID = "invalid"  # rejected by static validation, never executed


class RunResult(BaseModel):
    """The outcome of a simulated run."""

    status: RunStatus
    events: list[Event] = []
    final_state: dict[str, float] = {}
    validation: ValidationResult | None = None
    failure: Issue | None = None

    @property
    def ok(self) -> bool:
        return self.status is RunStatus.COMPLETED


class SimulationRunner:
    """Runs protocols against an in-memory virtual deck."""

    def run(self, protocol: Protocol, *, run_validation: bool = True) -> RunResult:
        if run_validation:
            result = validate(protocol)
            if not result.ok:
                return RunResult(
                    status=RunStatus.INVALID,
                    validation=result,
                    failure=result.errors[0],
                )

        deck = DeckState.from_protocol(protocol)
        log = EventLog()
        log.emit(
            RunStarted(protocol_name=protocol.metadata.name, total_steps=len(protocol.steps))
        )

        for index, step in enumerate(protocol.steps):
            action, detail = _describe(step)
            log.emit(StepStarted(step_index=index, action=action, detail=detail))
            try:
                self._execute(step, index, deck, log)
            except SimulationError as exc:
                log.emit(StepFailed(step_index=index, code=exc.code, message=exc.message))
                log.emit(RunFailed(step_index=index, code=exc.code, message=exc.message))
                return RunResult(
                    status=RunStatus.FAILED,
                    events=log.events,
                    final_state=deck.snapshot(),
                    failure=Issue(
                        severity=Severity.ERROR,
                        code=exc.code,
                        message=exc.message,
                        step_index=index,
                    ),
                )
            log.emit(StepCompleted(step_index=index))

        log.emit(RunCompleted(steps_completed=len(protocol.steps)))
        return RunResult(
            status=RunStatus.COMPLETED,
            events=log.events,
            final_state=deck.snapshot(),
        )

    # --- Step execution -------------------------------------------------------

    def _execute(self, step: Step, index: int, deck: DeckState, log: EventLog) -> None:
        if isinstance(step, TransferStep):
            self._acquire_tip(deck, new_tip=step.new_tip)
            self._aspirate(deck, step.source, step.volume_ul, index, log)
            self._dispense(deck, step.dest, step.volume_ul)
        elif isinstance(step, AspirateStep):
            self._acquire_tip(deck, new_tip=False)
            self._aspirate(deck, step.well, step.volume_ul, index, log)
        elif isinstance(step, DispenseStep):
            self._dispense(deck, step.well, step.volume_ul)
        elif isinstance(step, MixStep):
            self._acquire_tip(deck, new_tip=False)
            for _ in range(step.repeats):
                self._aspirate(deck, step.well, step.volume_ul, index, log)
                self._dispense(deck, step.well, step.volume_ul)

    def _acquire_tip(self, deck: DeckState, *, new_tip: bool) -> None:
        pipette = deck.pipette
        if new_tip or not pipette.has_tip:
            tip_id, capacity = deck.take_tip()
            pipette.has_tip = True
            pipette.tip_id = tip_id
            pipette.tip_capacity_ul = capacity
            pipette.tip_volume_ul = 0.0
            pipette.fresh = True

    def _aspirate(
        self, deck: DeckState, ref: str, volume_ul: float, index: int, log: EventLog
    ) -> None:
        pipette = deck.pipette
        if not pipette.has_tip:
            raise SimulationError("E_NO_TIP_MOUNTED", "Aspirate attempted with no tip mounted.")
        if (
            not pipette.fresh
            and pipette.last_source is not None
            and pipette.last_source != ref
        ):
            log.emit(
                StepWarning(
                    step_index=index,
                    code="W_TIP_CARRYOVER",
                    message=(
                        f"Reusing tip across wells '{pipette.last_source}' -> '{ref}' "
                        "may carry over liquid."
                    ),
                )
            )
        if pipette.tip_volume_ul + volume_ul > pipette.tip_capacity_ul + EPSILON:
            raise SimulationError(
                "E_TIP_OVERFLOW",
                f"Aspirating {volume_ul}uL exceeds tip capacity "
                f"{pipette.tip_capacity_ul}uL (holds {pipette.tip_volume_ul}uL).",
            )
        deck.remove_liquid(ref, volume_ul)
        pipette.tip_volume_ul += volume_ul
        pipette.last_source = ref
        pipette.fresh = False

    def _dispense(self, deck: DeckState, ref: str, volume_ul: float) -> None:
        pipette = deck.pipette
        if not pipette.has_tip:
            raise SimulationError("E_NO_TIP_MOUNTED", "Dispense attempted with no tip mounted.")
        if volume_ul > pipette.tip_volume_ul + EPSILON:
            raise SimulationError(
                "E_INSUFFICIENT_TIP_VOLUME",
                f"Dispensing {volume_ul}uL but tip holds only {pipette.tip_volume_ul}uL.",
            )
        deck.add_liquid(ref, volume_ul)
        pipette.tip_volume_ul -= volume_ul


def _describe(step: Step) -> tuple[str, str]:
    """Return a ``(action, human-detail)`` pair for a step, for the event log."""
    if isinstance(step, TransferStep):
        return "transfer", f"{step.volume_ul}uL {step.source} -> {step.dest}"
    if isinstance(step, AspirateStep):
        return "aspirate", f"{step.volume_ul}uL from {step.well}"
    if isinstance(step, DispenseStep):
        return "dispense", f"{step.volume_ul}uL into {step.well}"
    if isinstance(step, MixStep):
        return "mix", f"{step.repeats}x {step.volume_ul}uL at {step.well}"
    return "unknown", ""  # pragma: no cover - exhaustive above
