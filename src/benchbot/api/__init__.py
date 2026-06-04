"""BenchBot HTTP API (FastAPI), a thin adapter over the engine and store."""

from __future__ import annotations

from benchbot.api.app import create_app

__all__ = ["create_app"]
