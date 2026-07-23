from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from open_duck_x5.probe import main as probe_main
from tools.compare_timing import main as comparison_main


def _mock_summary(tmp_path: Path) -> Path:
    summary = tmp_path / "summary.json"
    assert (
        probe_main(
            [
                "--bus",
                "mock",
                "--ticks",
                "3",
                "--mock-latency-ms",
                "0",
                "--output",
                str(tmp_path / "timing.jsonl"),
                "--summary",
                str(summary),
            ]
        )
        == 0
    )
    return summary


def test_mock_comparison_is_hashed_informational_and_schema_valid(tmp_path: Path) -> None:
    summary = _mock_summary(tmp_path)
    output = tmp_path / "comparison.json"

    assert comparison_main(["--new-summary", str(summary), "--output", str(output)]) == 0

    result = json.loads(output.read_text(encoding="utf-8"))
    schema_path = Path(__file__).parents[1] / "schemas/baseline_comparison.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(result)
    assert result["status"] == "INFORMATIONAL_MOCK"
    assert result["new_summary_source"]["sha256"] == hashlib.sha256(
        summary.read_bytes()
    ).hexdigest()


def test_comparison_rejects_incomplete_summary(tmp_path: Path) -> None:
    summary = _mock_summary(tmp_path)
    value = json.loads(summary.read_text(encoding="utf-8"))
    value["run_status"] = "HALTED"
    value["halt_reason"] = "synthetic interruption"
    summary.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(SystemExit):
        comparison_main(
            ["--new-summary", str(summary), "--output", str(tmp_path / "never.json")]
        )


def test_comparison_refuses_to_overwrite_source_summary(tmp_path: Path) -> None:
    summary = _mock_summary(tmp_path)
    before = summary.read_bytes()

    with pytest.raises(SystemExit):
        comparison_main(["--new-summary", str(summary), "--output", str(summary)])

    assert summary.read_bytes() == before
