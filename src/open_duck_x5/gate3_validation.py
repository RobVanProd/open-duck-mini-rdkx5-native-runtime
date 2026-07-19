from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from . import imu_calibration as imu_calibration_module
from . import sensor_probe as sensor_probe_module
from . import sensors as sensors_module
from .imu_calibration import BNO055Calibration, sha256_file
from .sensor_probe import SENSOR_LABELS

SAMPLES_FILENAME = "sensor.jsonl"
SUMMARY_FILENAME = "summary.json"
CALIBRATION_FILENAME = "imu_calibration.json"
EXPECTED_SAMPLES = 250
EXPECTED_FREQUENCY_HZ = 50.0
EXPECTED_SENSOR_FREQUENCY_HZ = 100.0
EXPECTED_STALE_AFTER_MS = 40.0
EXPECTED_CONFIG_SHA256 = "131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b"
MAX_SUMMARY_BYTES = 1024 * 1024
MAX_JSONL_BYTES = 32 * 1024 * 1024


class Gate3ValidationError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Gate3ValidationError(message)


def _load_json(path: Path, *, maximum_bytes: int) -> dict[str, Any]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise Gate3ValidationError(f"cannot stat {path}: {exc}") from exc
    _require(1 <= size <= maximum_bytes, f"invalid evidence file size for {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Gate3ValidationError(f"cannot read JSON {path}: {exc}") from exc
    _require(isinstance(data, dict), f"JSON root must be an object: {path}")
    return data


def _finite_vector(value: object, *, length: int, field: str) -> list[float]:
    _require(isinstance(value, list) and len(value) == length, f"bad {field} vector")
    result = [float(item) for item in value]
    _require(all(math.isfinite(item) for item in result), f"non-finite {field} vector")
    return result


def _load_records(path: Path, label: str) -> tuple[list[dict[str, Any]], dict[str, object]]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise Gate3ValidationError(f"cannot stat {path}: {exc}") from exc
    _require(1 <= size <= MAX_JSONL_BYTES, f"invalid evidence file size for {path}")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise Gate3ValidationError(f"cannot read JSONL {path}: {exc}") from exc
    _require(len(lines) == EXPECTED_SAMPLES, f"{label}: expected exactly 250 JSONL rows")

    records: list[dict[str, Any]] = []
    acceleration = np.zeros((EXPECTED_SAMPLES, 3), dtype=np.float64)
    gyro = np.zeros((EXPECTED_SAMPLES, 3), dtype=np.float64)
    contacts = np.zeros((EXPECTED_SAMPLES, 2), dtype=np.float64)
    previous_tick_timestamp = -1
    previous_imu_timestamp = -1
    previous_contact_timestamp = -1
    for index, line in enumerate(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise Gate3ValidationError(f"{label}: invalid JSONL row {index}: {exc}") from exc
        _require(isinstance(record, dict), f"{label}: row {index} is not an object")
        _require(
            record.get("schema_version") == "open_duck_x5.sensor_tick.v1",
            f"{label}: row {index} has wrong schema",
        )
        _require(record.get("sample") == index, f"{label}: row index mismatch at {index}")
        _require(record.get("label") == label, f"{label}: row label mismatch at {index}")
        tick_timestamp = int(record.get("timestamp_monotonic_ns", -1))
        _require(
            tick_timestamp > previous_tick_timestamp,
            f"{label}: nonincreasing tick timestamp at {index}",
        )
        previous_tick_timestamp = tick_timestamp

        imu = record.get("imu")
        contact = record.get("contacts")
        _require(isinstance(imu, dict), f"{label}: missing IMU row at {index}")
        _require(isinstance(contact, dict), f"{label}: missing contact row at {index}")
        imu_timestamp = int(imu.get("sample_timestamp_ns", -1))
        contact_timestamp = int(contact.get("sample_timestamp_ns", -1))
        _require(
            imu_timestamp > previous_imu_timestamp,
            f"{label}: nonincreasing IMU timestamp at {index}",
        )
        _require(
            contact_timestamp > previous_contact_timestamp,
            f"{label}: nonincreasing contact timestamp at {index}",
        )
        previous_imu_timestamp = imu_timestamp
        previous_contact_timestamp = contact_timestamp
        _require(imu.get("stale") is False, f"{label}: stale IMU row at {index}")
        _require(contact.get("stale") is False, f"{label}: stale contact row at {index}")
        imu_age_ms = float(imu.get("age_ms", math.inf))
        contact_age_ms = float(contact.get("age_ms", math.inf))
        _require(
            0 <= imu_age_ms <= EXPECTED_STALE_AFTER_MS,
            f"{label}: invalid IMU age at {index}",
        )
        _require(
            0 <= contact_age_ms <= EXPECTED_STALE_AFTER_MS,
            f"{label}: invalid contact age at {index}",
        )
        gyro[index] = _finite_vector(
            imu.get("gyro_rad_s"), length=3, field=f"{label} gyro"
        )
        acceleration[index] = _finite_vector(
            imu.get("acceleration_m_s2"),
            length=3,
            field=f"{label} acceleration",
        )
        left = float(contact.get("left", math.nan))
        right = float(contact.get("right", math.nan))
        _require(left in (0.0, 1.0), f"{label}: nondigital left contact at {index}")
        _require(right in (0.0, 1.0), f"{label}: nondigital right contact at {index}")
        contacts[index] = (left, right)
        records.append(record)

    metrics: dict[str, object] = {
        "acceleration_mean_m_s2": acceleration.mean(axis=0).tolist(),
        "gyro_mean_rad_s": gyro.mean(axis=0).tolist(),
        "gyro_abs_max_rad_s": np.abs(gyro).max(axis=0).tolist(),
        "contact_mean": contacts.mean(axis=0).tolist(),
    }
    return records, metrics


def _expected_software_hashes() -> dict[str, str]:
    return {
        "sensor_probe_sha256": sha256_file(Path(sensor_probe_module.__file__).resolve()),
        "sensors_sha256": sha256_file(Path(sensors_module.__file__).resolve()),
        "imu_calibration_sha256": sha256_file(
            Path(imu_calibration_module.__file__).resolve()
        ),
    }


def _validate_summary(
    summary: dict[str, Any],
    *,
    label: str,
    jsonl_path: Path,
    expected_software: dict[str, str],
    expected_calibration: BNO055Calibration,
) -> None:
    _require(
        summary.get("schema_version") == "open_duck_x5.sensor_summary.v2",
        f"{label}: wrong summary schema",
    )
    expected_scalars = {
        "backend": "x5",
        "informational_only": False,
        "hardware_gate_status": "REVIEW_REQUIRED",
        "run_status": "COMPLETE",
        "review_status": "REVIEW_REQUIRED",
        "label": label,
        "samples": EXPECTED_SAMPLES,
        "samples_requested": EXPECTED_SAMPLES,
    }
    for field, expected in expected_scalars.items():
        _require(summary.get(field) == expected, f"{label}: bad summary field {field}")
    _require(
        summary.get("jsonl_sha256") == sha256_file(jsonl_path),
        f"{label}: JSONL hash mismatch",
    )

    config = summary.get("config")
    _require(isinstance(config, dict), f"{label}: missing config provenance")
    config_sha256 = config.get("sha256")
    _require(
        config_sha256 == EXPECTED_CONFIG_SHA256,
        f"{label}: config hash does not match the preregistered board config",
    )
    _require(config.get("imu_upside_down") is True, f"{label}: unexpected IMU orientation")

    environment = summary.get("environment")
    _require(isinstance(environment, dict), f"{label}: missing environment")
    expected_environment = {
        "frequency_hz": EXPECTED_FREQUENCY_HZ,
        "sensor_frequency_hz": EXPECTED_SENSOR_FREQUENCY_HZ,
        "stale_after_ms": EXPECTED_STALE_AFTER_MS,
        "imu_bus": 5,
        "imu_address": 0x28,
        "imu_i2c_device": "/dev/i2c-5",
        "servo_bus_accessed": False,
        "torque_enabled": False,
        "goal_position_writes": 0,
        "policy_loaded": False,
        "policy_inference_count": 0,
        "hardware_authorized": True,
        "suspended_or_benched": True,
    }
    for field, expected in expected_environment.items():
        _require(
            environment.get(field) == expected,
            f"{label}: bad environment field {field}",
        )
    expected_gpio = {
        "numbering": "BCM",
        "left": {"bcm": 22, "physical_pin": 15},
        "right": {"bcm": 27, "physical_pin": 13},
        "polarity": "raw GPIO false -> contact true",
    }
    _require(
        environment.get("contact_gpio_mapping") == expected_gpio,
        f"{label}: contact GPIO mapping changed",
    )

    software = summary.get("software")
    _require(isinstance(software, dict), f"{label}: missing software provenance")
    for field, expected in expected_software.items():
        _require(software.get(field) == expected, f"{label}: source hash mismatch for {field}")

    calibration = summary.get("imu_calibration")
    _require(isinstance(calibration, dict), f"{label}: missing calibration provenance")
    _require(calibration.get("required") is True, f"{label}: calibration not required")
    _require(
        calibration.get("source_format") == "apirrone.imu_calib_data.pkl",
        f"{label}: wrong calibration source format",
    )
    for field in ("profile_sha256", "source_sha256"):
        value = calibration.get(field)
        _require(
            isinstance(value, str) and len(value) == 64,
            f"{label}: bad calibration {field}",
        )
    _require(
        calibration.get("profile_sha256") == expected_calibration.profile_sha256,
        f"{label}: calibration profile hash does not match captured profile",
    )
    _require(
        calibration.get("source_sha256") == expected_calibration.source_sha256,
        f"{label}: calibration source hash does not match captured profile",
    )

    health = summary.get("sensor_health")
    _require(isinstance(health, dict), f"{label}: missing sensor health")
    _require(health.get("sample_errors") == 0, f"{label}: sensor worker errors")
    _require(
        isinstance(health.get("sample_successes"), int)
        and health["sample_successes"] > 0,
        f"{label}: no successful sensor samples",
    )
    _require(
        health.get("last_error_type") is None,
        f"{label}: sensor worker recorded an error type",
    )

    checks = summary.get("checks")
    _require(isinstance(checks, dict), f"{label}: missing checks")
    required_true_checks = (
        "exact_sample_count",
        "zero_imu_stale",
        "zero_contacts_stale",
        "strictly_increasing_imu_timestamps",
        "strictly_increasing_contact_timestamps",
        "zero_sensor_worker_errors",
        "bno055_identity_verified",
        "calibration_profile_applied",
        "calibration_readback_verified",
        "operator_label_confirmed",
        "authorization_provenance",
        "gate3_data_candidate",
    )
    for field in required_true_checks:
        _require(checks.get(field) is True, f"{label}: check did not pass: {field}")
    _require(
        checks.get("orientation_and_contact_label_match") == "REVIEW_REQUIRED",
        f"{label}: physical label review was auto-promoted",
    )

    imu = summary.get("imu")
    _require(isinstance(imu, dict), f"{label}: missing IMU summary")
    device = imu.get("device")
    _require(isinstance(device, dict), f"{label}: missing IMU device readback")
    for field in (
        "identity_verified",
        "calibration_applied",
        "calibration_readback_verified",
    ):
        _require(device.get(field) is True, f"{label}: IMU device proof failed: {field}")
    expected_device_readback = {
        "chip_id": 0xA0,
        "operation_mode": 0x0C,
        "axis_map_config": 0x21,
        "axis_map_sign": 0x07,
        "unit_selection": 0,
        "upside_down": True,
    }
    for field, expected in expected_device_readback.items():
        _require(
            device.get(field) == expected,
            f"{label}: bad IMU device readback for {field}",
        )
    _require(
        isinstance(device.get("calibration_readback"), dict),
        f"{label}: missing calibration register readback",
    )
    expected_offset_readback = {
        "offsets_accelerometer": list(expected_calibration.offsets_accelerometer),
        "offsets_gyroscope": list(expected_calibration.offsets_gyroscope),
        "offsets_magnetometer": list(expected_calibration.offsets_magnetometer),
    }
    _require(
        device.get("calibration_readback") == expected_offset_readback,
        f"{label}: calibration register values do not match captured profile",
    )
    _require(
        device.get("calibration_profile_sha256") == calibration.get("profile_sha256"),
        f"{label}: calibration profile readback provenance mismatch",
    )
    _require(
        device.get("calibration_source_sha256") == calibration.get("source_sha256"),
        f"{label}: calibration source provenance mismatch",
    )


def validate_gate3(run_root: Path, output: Path) -> dict[str, object]:
    run_root = run_root.expanduser().resolve()
    output = output.expanduser().resolve()
    _require(run_root.is_dir(), f"Gate 3 run root is not a directory: {run_root}")
    if output.exists():
        raise Gate3ValidationError(f"refusing to overwrite existing review packet: {output}")

    expected_software = _expected_software_hashes()
    calibration_path = run_root / CALIBRATION_FILENAME
    _require(calibration_path.is_file(), f"missing captured {CALIBRATION_FILENAME}")
    expected_calibration = BNO055Calibration.load(calibration_path)
    per_label: dict[str, object] = {}
    common_config_sha256: str | None = None
    common_calibration_profile_sha256: str | None = None
    common_calibration_source_sha256: str | None = None
    raw_artifacts: list[dict[str, str]] = [
        {
            "path": CALIBRATION_FILENAME,
            "sha256": sha256_file(calibration_path),
        }
    ]

    for label in SENSOR_LABELS:
        label_root = run_root / label
        jsonl_path = label_root / SAMPLES_FILENAME
        summary_path = label_root / SUMMARY_FILENAME
        _require(jsonl_path.is_file(), f"{label}: missing {SAMPLES_FILENAME}")
        _require(summary_path.is_file(), f"{label}: missing {SUMMARY_FILENAME}")
        _records, metrics = _load_records(jsonl_path, label)
        summary = _load_json(summary_path, maximum_bytes=MAX_SUMMARY_BYTES)
        _validate_summary(
            summary,
            label=label,
            jsonl_path=jsonl_path,
            expected_software=expected_software,
            expected_calibration=expected_calibration,
        )

        config_sha256 = str(summary["config"]["sha256"])
        profile_sha256 = str(summary["imu_calibration"]["profile_sha256"])
        source_sha256 = str(summary["imu_calibration"]["source_sha256"])
        if common_config_sha256 is None:
            common_config_sha256 = config_sha256
            common_calibration_profile_sha256 = profile_sha256
            common_calibration_source_sha256 = source_sha256
        _require(config_sha256 == common_config_sha256, f"{label}: config hash changed")
        _require(
            profile_sha256 == common_calibration_profile_sha256,
            f"{label}: calibration profile hash changed",
        )
        _require(
            source_sha256 == common_calibration_source_sha256,
            f"{label}: calibration source hash changed",
        )
        per_label[label] = {
            **metrics,
            "operator_label_confirmed": True,
            "physical_label_decision": "REVIEW_REQUIRED",
        }
        raw_artifacts.extend(
            (
                {
                    "path": str(jsonl_path.relative_to(run_root)),
                    "sha256": sha256_file(jsonl_path),
                },
                {
                    "path": str(summary_path.relative_to(run_root)),
                    "sha256": sha256_file(summary_path),
                },
            )
        )

    contact_expectations = {
        "no_contacts": [0.0, 0.0],
        "left_contact": [1.0, 0.0],
        "right_contact": [0.0, 1.0],
        "both_contacts": [1.0, 1.0],
    }
    for label, expected in contact_expectations.items():
        observed = per_label[label]["contact_mean"]
        per_label[label]["expected_contact_pattern"] = expected
        per_label[label]["contact_pattern_consistent"] = all(
            abs(float(actual) - wanted) <= 0.05
            for actual, wanted in zip(observed, expected, strict=True)
        )
        _require(
            bool(per_label[label]["contact_pattern_consistent"]),
            f"{label}: contact pattern is inconsistent with the typed physical label",
        )

    packet: dict[str, object] = {
        "schema_version": "open_duck_x5.gate3_review.v1",
        "status": "REVIEW_REQUIRED",
        "data_integrity_candidate": True,
        "physical_label_decision": "REVIEW_REQUIRED",
        "gate3_passed": False,
        "required_labels": list(SENSOR_LABELS),
        "capture_contract": {
            "samples_per_label": EXPECTED_SAMPLES,
            "frequency_hz": EXPECTED_FREQUENCY_HZ,
            "sensor_frequency_hz": EXPECTED_SENSOR_FREQUENCY_HZ,
            "stale_after_ms": EXPECTED_STALE_AFTER_MS,
            "config_sha256": EXPECTED_CONFIG_SHA256,
            "imu_i2c_device": "/dev/i2c-5",
            "imu_address": 0x28,
            "servo_bus_accessed": False,
            "torque_enabled": False,
        },
        "provenance": {
            "config_sha256": common_config_sha256,
            "calibration_profile_sha256": common_calibration_profile_sha256,
            "calibration_source_sha256": common_calibration_source_sha256,
            "software": expected_software,
        },
        "labels": per_label,
        "raw_artifacts": raw_artifacts,
        "review_instructions": [
            "Verify upright gravity and all four labeled tilt directions from acceleration means.",
            "Verify each physical foot-switch actuation matches the labeled contact pattern.",
            "Keep Gate 3 blocked if any physical label is ambiguous or reversed.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(packet, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except OSError as exc:
        raise Gate3ValidationError(f"cannot create review packet {output}: {exc}") from exc
    return packet


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate frozen Gate 3 sensor captures without auto-passing physical labels"
    )
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        packet = validate_gate3(args.run_root, args.output)
    except (Gate3ValidationError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(packet, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
