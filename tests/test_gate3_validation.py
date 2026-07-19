from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from open_duck_x5 import gate3_validation
from open_duck_x5.sensor_probe import SENSOR_LABELS


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_gate3_run(root: Path) -> Path:
    software = gate3_validation._expected_software_hashes()
    root.mkdir(parents=True)
    calibration_path = root / gate3_validation.CALIBRATION_FILENAME
    calibration_path.write_text(
        json.dumps(
            {
                "schema_version": "open_duck_x5.bno055_calibration.v1",
                "source_format": "apirrone.imu_calib_data.pkl",
                "source_sha256": "d" * 64,
                "offsets_accelerometer": [1, 2, 3],
                "offsets_gyroscope": [4, 5, 6],
                "offsets_magnetometer": [7, 8, 9],
            }
        ),
        encoding="utf-8",
    )
    calibration_sha256 = _sha256(calibration_path)
    contact_values = {
        "no_contacts": (0.0, 0.0),
        "left_contact": (1.0, 0.0),
        "right_contact": (0.0, 1.0),
        "both_contacts": (1.0, 1.0),
    }
    for label in SENSOR_LABELS:
        label_root = root / label
        label_root.mkdir(parents=True)
        sensor_path = label_root / gate3_validation.SAMPLES_FILENAME
        left, right = contact_values.get(label, (0.0, 0.0))
        records = []
        for index in range(gate3_validation.EXPECTED_SAMPLES):
            timestamp = 1_000_000_000 + index * 20_000_000
            records.append(
                {
                    "schema_version": "open_duck_x5.sensor_tick.v1",
                    "sample": index,
                    "label": label,
                    "timestamp_monotonic_ns": timestamp,
                    "tick_period_ms": None if index == 0 else 20.0,
                    "release_lateness_ms": 0.001,
                    "imu": {
                        "sample_timestamp_ns": timestamp + 100,
                        "age_ms": 0.1,
                        "stale": False,
                        "gyro_rad_s": [0.0, 0.0, 0.0],
                        "acceleration_m_s2": [0.0, 0.0, 9.81],
                    },
                    "contacts": {
                        "sample_timestamp_ns": timestamp + 200,
                        "age_ms": 0.1,
                        "stale": False,
                        "left": left,
                        "right": right,
                    },
                }
            )
        sensor_path.write_text(
            "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records),
            encoding="utf-8",
        )
        summary = {
            "schema_version": "open_duck_x5.sensor_summary.v2",
            "backend": "x5",
            "informational_only": False,
            "hardware_gate_status": "REVIEW_REQUIRED",
            "run_status": "COMPLETE",
            "review_status": "REVIEW_REQUIRED",
            "label": label,
            "samples": 250,
            "samples_requested": 250,
            "config": {
                "sha256": gate3_validation.EXPECTED_CONFIG_SHA256,
                "imu_upside_down": True,
            },
            "software": software,
            "imu_calibration": {
                "required": True,
                "source_format": "apirrone.imu_calib_data.pkl",
                "profile_sha256": calibration_sha256,
                "source_sha256": "d" * 64,
            },
            "environment": {
                "frequency_hz": 50.0,
                "sensor_frequency_hz": 100.0,
                "stale_after_ms": 40.0,
                "imu_bus": 5,
                "imu_address": 0x28,
                "imu_i2c_device": "/dev/i2c-5",
                "contact_gpio_mapping": {
                    "numbering": "BCM",
                    "left": {"bcm": 22, "physical_pin": 15},
                    "right": {"bcm": 27, "physical_pin": 13},
                    "polarity": "raw GPIO false -> contact true",
                },
                "servo_bus_accessed": False,
                "torque_enabled": False,
                "goal_position_writes": 0,
                "policy_loaded": False,
                "policy_inference_count": 0,
                "hardware_authorized": True,
                "suspended_or_benched": True,
            },
            "sensor_health": {
                "sample_successes": 500,
                "sample_errors": 0,
                "last_error_type": None,
            },
            "checks": {
                "exact_sample_count": True,
                "zero_imu_stale": True,
                "zero_contacts_stale": True,
                "strictly_increasing_imu_timestamps": True,
                "strictly_increasing_contact_timestamps": True,
                "zero_sensor_worker_errors": True,
                "bno055_identity_verified": True,
                "calibration_profile_applied": True,
                "calibration_readback_verified": True,
                "operator_label_confirmed": True,
                "orientation_and_contact_label_match": "REVIEW_REQUIRED",
                "authorization_provenance": True,
                "gate3_data_candidate": True,
            },
            "imu": {
                "device": {
                    "identity_verified": True,
                    "calibration_applied": True,
                    "calibration_readback_verified": True,
                    "chip_id": 0xA0,
                    "operation_mode": 0x0C,
                    "axis_map_config": 0x21,
                    "axis_map_sign": 0x07,
                    "unit_selection": 0,
                    "upside_down": True,
                    "calibration_readback": {
                        "offsets_accelerometer": [1, 2, 3],
                        "offsets_gyroscope": [4, 5, 6],
                        "offsets_magnetometer": [7, 8, 9],
                    },
                    "calibration_profile_sha256": calibration_sha256,
                    "calibration_source_sha256": "d" * 64,
                }
            },
            "jsonl_sha256": _sha256(sensor_path),
        }
        (label_root / gate3_validation.SUMMARY_FILENAME).write_text(
            json.dumps(summary), encoding="utf-8"
        )
    return root


def test_gate3_validator_builds_review_only_packet(tmp_path: Path) -> None:
    run_root = _write_gate3_run(tmp_path / "run")
    output = tmp_path / "review.json"

    packet = gate3_validation.validate_gate3(run_root, output)

    assert output.is_file()
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas" / "gate3_review.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(packet)
    assert packet["status"] == "REVIEW_REQUIRED"
    assert packet["data_integrity_candidate"] is True
    assert packet["gate3_passed"] is False
    assert packet["physical_label_decision"] == "REVIEW_REQUIRED"
    assert len(packet["raw_artifacts"]) == 19
    assert packet["labels"]["left_contact"]["contact_pattern_consistent"] is True


def test_gate3_validator_rejects_tampered_jsonl(tmp_path: Path) -> None:
    run_root = _write_gate3_run(tmp_path / "run")
    sensor_path = run_root / "upright" / gate3_validation.SAMPLES_FILENAME
    sensor_path.write_text(sensor_path.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")

    with pytest.raises(gate3_validation.Gate3ValidationError, match="exactly 250"):
        gate3_validation.validate_gate3(run_root, tmp_path / "review.json")


def test_gate3_validator_rejects_source_hash_mismatch(tmp_path: Path) -> None:
    run_root = _write_gate3_run(tmp_path / "run")
    summary_path = run_root / "right_tilt" / gate3_validation.SUMMARY_FILENAME
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["software"]["sensors_sha256"] = "0" * 64
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(gate3_validation.Gate3ValidationError, match="source hash mismatch"):
        gate3_validation.validate_gate3(run_root, tmp_path / "review.json")
