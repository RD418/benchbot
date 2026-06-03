"""Async engine / session plumbing and database URL configuration.

The URL is read from ``BENCHBOT_DATABASE_URL`` (default: a local SQLite file).
Because the URL is the only coupling to SQLite, swapping in Postgres later is a
one-line environment change. Schema in production is managed by Alembic; tests
and quick dev use :func:`create_all`.
"""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from benchbot.store.models import Base

DEFAULT_URL = "sqlite+aiosqlite:///benchbot.db"


def get_database_url() -> str:
    return os.environ.get("BENCHBOT_DATABASE_URL", DEFAULT_URL)


def make_engine(url: str | None = None) -> AsyncEngine:
    """Create an async engine for the configured (or given) database URL."""
    return create_async_engine(url or get_database_url())


def make_memory_engine() -> AsyncEngine:
    """Create a shared in-memory SQLite engine (for tests).

    ``StaticPool`` keeps a single connection alive so the in-memory database
    persists across sessions within one engine.
    """
    return create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_all(engine: AsyncEngine) -> None:
    """Create all tables from the ORM metadata (dev/test convenience)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
