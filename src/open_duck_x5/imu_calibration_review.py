from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from . import imu_calibration as imu_calibration_module
from . import imu_calibration_capture as capture_module
from . import sensors as sensors_module
from .imu_calibration import (
    BNO055Calibration,
    CalibrationError,
    load_legacy_calibration,
    sha256_file,
)

REVIEW_SCHEMA_VERSION = "open_duck_x5.bno055_calibration_review.v1"
EXPECTED_CONFIG_SHA256 = "131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b"
EXPECTED_CAPTURE_SOURCE_COMMIT = "4e9b748139a65449a71e6c58ec2401f0a90d42bd"
EXPECTED_CAPTURE_ARCHIVE_SHA256 = "7e8189501dbb24ecf0301b86e5c7d787e095aad24a634a3a599b7e5d8cd864cb"
EXPECTED_CAPTURE_SOFTWARE_SHA256 = {
    "capture": "a87655c66dc10164a493b6bc977fdb2a4f69fa030d52ec80bed88766c9969447",
    "sensors": "77867106e49ec0c6104152981c8a1a8a69238e5bf358c67b081cb4ac1f40acb3",
    "imu_calibration": "193851d96615996df8a7d906a14aee52491197eebdd4fe237051918bb5988d5d",
}
EXPECTED_TIMEOUT_SECONDS = 600.0
EXPECTED_POLL_SECONDS = 0.25
EXPECTED_STABLE_FULL_SAMPLES = 5
MAX_SUMMARY_BYTES = 1024 * 1024
MAX_STATUS_BYTES = 8 * 1024 * 1024
CAPTURE_FILENAMES = (
    capture_module.LEGACY_FILENAME,
    capture_module.PROFILE_FILENAME,
    capture_module.STATUS_FILENAME,
    capture_module.SUMMARY_FILENAME,
)


class CalibrationReviewError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CalibrationReviewError(message)


def _load_json(path: Path, *, maximum_bytes: int) -> dict[str, Any]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise CalibrationReviewError(f"cannot stat {path}: {exc}") from exc
    _require(1 <= size <= maximum_bytes, f"invalid evidence file size for {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CalibrationReviewError(f"cannot read JSON {path}: {exc}") from exc
    _require(isinstance(value, dict), f"JSON root must be an object: {path}")
    return value


def _mapping(value: object, field: str) -> dict[str, Any]:
    _require(isinstance(value, dict), f"{field} must be an object")
    return value


def _finite_number(value: object, field: str) -> float:
    _require(
        isinstance(value, (int, float)) and not isinstance(value, bool),
        f"{field} must be numeric",
    )
    number = float(value)
    _require(math.isfinite(number), f"{field} must be finite")
    return number


def _review_software() -> dict[str, str]:
    paths = {
        "review": Path(__file__).resolve(),
        "capture": Path(capture_module.__file__).resolve(),
        "sensors": Path(sensors_module.__file__).resolve(),
        "imu_calibration": Path(imu_calibration_module.__file__).resolve(),
    }
    return {name: sha256_file(path) for name, path in paths.items()}


def _offsets(calibration: BNO055Calibration) -> dict[str, list[int]]:
    return {
        "offsets_accelerometer": list(calibration.offsets_accelerometer),
        "offsets_gyroscope": list(calibration.offsets_gyroscope),
        "offsets_magnetometer": list(calibration.offsets_magnetometer),
    }


def _validate_device(
    value: object,
    *,
    field: str,
    calibration: BNO055Calibration,
    calibration_applied: bool,
) -> None:
    device = _mapping(value, field)
    expected = {
        "chip_id": 0xA0,
        "operation_mode": 0x0C,
        "axis_map_config": 0x21,
        "axis_map_sign": 0x07,
        "unit_selection": 0,
        "identity_verified": True,
        "upside_down": True,
        "calibration_applied": calibration_applied,
        "calibration_readback_verified": calibration_applied,
        "calibration_readback": _offsets(calibration) if calibration_applied else None,
    }
    for name, expected_value in expected.items():
        _require(
            device.get(name) == expected_value,
            f"{field}.{name} mismatch: expected {expected_value!r}",
        )
    if not calibration_applied:
        _require(
            device.get("calibration_status_raw") == 0xFF,
            f"{field} did not preserve the accepted full-calibration status",
        )


def _load_status_rows(path: Path) -> list[dict[str, Any]]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise CalibrationReviewError(f"cannot stat {path}: {exc}") from exc
    _require(1 <= size <= MAX_STATUS_BYTES, f"invalid status JSONL size for {path}")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise CalibrationReviewError(f"cannot read status JSONL {path}: {exc}") from exc
    _require(2 <= len(lines) <= capture_module.MAX_STATUS_RECORDS, "bad status row count")
    rows: list[dict[str, Any]] = []
    previous_elapsed = -1.0
    expected_keys = {
        "schema_version",
        "poll",
        "elapsed_seconds",
        "status_raw",
        "system",
        "gyroscope",
        "accelerometer",
        "magnetometer",
    }
    for index, line in enumerate(lines):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CalibrationReviewError(f"invalid status row {index}: {exc}") from exc
        _require(isinstance(row, dict), f"status row {index} is not an object")
        _require(set(row) == expected_keys, f"status row {index} has wrong fields")
        _require(
            row["schema_version"] == capture_module.STATUS_SCHEMA_VERSION,
            f"status row {index} has wrong schema",
        )
        _require(row["poll"] == index, f"status row {index} has wrong poll index")
        elapsed = _finite_number(row["elapsed_seconds"], f"status row {index} elapsed")
        _require(elapsed >= previous_elapsed, f"status elapsed time decreased at row {index}")
        previous_elapsed = elapsed
        raw = row["status_raw"]
        _require(isinstance(raw, int) and 0 <= raw <= 0xFF, f"bad status byte at row {index}")
        decoded = {
            "system": (raw >> 6) & 0x03,
            "gyroscope": (raw >> 4) & 0x03,
            "accelerometer": (raw >> 2) & 0x03,
            "magnetometer": raw & 0x03,
        }
        for name, expected in decoded.items():
            _require(row[name] == expected, f"status decode mismatch at row {index}: {name}")
        rows.append(row)
    return rows


def verify_calibration_capture(
    capture_dir: Path,
    *,
    expected_config_sha256: str = EXPECTED_CONFIG_SHA256,
    expected_capture_software_sha256: dict[str, str] | None = None,
) -> dict[str, object]:
    capture_dir = capture_dir.expanduser().resolve()
    _require(capture_dir.is_dir(), f"calibration capture is not a directory: {capture_dir}")
    entries = {path.name for path in capture_dir.iterdir()}
    _require(entries == set(CAPTURE_FILENAMES), "calibration capture has missing or extra files")
    paths = {name: capture_dir / name for name in CAPTURE_FILENAMES}
    for name, path in paths.items():
        _require(path.is_file() and not path.is_symlink(), f"invalid capture file: {name}")

    legacy = load_legacy_calibration(paths[capture_module.LEGACY_FILENAME])
    profile = BNO055Calibration.load(paths[capture_module.PROFILE_FILENAME])
    _require(profile.source_sha256 == legacy.source_sha256, "profile source hash mismatch")
    _require(_offsets(profile) == _offsets(legacy), "profile offsets differ from legacy source")
    rows = _load_status_rows(paths[capture_module.STATUS_FILENAME])
    summary = _load_json(paths[capture_module.SUMMARY_FILENAME], maximum_bytes=MAX_SUMMARY_BYTES)

    expected_scalars = {
        "schema_version": capture_module.CAPTURE_SCHEMA_VERSION,
        "backend": "x5",
        "informational_only": False,
        "hardware_status": "REVIEW_REQUIRED",
        "run_status": "COMPLETE",
        "review_status": "REVIEW_REQUIRED",
    }
    for field, expected in expected_scalars.items():
        _require(summary.get(field) == expected, f"bad calibration summary field: {field}")

    config = _mapping(summary.get("config"), "config")
    _require(config.get("sha256") == expected_config_sha256, "config hash mismatch")
    _require(config.get("imu_upside_down") is True, "imu_upside_down must remain true")

    environment = _mapping(summary.get("environment"), "environment")
    expected_environment = {
        "imu_i2c_device": "/dev/i2c-5",
        "imu_address": 0x28,
        "timeout_seconds": EXPECTED_TIMEOUT_SECONDS,
        "poll_seconds": EXPECTED_POLL_SECONDS,
        "stable_full_samples_required": EXPECTED_STABLE_FULL_SAMPLES,
        "hardware_authorized": True,
        "suspended_or_benched": True,
        "manual_calibration_authorized": True,
        "servo_bus_accessed": False,
        "torque_enabled": False,
        "goal_position_writes": 0,
        "policy_loaded": False,
        "policy_inference_count": 0,
    }
    for field, expected in expected_environment.items():
        _require(environment.get(field) == expected, f"bad calibration environment: {field}")

    calibration = _mapping(summary.get("calibration"), "calibration")
    _require(calibration.get("final_status_raw") == 0xFF, "final calibration status is not full")
    _require(
        calibration.get("stable_full_samples") == EXPECTED_STABLE_FULL_SAMPLES,
        "wrong sustained full-calibration population",
    )
    _require(calibration.get("polls") == len(rows), "status row count mismatch")
    _require(calibration.get("offsets") == _offsets(profile), "summary offsets mismatch")
    _validate_device(
        calibration.get("initial_device"),
        field="calibration.initial_device",
        calibration=profile,
        calibration_applied=False,
    )
    _validate_device(
        calibration.get("post_profile_readback"),
        field="calibration.post_profile_readback",
        calibration=profile,
        calibration_applied=True,
    )
    _require(
        all(row["status_raw"] == 0xFF for row in rows[-EXPECTED_STABLE_FULL_SAMPLES:]),
        "status stream does not end with the preregistered full-calibration run",
    )

    artifacts = _mapping(summary.get("artifacts"), "artifacts")
    expected_artifacts = {
        "legacy_pickle": (
            capture_module.LEGACY_FILENAME,
            sha256_file(paths[capture_module.LEGACY_FILENAME]),
        ),
        "profile": (
            capture_module.PROFILE_FILENAME,
            sha256_file(paths[capture_module.PROFILE_FILENAME]),
        ),
        "status_jsonl": (
            capture_module.STATUS_FILENAME,
            sha256_file(paths[capture_module.STATUS_FILENAME]),
        ),
    }
    for name, (expected_path, expected_hash) in expected_artifacts.items():
        artifact = _mapping(artifacts.get(name), f"artifacts.{name}")
        _require(artifact.get("path") == expected_path, f"bad artifact path: {name}")
        _require(artifact.get("sha256") == expected_hash, f"bad artifact hash: {name}")
    _require(
        _mapping(artifacts.get("profile"), "artifacts.profile").get("source_sha256")
        == legacy.source_sha256,
        "profile artifact source hash mismatch",
    )
    _require(
        _mapping(artifacts.get("status_jsonl"), "artifacts.status_jsonl").get("records")
        == len(rows),
        "status artifact row count mismatch",
    )

    expected_capture_software = (
        EXPECTED_CAPTURE_SOFTWARE_SHA256
        if expected_capture_software_sha256 is None
        else expected_capture_software_sha256
    )
    _require(
        set(expected_capture_software) == set(EXPECTED_CAPTURE_SOFTWARE_SHA256),
        "invalid expected capture software population",
    )
    software = _mapping(summary.get("software"), "software")
    _require(
        set(software) == set(expected_capture_software),
        "wrong software provenance fields",
    )
    for name, expected_sha256 in expected_capture_software.items():
        actual = _mapping(software.get(name), f"software.{name}")
        _require(actual.get("sha256") == expected_sha256, f"source hash mismatch: {name}")

    checks = _mapping(summary.get("checks"), "checks")
    for name in (
        "full_calibration_sustained",
        "profile_source_matches_legacy",
        "exact_offset_readback",
        "identity_and_frozen_mapping_verified",
        "authorization_provenance",
        "profile_candidate",
    ):
        _require(checks.get(name) is True, f"calibration check did not pass: {name}")

    raw_artifacts = [
        {"path": name, "sha256": sha256_file(path)} for name, path in sorted(paths.items())
    ]
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "status": "REVIEW_REQUIRED",
        "data_integrity_candidate": True,
        "physical_calibration_decision": "REVIEW_REQUIRED",
        "capture_source_commit": EXPECTED_CAPTURE_SOURCE_COMMIT,
        "capture_archive_sha256": EXPECTED_CAPTURE_ARCHIVE_SHA256,
        "config_sha256": expected_config_sha256,
        "offsets": _offsets(profile),
        "calibration_profile_sha256": profile.profile_sha256,
        "calibration_source_sha256": legacy.source_sha256,
        "status_rows": len(rows),
        "stable_full_samples": EXPECTED_STABLE_FULL_SAMPLES,
        "capture_software_sha256": dict(expected_capture_software),
        "review_software_sha256": _review_software(),
        "raw_artifacts": raw_artifacts,
        "checks": {
            "exact_capture_population": True,
            "config_contract_verified": True,
            "authorization_provenance_verified": True,
            "status_stream_rederived": True,
            "legacy_source_restricted_and_hashed": True,
            "profile_matches_legacy": True,
            "exact_device_readback_verified": True,
            "software_provenance_verified": True,
            "no_servo_or_policy_access_verified": True,
        },
        "review_instructions": [
            "Confirm Rob performed the calibration while physically supporting the robot.",
            "Confirm the final five status samples are 3/3/3/3 and offsets are "
            "plausible for this unit.",
            "Keep Gate 3 blocked until this packet and the raw capture are reviewed and hashed.",
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Independently verify a no-servo BNO055 calibration capture"
    )
    parser.add_argument("--capture-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--expected-config-sha256",
        default=EXPECTED_CONFIG_SHA256,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    output = args.output.expanduser().resolve()
    if output.exists():
        parser.error(f"refusing to overwrite review packet: {output}")
    try:
        packet = verify_calibration_capture(
            args.capture_dir,
            expected_config_sha256=args.expected_config_sha256,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(packet, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except (CalibrationError, CalibrationReviewError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(packet, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
