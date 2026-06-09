from __future__ import annotations

import ssl

import pytest

from benchbot.store.db import engine_connect_args


def test_sqlite_needs_no_connect_args() -> None:
    assert engine_connect_args("sqlite+aiosqlite:///x.db") == {}


def test_postgres_enables_ssl_by_default() -> None:
    connect_args = engine_connect_args("postgresql+asyncpg://u:p@host:5432/db")
    context = connect_args["ssl"]

    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is False
    assert context.verify_mode == ssl.CERT_NONE


def test_postgres_ssl_can_verify_certificates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BENCHBOT_DB_SSL", "verify")

    connect_args = engine_connect_args("postgresql+asyncpg://u:p@host:5432/db")
    context = connect_args["ssl"]

    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_postgres_ssl_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BENCHBOT_DB_SSL", "disable")
    assert engine_connect_args("postgresql+asyncpg://u:p@host:5432/db") == {}
