from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from open_duck_x5.probe import main


def test_mock_probe_writes_schema_valid_jsonl_and_summary(tmp_path: Path) -> None:
    output = tmp_path / "timing.jsonl"
    summary_path = tmp_path / "summary.json"
    assert (
        main(
            [
                "--bus",
                "mock",
                "--ticks",
                "12",
                "--mock-latency-ms",
                "0",
                "--output",
                str(output),
                "--summary",
                str(summary_path),
            ]
        )
        == 0
    )
    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    schema_path = Path(__file__).parents[1] / "schemas" / "timing_tick.schema.json"
    validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
    assert len(records) == 12
    for record in records:
        validator.validate(record)
        assert len(record["motion"]["target_positions_rad"]) == 14
        assert len(record["motion"]["actual_positions_rad"]) == 14
        assert len(record["motion"]["absolute_error_rad"]) == 14

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["schema_version"] == "open_duck_x5.timing_summary.v2"
    assert summary["run_status"] == "COMPLETE"
    assert summary["halt_reason"] is None
    assert summary["backend"] == "mock"
    assert summary["informational_only"] is True
    assert summary["ticks"] == 12
    assert summary["transactions_failed"] == 0
    assert summary["transaction_status_counts"]["ok"] == 12 * 16
    assert summary["transaction_failure_counts"] == {
        "timeout": 0,
        "crc": 0,
        "partial": 0,
        "device": 0,
        "unexpected_id": 0,
        "io": 0,
        "unexpected_packet": 0,
    }
    assert summary["tracking_absolute_error_rad"]["samples"] == 12
    assert summary["environment"]["telemetry_records_dropped"] == 0


def test_mock_moving_probe_runs_slow_home_path(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    output = tmp_path / "moving.jsonl"
    summary_path = tmp_path / "moving-summary.json"
    assert (
        main(
            [
                "--bus",
                "mock",
                "--enable-torque",
                "--config",
                str(root / "duck_config.example.json"),
                "--home-seconds",
                "0.001",
                "--ticks",
                "2",
                "--mock-latency-ms",
                "0",
                "--output",
                str(output),
                "--summary",
                str(summary_path),
            ]
        )
        == 0
    )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["environment"]["torque_enabled"] is True
    assert len(summary["environment"]["config_sha256"]) == 64


def test_serial_movement_needs_gate_assertion_before_opening_bus(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "--bus",
                "serial",
                "--enable-torque",
                "--hardware-authorized",
                "--suspended-or-benched",
                "--output",
                str(tmp_path / "never.jsonl"),
                "--summary",
                str(tmp_path / "never.json"),
            ]
        )
