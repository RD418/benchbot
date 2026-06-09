"""FastAPI application factory.

The store is created during the app's lifespan so its async engine is bound to
the same event loop that serves requests. Tables are created on startup for
zero-config dev/demo; production should run ``alembic upgrade head`` instead
(``create_all`` is idempotent and won't conflict). Tests can inject their own
:class:`RunStore` to avoid touching a real database.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from benchbot.api.routes import router
from benchbot.store.db import create_all, make_engine, make_session_factory
from benchbot.store.repository import RunStore
from benchbot.workcell.cell import build_default_workcell

#: Dev origins allowed to call the API (the Vite dashboard). Override with
#: BENCHBOT_CORS_ORIGINS (comma-separated).
_DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"


def create_app(store: RunStore | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # A fresh work cell per app instance (in-memory; holds live device health).
        app.state.workcell = build_default_workcell()
        if store is not None:
            app.state.store = store
            yield
            return
        engine = make_engine()
        await create_all(engine)
        app.state.store = RunStore(make_session_factory(engine))
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(
        title="BenchBot",
        version="0.1.0",
        summary="Simulated lab-automation protocol runner",
        lifespan=lifespan,
    )
    origins = os.environ.get("BENCHBOT_CORS_ORIGINS", _DEFAULT_ORIGINS).split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in origins if o.strip()],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app
