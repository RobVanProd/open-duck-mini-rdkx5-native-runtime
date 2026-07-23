from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from open_duck_x5 import sensor_probe
from open_duck_x5.sensors import SensorReadout


def _config() -> Path:
    return Path(__file__).parents[1] / "duck_config.example.json"


def _validator(name: str) -> Draft202012Validator:
    path = Path(__file__).parents[1] / "schemas" / name
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


def _calibration(tmp_path: Path) -> Path:
    path = tmp_path / "imu_calibration.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "open_duck_x5.bno055_calibration.v1",
                "source_format": "apirrone.imu_calib_data.pkl",
                "source_sha256": "a" * 64,
                "offsets_accelerometer": [1, 2, 3],
                "offsets_gyroscope": [4, 5, 6],
                "offsets_magnetometer": [7, 8, 9],
            }
        ),
        encoding="utf-8",
    )
    return path


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
    assert summary["environment"]["policy_loaded"] is False
    assert summary["environment"]["policy_inference_count"] == 0
    assert summary["environment"]["hardware_authorized"] is False
    assert summary["environment"]["suspended_or_benched"] is False
    assert summary["checks"]["authorization_provenance"] is True
    assert summary["checks"]["gate3_data_candidate"] is False
    assert summary["checks"]["bno055_identity_verified"] is False
    assert summary["checks"]["calibration_profile_applied"] is False
    assert summary["checks"]["operator_label_confirmed"] is False
    assert summary["sensor_health"]["sample_errors"] == 0
    assert summary["jsonl_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()


def test_x5_sensor_probe_requires_both_guards_before_hardware_imports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def forbid_contacts() -> object:
        raise AssertionError("GPIO must not open before hardware authorization")

    monkeypatch.setattr(sensor_probe, "X5FootContacts", forbid_contacts)
    calibration = _calibration(tmp_path)
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
                "--imu-calibration",
                str(calibration),
                "--operator-confirmed-label",
                "upright",
                "--samples",
                "2",
                "--output",
                str(output),
                "--summary",
                str(tmp_path / "never-summary.json"),
            ]
        )
    assert not output.exists()


def test_x5_sensor_probe_requires_calibration_and_exact_operator_label(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def forbid_contacts() -> object:
        raise AssertionError("GPIO must not open during argument validation")

    monkeypatch.setattr(sensor_probe, "X5FootContacts", forbid_contacts)
    base = [
        "--backend",
        "x5",
        "--label",
        "upright",
        "--config",
        str(_config()),
        "--samples",
        "2",
        "--output",
        str(tmp_path / "never.jsonl"),
        "--summary",
        str(tmp_path / "never-summary.json"),
        "--hardware-authorized",
        "--suspended-or-benched",
    ]

    with pytest.raises(SystemExit):
        sensor_probe.main(base)

    with pytest.raises(SystemExit):
        sensor_probe.main(
            [
                *base,
                "--imu-calibration",
                str(_calibration(tmp_path)),
                "--operator-confirmed-label",
                "nose_forward",
            ]
        )


def test_x5_candidate_requires_device_and_worker_proofs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeHub:
        def __init__(self) -> None:
            self.ready = False

        def wait_until_ready(self, timeout_s: float) -> None:
            assert timeout_s == 2.0
            self.ready = True

        def read_into(self, output: SensorReadout, now_ns: int) -> None:
            assert self.ready, "probe read before initial sensor publication"
            output.gyro_rad_s[:] = (0.1, 0.2, 0.3)
            output.acceleration_m_s2[:] = (0.0, 0.0, 9.81)
            output.contacts[:] = (0.0, 0.0)
            output.imu_timestamp_ns = now_ns
            output.contacts_timestamp_ns = now_ns
            output.imu_age_ns = 0
            output.contacts_age_ns = 0
            output.imu_stale = False
            output.contacts_stale = False

        def close(self) -> None:
            return None

        def diagnostics(self) -> dict[str, object]:
            return {
                "sample_attempts": 4,
                "sample_successes": 4,
                "sample_errors": 0,
                "consecutive_errors": 0,
                "max_consecutive_errors": 0,
                "last_error_type": None,
                "imu": {
                    "identity_verified": True,
                    "calibration_applied": True,
                    "calibration_readback_verified": True,
                },
            }

    fake_hub = FakeHub()
    monkeypatch.setattr(
        sensor_probe,
        "_create_hub",
        lambda _args, _config, _calibration: fake_hub,
    )
    output = tmp_path / "upright.jsonl"
    summary_path = tmp_path / "upright-summary.json"

    assert (
        sensor_probe.main(
            [
                "--backend",
                "x5",
                "--label",
                "upright",
                "--operator-confirmed-label",
                "upright",
                "--config",
                str(_config()),
                "--imu-calibration",
                str(_calibration(tmp_path)),
                "--samples",
                "4",
                "--frequency-hz",
                "1000",
                "--output",
                str(output),
                "--summary",
                str(summary_path),
                "--hardware-authorized",
                "--suspended-or-benched",
            ]
        )
        == 0
    )

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    _validator("sensor_summary.schema.json").validate(summary)
    assert summary["checks"]["gate3_data_candidate"] is True
    assert summary["checks"]["operator_label_confirmed"] is True
    assert summary["checks"]["calibration_readback_verified"] is True
    assert summary["environment"]["initial_sample_ready_timeout_s"] == 2.0


def test_sensor_probe_ready_timeout_closes_without_publishing_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class NeverReadyHub:
        def __init__(self) -> None:
            self.closed = False

        @staticmethod
        def wait_until_ready(timeout_s: float) -> None:
            assert timeout_s == 2.0
            raise RuntimeError("injected initial sensor timeout")

        @staticmethod
        def read_into(_output: SensorReadout, _now_ns: int) -> None:
            raise AssertionError("probe must not read after ready timeout")

        def close(self) -> None:
            self.closed = True

        @staticmethod
        def diagnostics() -> dict[str, object]:
            return {}

    hub = NeverReadyHub()
    monkeypatch.setattr(
        sensor_probe,
        "_create_hub",
        lambda _args, _config, _calibration: hub,
    )
    output = tmp_path / "never.jsonl"
    summary = tmp_path / "never-summary.json"

    with pytest.raises(SystemExit):
        sensor_probe.main(
            [
                "--backend",
                "mock",
                "--label",
                "upright",
                "--config",
                str(_config()),
                "--samples",
                "2",
                "--output",
                str(output),
                "--summary",
                str(summary),
            ]
        )

    assert hub.closed is True
    assert not output.exists()
    assert not summary.exists()


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
