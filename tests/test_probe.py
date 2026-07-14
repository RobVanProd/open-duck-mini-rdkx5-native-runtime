from __future__ import annotations

import json
from pathlib import Path

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

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["backend"] == "mock"
    assert summary["informational_only"] is True
    assert summary["ticks"] == 12
    assert summary["transactions_failed"] == 0
    assert summary["environment"]["telemetry_records_dropped"] == 0
