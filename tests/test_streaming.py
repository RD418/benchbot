from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from benchbot.api.app import create_app


@pytest.fixture
def client(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    db = tmp_path / "test.db"
    monkeypatch.setenv("BENCHBOT_DATABASE_URL", f"sqlite+aiosqlite:///{db}")
    with TestClient(create_app()) as c:
        yield c


def _parse_sse(body: str) -> list[dict[str, Any]]:
    return [
        json.loads(line[len("data:") :].strip())
        for line in body.splitlines()
        if line.startswith("data:")
    ]


def test_stream_healthy_run(client: TestClient) -> None:
    body = client.get("/stream/demo", params={"delay": 0}).text
    messages = _parse_sse(body)
    kinds = [m["kind"] for m in messages]
    assert kinds[0] == "event"
    assert kinds[-1] == "done"  # terminal message
    assert messages[-1]["result"]["status"] == "completed"


def test_stream_degraded_run_emits_quarantine(client: TestClient) -> None:
    body = client.get("/stream/demo", params={"delay": 0, "hard_rate": 1.0, "seed": 1}).text
    messages = _parse_sse(body)
    event_types = [m["event"]["type"] for m in messages if m["kind"] == "event"]
    assert "device_quarantined" in event_types
    assert "task_skipped" in event_types
    assert messages[-1]["result"]["status"] == "degraded"


def test_stream_content_type_is_event_stream(client: TestClient) -> None:
    with client.stream("GET", "/stream/demo", params={"delay": 0}) as response:
        assert response.headers["content-type"].startswith("text/event-stream")
