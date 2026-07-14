from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from open_duck_x5 import sensor_probe


def _config() -> Path:
    return Path(__file__).parents[1] / "duck_config.example.json"


def _validator(name: str) -> Draft202012Validator:
    path = Path(__file__).parents[1] / "schemas" / name
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


def test_mock_sensor_probe_writes_labeled_schema_valid_evidence(tmp_path: Path) -> None:
    output = tmp_path / "upright.jsonl"
    summary_path = tmp_path / "upright-summary.json"

    assert (
        sensor_probe.main(
            [
                "--backend",
                "mock",
                "--label",
                "upright",
                "--config",
                str(_config()),
                "--samples",
                "4",
                "--frequency-hz",
                "1000",
                "--output",
                str(output),
                "--summary",
                str(summary_path),
            ]
        )
        == 0
    )

    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    tick_validator = _validator("sensor_tick.schema.json")
    assert len(records) == 4
    for index, record in enumerate(records):
        tick_validator.validate(record)
        assert record["sample"] == index
        assert record["label"] == "upright"
        assert record["imu"]["acceleration_m_s2"] == [0.0, 0.0, 9.81]

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    _validator("sensor_summary.schema.json").validate(summary)
    assert summary["backend"] == "mock"
    assert summary["review_status"] == "REVIEW_REQUIRED"
    assert summary["hardware_gate_status"] == "NOT_APPLICABLE_MOCK"
    assert summary["checks"]["zero_imu_stale"] is True
    assert summary["checks"]["zero_contacts_stale"] is True
    assert summary["environment"]["servo_bus_accessed"] is False
    assert summary["environment"]["goal_position_writes"] == 0
    assert summary["environment"]["hardware_authorized"] is False
    assert summary["environment"]["suspended_or_benched"] is False
    assert summary["checks"]["authorization_provenance"] is True
    assert summary["checks"]["gate3_data_candidate"] is False
    assert summary["jsonl_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()


def test_x5_sensor_probe_requires_both_guards_before_hardware_imports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def forbid_contacts() -> object:
        raise AssertionError("GPIO must not open before hardware authorization")

    monkeypatch.setattr(sensor_probe, "X5FootContacts", forbid_contacts)
    output = tmp_path / "never.jsonl"
    with pytest.raises(SystemExit):
        sensor_probe.main(
            [
                "--backend",
                "x5",
                "--label",
                "upright",
                "--config",
                str(_config()),
                "--samples",
                "2",
                "--output",
                str(output),
                "--summary",
                str(tmp_path / "never-summary.json"),
            ]
        )
    assert not output.exists()


def test_sensor_probe_refuses_to_overwrite_summary_with_jsonl(tmp_path: Path) -> None:
    same_path = tmp_path / "same.json"
    with pytest.raises(SystemExit):
        sensor_probe.main(
            [
                "--label",
                "upright",
                "--config",
                str(_config()),
                "--samples",
                "2",
                "--output",
                str(same_path),
                "--summary",
                str(same_path),
            ]
        )


def test_sensor_probe_cannot_overwrite_config(tmp_path: Path) -> None:
    config = tmp_path / "duck_config.json"
    original = _config().read_bytes()
    config.write_bytes(original)
    with pytest.raises(SystemExit):
        sensor_probe.main(
            [
                "--backend",
                "mock",
                "--label",
                "upright",
                "--config",
                str(config),
                "--samples",
                "2",
                "--output",
                str(config),
                "--summary",
                str(tmp_path / "summary.json"),
            ]
        )
    assert config.read_bytes() == original
