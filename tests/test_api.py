from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from benchbot.api.app import create_app
from benchbot.domain.protocol import Protocol, ProtocolBuilder


@pytest.fixture
def client(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    db = tmp_path / "test.db"
    monkeypatch.setenv("BENCHBOT_DATABASE_URL", f"sqlite+aiosqlite:///{db}")
    with TestClient(create_app()) as c:
        yield c


def _valid() -> dict[str, Any]:
    protocol: Protocol = (
        ProtocolBuilder("api run")
        .add_plate("p", "plate_96_wellplate_200ul", slot=1)
        .add_tiprack("t", "tiprack_300ul", slot=2)
        .fill("p:A1", 100)
        .transfer("p:A1", "p:A2", 50)
        .build()
    )
    return protocol.model_dump(mode="json")


def _invalid() -> dict[str, Any]:
    # Parses fine but fails static validation: uses a fresh tip with no tip rack.
    protocol = (
        ProtocolBuilder("no tips")
        .add_plate("p", "plate_96_wellplate_200ul", slot=1)
        .fill("p:A1", 100)
        .transfer("p:A1", "p:A2", 50)
        .build()
    )
    return protocol.model_dump(mode="json")


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_validate_endpoint(client: TestClient) -> None:
    assert client.post("/protocols/validate", json=_valid()).json()["ok"] is True
    bad = client.post("/protocols/validate", json=_invalid()).json()
    assert bad["ok"] is False
    assert any(i["code"] == "E_NO_TIPRACK" for i in bad["issues"])


def test_submit_and_monitor_run(client: TestClient) -> None:
    resp = client.post("/runs", json={"protocol": _valid()})
    assert resp.status_code == 201
    summary = resp.json()
    assert summary["status"] == "completed"
    run_id = summary["id"]

    run = client.get(f"/runs/{run_id}").json()
    assert run["status"] == "completed"

    events = client.get(f"/runs/{run_id}/events").json()
    assert events[0]["type"] == "run_started"

    diag = client.get(f"/runs/{run_id}/diagnostics").json()
    assert diag["command_count"] > 0
    assert diag["retry_count"] == 0
    assert diag["recovery_failures"] == 0


def test_submit_with_hard_faults_fails(client: TestClient) -> None:
    body = {"protocol": _valid(), "faults": {"seed": 1, "hard_rate": 1.0}}
    summary = client.post("/runs", json=body).json()
    assert summary["status"] == "failed"
    assert summary["failure"]["code"] == "E_HARDWARE_FAILURE"

    diag = client.get(f"/runs/{summary['id']}/diagnostics").json()
    assert diag["recovery_failures"] >= 1


def test_submit_invalid_protocol_reports_invalid(client: TestClient) -> None:
    summary = client.post("/runs", json={"protocol": _invalid()}).json()
    assert summary["status"] == "invalid"
    assert summary["failure"]["code"] == "E_NO_TIPRACK"
    assert client.get(f"/runs/{summary['id']}/events").json() == []


def test_invalid_fault_rates_rejected(client: TestClient) -> None:
    body = {"protocol": _valid(), "faults": {"transient_rate": 0.8, "hard_rate": 0.8}}
    assert client.post("/runs", json=body).status_code == 422


def test_missing_run_is_404(client: TestClient) -> None:
    assert client.get("/runs/nope").status_code == 404
    assert client.get("/runs/nope/events").status_code == 404
    assert client.get("/runs/nope/diagnostics").status_code == 404


def test_list_runs(client: TestClient) -> None:
    client.post("/runs", json={"protocol": _valid()})
    client.post("/runs", json={"protocol": _valid()})
    runs = client.get("/runs").json()
    assert len(runs) == 2
