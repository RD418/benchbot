"""Async engine / session plumbing and database URL configuration.

The URL is read from ``BENCHBOT_DATABASE_URL`` (default: a local SQLite file).
Because the URL is the only coupling to SQLite, swapping in Postgres is a
one-line environment change — e.g. on Supabase:
``postgresql+asyncpg://user:pass@host:5432/postgres``. Schema in production is
managed by Alembic; tests and quick dev use :func:`create_all`.

Managed Postgres (Supabase, Neon, …) requires TLS. For ``postgresql+asyncpg``
URLs we require TLS by default without certificate verification, matching
``sslmode=require`` behavior; set ``BENCHBOT_DB_SSL=verify`` to require a valid
CA chain, or ``BENCHBOT_DB_SSL=disable`` for a local Postgres without TLS.
"""

from __future__ import annotations

import os
import ssl
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
    if url.startswith("postgresql+asyncpg"):
        ssl_mode = os.environ.get("BENCHBOT_DB_SSL", "require")
        if ssl_mode == "disable":
            return {}
        if ssl_mode == "verify":
            return {"ssl": ssl.create_default_context()}

        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return {"ssl": context}
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
