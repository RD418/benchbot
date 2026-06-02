"""The synchronous simulation runner.

Executes a protocol step-by-step against a :class:`DeckState`, routing every
physical action (pick up tip, aspirate, dispense, drop tip) through an
:class:`~benchbot.instruments.base.Instrument` wrapped in a
:class:`~benchbot.engine.retry.RetryPolicy`. Static validation runs first;
stateful checks (volumes, tips) run pre-flight before each command; instrument
faults drive the retry/recovery path. Everything is recorded as events.

The runner is intentionally synchronous in M2/M3. Async orchestration (queuing,
cancellation) arrives with the API.
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
    CommandAcked,
    CommandSent,
    Event,
    EventLog,
    RecoveryFailed,
    RetryScheduled,
    RunCompleted,
    RunFailed,
    RunStarted,
    StepCompleted,
    StepFailed,
    StepStarted,
    StepWarning,
)
from benchbot.engine.retry import RetryPolicy
from benchbot.instruments.base import (
    Ack,
    Command,
    Instrument,
    InstrumentError,
    RetryableError,
)
from benchbot.instruments.mock_serial import MockSerialInstrument


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
    """Runs protocols against an in-memory virtual deck via an instrument."""

    def __init__(
        self,
        instrument: Instrument | None = None,
        retry: RetryPolicy | None = None,
    ) -> None:
        self.instrument: Instrument = instrument or MockSerialInstrument()
        self.retry = retry or RetryPolicy()

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
            self._acquire_tip(deck, log, index, new_tip=step.new_tip)
            self._aspirate(deck, step.source, step.volume_ul, index, log)
            self._dispense(deck, step.dest, step.volume_ul, index, log)
        elif isinstance(step, AspirateStep):
            self._acquire_tip(deck, log, index, new_tip=False)
            self._aspirate(deck, step.well, step.volume_ul, index, log)
        elif isinstance(step, DispenseStep):
            self._dispense(deck, step.well, step.volume_ul, index, log)
        elif isinstance(step, MixStep):
            self._acquire_tip(deck, log, index, new_tip=False)
            for _ in range(step.repeats):
                self._aspirate(deck, step.well, step.volume_ul, index, log)
                self._dispense(deck, step.well, step.volume_ul, index, log)

    def _acquire_tip(
        self, deck: DeckState, log: EventLog, index: int, *, new_tip: bool
    ) -> None:
        pipette = deck.pipette
        if not new_tip and pipette.has_tip:
            return
        if pipette.has_tip:
            self._send(index, Command(name="DROP_TIP", params={"tip": pipette.tip_id or ""}), log)
            pipette.has_tip = False
        if deck.tips_remaining == 0:
            raise SimulationError("E_NO_TIP_AVAILABLE", "No tips remaining on the deck.")
        tip_id, capacity = deck.take_tip()
        self._send(index, Command(name="PICK_UP_TIP", params={"tip": tip_id}), log)
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
        # Pre-flight state checks happen before any command reaches the instrument.
        if pipette.tip_volume_ul + volume_ul > pipette.tip_capacity_ul + EPSILON:
            raise SimulationError(
                "E_TIP_OVERFLOW",
                f"Aspirating {volume_ul}uL exceeds tip capacity "
                f"{pipette.tip_capacity_ul}uL (holds {pipette.tip_volume_ul}uL).",
            )
        if volume_ul > deck.volume(ref) + EPSILON:
            raise SimulationError(
                "E_INSUFFICIENT_VOLUME",
                f"Cannot aspirate {volume_ul}uL from '{ref}' holding {deck.volume(ref)}uL.",
            )
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
        self._send(index, Command(name="ASPIRATE", params={"vol": volume_ul, "well": ref}), log)
        deck.remove_liquid(ref, volume_ul)
        pipette.tip_volume_ul += volume_ul
        pipette.last_source = ref
        pipette.fresh = False

    def _dispense(
        self, deck: DeckState, ref: str, volume_ul: float, index: int, log: EventLog
    ) -> None:
        pipette = deck.pipette
        if not pipette.has_tip:
            raise SimulationError("E_NO_TIP_MOUNTED", "Dispense attempted with no tip mounted.")
        if volume_ul > pipette.tip_volume_ul + EPSILON:
            raise SimulationError(
                "E_INSUFFICIENT_TIP_VOLUME",
                f"Dispensing {volume_ul}uL but tip holds only {pipette.tip_volume_ul}uL.",
            )
        if deck.volume(ref) + volume_ul > deck.capacity(ref) + EPSILON:
            raise SimulationError(
                "E_OVERFILL",
                f"Dispensing {volume_ul}uL into '{ref}' "
                f"(holds {deck.volume(ref)}uL) exceeds capacity {deck.capacity(ref)}uL.",
            )
        self._send(index, Command(name="DISPENSE", params={"vol": volume_ul, "well": ref}), log)
        deck.add_liquid(ref, volume_ul)
        pipette.tip_volume_ul -= volume_ul

    # --- Instrument I/O with retry/recovery -----------------------------------

    def _send(self, step_index: int, command: Command, log: EventLog) -> Ack:
        attempt_no = 0

        def attempt() -> Ack:
            nonlocal attempt_no
            attempt_no += 1
            log.emit(
                CommandSent(step_index=step_index, command=command.frame(), attempt=attempt_no)
            )
            ack = self.instrument.send(command)
            log.emit(
                CommandAcked(step_index=step_index, command=command.frame(), attempt=attempt_no)
            )
            return ack

        def on_retry(attempt_number: int, error: RetryableError) -> None:
            log.emit(
                RetryScheduled(
                    step_index=step_index,
                    command=command.frame(),
                    attempt=attempt_number,
                    code=error.code,
                    message=str(error),
                )
            )

        try:
            return self.retry.run(attempt, on_retry)
        except InstrumentError as exc:
            log.emit(
                RecoveryFailed(
                    step_index=step_index,
                    command=command.frame(),
                    code=exc.code,
                    message=str(exc),
                )
            )
            raise SimulationError(exc.code, str(exc)) from exc


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
