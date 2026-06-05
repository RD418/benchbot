from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from benchbot.cli import app

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
runner = CliRunner()


def test_validate_ok() -> None:
    result = runner.invoke(app, ["validate", str(EXAMPLES / "serial_dilution.yaml")])
    assert result.exit_code == 0
    assert "OK" in result.output


def test_validate_invalid() -> None:
    result = runner.invoke(app, ["validate", str(EXAMPLES / "invalid_protocol.yaml")])
    assert result.exit_code == 1
    assert "E_SAME_SOURCE_DEST" in result.output


def test_run_completes() -> None:
    result = runner.invoke(app, ["run", str(EXAMPLES / "serial_dilution.yaml")])
    assert result.exit_code == 0
    assert "status: completed" in result.output


def test_run_with_hard_fault_fails() -> None:
    result = runner.invoke(
        app,
        ["run", str(EXAMPLES / "serial_dilution.yaml"), "--hard-rate", "1.0", "--seed", "1"],
    )
    assert result.exit_code == 1
    assert "failed" in result.output


def test_run_save_then_list_and_show(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "cli.db"
    monkeypatch.setenv("BENCHBOT_DATABASE_URL", f"sqlite+aiosqlite:///{db}")

    saved = runner.invoke(app, ["run", str(EXAMPLES / "serial_dilution.yaml"), "--save"])
    assert saved.exit_code == 0
    assert "saved run:" in saved.output
    run_id = saved.output.split("saved run:")[1].strip().splitlines()[0]

    listed = runner.invoke(app, ["list"])
    assert listed.exit_code == 0
    assert "completed" in listed.output

    shown = runner.invoke(app, ["show", run_id])
    assert shown.exit_code == 0
    assert run_id in shown.output

    events = runner.invoke(app, ["events", run_id])
    assert events.exit_code == 0
    assert "run_started" in events.output


def test_show_missing_run() -> None:
    result = runner.invoke(app, ["show", "does-not-exist"])
    assert result.exit_code == 1
