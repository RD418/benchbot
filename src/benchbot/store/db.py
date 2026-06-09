"""Async engine / session plumbing and database URL configuration.

The URL is read from ``BENCHBOT_DATABASE_URL`` (default: a local SQLite file).
Because the URL is the only coupling to SQLite, swapping in Postgres is a
one-line environment change — e.g. on Supabase:
``postgresql+asyncpg://user:pass@host:5432/postgres``. Schema in production is
managed by Alembic; tests and quick dev use :func:`create_all`.

Managed Postgres (Supabase, Neon, …) requires TLS. For ``postgresql+asyncpg``
URLs we enable it by default via asyncpg's ``ssl`` connect arg; set
``BENCHBOT_DB_SSL=disable`` for a local Postgres without TLS.
"""

from __future__ import annotations

import os
from typing import Any

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


def engine_connect_args(url: str) -> dict[str, Any]:
    """Driver connect args for a URL — notably TLS for managed Postgres."""
    if url.startswith("postgresql+asyncpg") and os.environ.get("BENCHBOT_DB_SSL") != "disable":
        return {"ssl": True}
    return {}


def make_engine(url: str | None = None) -> AsyncEngine:
    """Create an async engine for the configured (or given) database URL."""
    resolved = url or get_database_url()
    return create_async_engine(resolved, connect_args=engine_connect_args(resolved))


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
