from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio

from benchbot.store import (
    RunStore,
    WorkflowStore,
    create_all,
    make_memory_engine,
    make_session_factory,
)


@pytest_asyncio.fixture
async def store() -> AsyncIterator[RunStore]:
    """A RunStore backed by a fresh in-memory SQLite database per test."""
    engine = make_memory_engine()
    await create_all(engine)
    try:
        yield RunStore(make_session_factory(engine))
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def workflow_store() -> AsyncIterator[WorkflowStore]:
    """A WorkflowStore backed by a fresh in-memory SQLite database per test."""
    engine = make_memory_engine()
    await create_all(engine)
    try:
        yield WorkflowStore(make_session_factory(engine))
    finally:
        await engine.dispose()
