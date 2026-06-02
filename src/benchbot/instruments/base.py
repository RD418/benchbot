"""Instrument interface, command/ack framing, and error taxonomy.

BenchBot talks to "hardware" through a narrow :class:`Instrument` interface that
exchanges serial-style frames. The real implementation in M3 is a software
mock, but the seam is exactly where a real serial/USB driver would slot in.

Errors are split by *recoverability*: :class:`RetryableError` (a transient NAK
or timeout the retry policy will re-attempt) versus :class:`HardwareError` (a
fatal fault that aborts the run immediately). Each carries a stable ``code``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from benchbot.domain.errors import BenchBotError

#: Values allowed in a command's parameter map.
ParamValue = str | int | float | bool


class Command(BaseModel):
    """A single instruction sent to an instrument."""

    name: str
    params: dict[str, ParamValue] = {}

    def frame(self) -> str:
        """Render the serial-style request frame, e.g. ``>ASPIRATE vol=100 well=p:A1``."""
        body = " ".join(f"{k}={v}" for k, v in self.params.items())
        return f">{self.name} {body}".rstrip()


class Ack(BaseModel):
    """A successful acknowledgement frame from an instrument."""

    ok: bool = True
    code: str = "ACK"
    message: str = ""


@runtime_checkable
class Instrument(Protocol):
    """Anything that can accept a :class:`Command` and acknowledge it."""

    def send(self, command: Command) -> Ack: ...


# --- Error taxonomy ------------------------------------------------------------


class InstrumentError(BenchBotError):
    """Base class for instrument communication errors."""

    code: str = "E_INSTRUMENT_ERROR"


class RetryableError(InstrumentError):
    """A transient failure that the retry policy may re-attempt."""

    code: str = "E_INSTRUMENT_RETRYABLE"


class NakError(RetryableError):
    """The instrument returned a negative acknowledgement (NAK)."""

    code: str = "E_INSTRUMENT_NAK"


class InstrumentTimeout(RetryableError):
    """The instrument did not respond within the expected window."""

    code: str = "E_INSTRUMENT_TIMEOUT"


class HardwareError(InstrumentError):
    """A fatal hardware fault; not safe to retry blindly."""

    code: str = "E_HARDWARE_FAILURE"
