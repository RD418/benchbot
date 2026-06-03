"""SQLAlchemy 2.0 ORM models for the event-sourced run log.

Two tables: ``runs`` holds per-run metadata plus a *projection* of the run's
status (a denormalized read model), while ``events`` is the append-only source
of truth — one row per emitted event, full payload stored as JSON. Run status
can always be re-derived from the event stream (see
:mod:`benchbot.store.projections`); the column is just a fast read model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    """Declarative base carrying the shared metadata for migrations."""


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    protocol_name: Mapped[str] = mapped_column(String(200))
    total_steps: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))  # projection of the event stream
    failure_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    events: Mapped[list[EventRow]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="EventRow.seq",
    )


class EventRow(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_event_run_seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(40), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)

    run: Mapped[RunRow] = relationship(back_populates="events")
