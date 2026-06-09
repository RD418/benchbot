from __future__ import annotations

import pytest

from benchbot.store.db import engine_connect_args


def test_sqlite_needs_no_connect_args() -> None:
    assert engine_connect_args("sqlite+aiosqlite:///x.db") == {}


def test_postgres_enables_ssl_by_default() -> None:
    assert engine_connect_args("postgresql+asyncpg://u:p@host:5432/db") == {"ssl": True}


def test_postgres_ssl_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BENCHBOT_DB_SSL", "disable")
    assert engine_connect_args("postgresql+asyncpg://u:p@host:5432/db") == {}
