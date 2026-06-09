from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from benchbot.api.app import create_app
from benchbot.domain.protocol import ProtocolBuilder
from benchbot.workcell.workflow import (
    IncubateTask,
    ReadPlateTask,
    RunProtocolTask,
    Workflow,
)


@pytest.fixture
def client(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    db = tmp_path / "test.db"
    monkeypatch.setenv("BENCHBOT_DATABASE_URL", f"sqlite+aiosqlite:///{db}")
    with TestClient(create_app()) as c:
        yield c


def _workflow_json() -> dict[str, Any]:
    protocol = (
        ProtocolBuilder("prep")
        .add_plate("p", "plate_96_wellplate_200ul", 1)
        .add_tiprack("t", "tiprack_300ul", 2)
        .fill("p:A1", 200)
        .transfer("p:A1", "p:A2", 100)
        .build()
    )
    workflow = Workflow(
        name="assay",
        tasks=[
            RunProtocolTask(id="prep", device="lh1", protocol=protocol),
            IncubateTask(id="incubate", device="inc1", minutes=30, celsius=37),
            ReadPlateTask(id="read", device="reader1", plate="p", depends_on=["incubate"]),
        ],
    )
    return workflow.model_dump(mode="json")


def test_workcell_health_starts_clean(client: TestClient) -> None:
    health = client.get("/workcell/health").json()
    names = {d["name"] for d in health["devices"]}
    assert names == {"lh1", "reader1", "inc1"}
    assert all(d["health"] == "ok" for d in health["devices"])


def test_submit_workflow_completes(client: TestClient) -> None:
    result = client.post("/workflows", json={"workflow": _workflow_json()}).json()
    assert result["status"] == "completed"
    assert all(t["outcome"] == "completed" for t in result["tasks"])


def test_submitted_workflow_is_persisted_and_queryable(client: TestClient) -> None:
    result = client.post("/workflows", json={"workflow": _workflow_json()}).json()
    run_id = result["id"]
    assert run_id is not None

    listed = client.get("/workflows").json()
    assert any(r["id"] == run_id and r["task_count"] == 3 for r in listed)

    run = client.get(f"/workflows/{run_id}").json()
    assert run["name"] == "assay"
    assert run["status"] == "completed"
    # The stored definition keeps the DAG edges.
    read = next(t for t in run["workflow"]["tasks"] if t["id"] == "read")
    assert read["depends_on"] == ["incubate"]

    events = client.get(f"/workflows/{run_id}/events").json()
    assert events[0]["type"] == "workflow_started"


def test_missing_workflow_is_404(client: TestClient) -> None:
    assert client.get("/workflows/nope").status_code == 404
    assert client.get("/workflows/nope/events").status_code == 404


def test_demo_endpoint_persists_a_run(client: TestClient) -> None:
    healthy = client.post("/workflows/demo").json()
    assert healthy["status"] == "completed"
    assert healthy["id"] is not None

    degraded = client.post("/workflows/demo", params={"hard_rate": 1.0, "seed": 1}).json()
    assert degraded["status"] == "degraded"

    runs = client.get("/workflows").json()
    assert {healthy["id"], degraded["id"]} <= {r["id"] for r in runs}


def test_workflow_degrades_under_device_fault(client: TestClient) -> None:
    body = {"workflow": _workflow_json(), "faults": {"inc1": {"seed": 1, "hard_rate": 1.0}}}
    result = client.post("/workflows", json=body).json()
    assert result["status"] == "degraded"
    outcomes = {t["id"]: t["outcome"] for t in result["tasks"]}
    assert outcomes["incubate"] == "failed"
    assert outcomes["read"] == "skipped"
    assert outcomes["prep"] == "completed"

    # The health endpoint now reflects the quarantined device.
    health = client.get("/workcell/health").json()
    inc1 = next(d for d in health["devices"] if d["name"] == "inc1")
    assert inc1["health"] == "down"
    assert inc1["errors"] >= 1


def test_invalid_workflow_returns_invalid(client: TestClient) -> None:
    bad = Workflow(tasks=[RunProtocolTask(id="x", device="reader1", protocol=_proto())]).model_dump(
        mode="json"
    )
    result = client.post("/workflows", json={"workflow": bad}).json()
    assert result["status"] == "invalid"


def _proto() -> Any:
    return (
        ProtocolBuilder("p")
        .add_plate("p", "plate_96_wellplate_200ul", 1)
        .add_tiprack("t", "tiprack_300ul", 2)
        .fill("p:A1", 100)
        .transfer("p:A1", "p:A2", 50)
        .build()
    )
