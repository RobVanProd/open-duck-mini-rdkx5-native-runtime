from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from open_duck_x5.single_servo_probe import main


def test_single_servo_probe_records_torque_off_mock_evidence(tmp_path: Path) -> None:
    output = tmp_path / "single.jsonl"
    summary_path = tmp_path / "single-summary.json"
    assert (
        main(
            [
                "--bus",
                "mock",
                "--servo-id",
                "20",
                "--ticks",
                "10",
                "--output",
                str(output),
                "--summary",
                str(summary_path),
            ]
        )
        == 0
    )
    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    schema_path = Path(__file__).parents[1] / "schemas" / "single_servo_tick.schema.json"
    validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
    assert len(records) == 10
    for record in records:
        validator.validate(record)
        assert record["servo_id"] == 20
        assert record["status"] == "ok"
        assert record["response_length"] == 2

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["run_status"] == "COMPLETE"
    assert summary["halt_reason"] is None
    assert summary["ping_status"] == "ok"
    assert summary["transactions_failed"] == 0
    assert summary["transaction_status_counts"]["ok"] == 10
    assert summary["environment"]["torque_enabled"] is False


def test_single_servo_serial_probe_requires_hardware_assertions(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "--bus",
                "serial",
                "--output",
                str(tmp_path / "never.jsonl"),
                "--summary",
                str(tmp_path / "never.json"),
            ]
        )
