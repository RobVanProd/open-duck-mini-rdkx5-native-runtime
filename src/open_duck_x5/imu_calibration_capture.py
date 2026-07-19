from __future__ import annotations

import argparse
import hashlib
import json
import math
import pickle
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from . import imu_calibration as imu_calibration_module
from . import sensors as sensors_module
from .clock import clock_ns
from .config import ConfigError, DuckConfig
from .hardware_guard import (
    HardwareAuthorizationError,
    add_hardware_ack_arguments,
    require_hardware_authorization,
)
from .imu_calibration import (
    CALIBRATION_SCHEMA_VERSION,
    LEGACY_SOURCE_FORMAT,
    BNO055Calibration,
    CalibrationError,
    convert_legacy_calibration,
    sha256_file,
)
from .sensors import BNO055Smbus

CAPTURE_SCHEMA_VERSION = "open_duck_x5.bno055_calibration_capture.v1"
STATUS_SCHEMA_VERSION = "open_duck_x5.bno055_calibration_status.v1"
LEGACY_FILENAME = "imu_calib_data.pkl"
PROFILE_FILENAME = "imu_calibration.json"
STATUS_FILENAME = "calibration-status.jsonl"
SUMMARY_FILENAME = "calibration-summary.json"
MAX_TIMEOUT_SECONDS = 1800.0
MIN_POLL_SECONDS = 0.1
MAX_STATUS_RECORDS = 18_000


class CalibrationCaptureError(RuntimeError):
    pass


class CalibrationDevice(Protocol):
    def calibration_status(self) -> tuple[int, dict[str, int]]: ...

    def capture_calibration_offsets(self) -> dict[str, tuple[int, int, int]]: ...

    def describe(self) -> dict[str, object]: ...

    def close(self) -> None: ...


class MockCalibrationDevice:
    OFFSETS = {
        "offsets_accelerometer": (11, -22, 33),
        "offsets_gyroscope": (-44, 55, -66),
        "offsets_magnetometer": (77, -88, 99),
    }

    def __init__(self, *, upside_down: bool, calibration: BNO055Calibration | None) -> None:
        self.upside_down = bool(upside_down)
        self.calibration = calibration

    @staticmethod
    def calibration_status() -> tuple[int, dict[str, int]]:
        return 0xFF, {
            "system": 3,
            "gyroscope": 3,
            "accelerometer": 3,
            "magnetometer": 3,
        }

    @classmethod
    def capture_calibration_offsets(cls) -> dict[str, tuple[int, int, int]]:
        return dict(cls.OFFSETS)

    def describe(self) -> dict[str, object]:
        readback = (
            {name: list(values) for name, values in self.OFFSETS.items()}
            if self.calibration is not None
            else None
        )
        return {
            "chip_id": 0xA0,
            "operation_mode": 0x0C,
            "axis_map_config": 0x21,
            "axis_map_sign": 0x07 if self.upside_down else 0x04,
            "unit_selection": 0,
            "identity_verified": True,
            "upside_down": self.upside_down,
            "calibration_applied": self.calibration is not None,
            "calibration_readback_verified": self.calibration is not None,
            "calibration_readback": readback,
            "calibration_status_raw": 0xFF,
            "calibration_status": {
                "system": 3,
                "gyroscope": 3,
                "accelerometer": 3,
                "magnetometer": 3,
            },
        }

    @staticmethod
    def close() -> None:
        return None


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Guided, no-servo BNO055 calibration capture for the RDK-X5"
    )
    parser.add_argument("--backend", choices=("mock", "x5"), default="mock")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--imu-bus", type=int, default=5)
    parser.add_argument("--imu-address", type=lambda value: int(value, 0), default=0x28)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--poll-seconds", type=float, default=0.25)
    parser.add_argument("--stable-full-samples", type=int, default=5)
    parser.add_argument(
        "--manual-calibration-authorized",
        action="store_true",
        help="assert that Rob is present and authorized manual IMU positioning",
    )
    add_hardware_ack_arguments(parser)
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if args.imu_bus < 0:
        raise ValueError("--imu-bus must be nonnegative")
    if not 0 <= args.imu_address <= 0x7F:
        raise ValueError("--imu-address must be a 7-bit I2C address")
    if not math.isfinite(args.timeout_seconds) or not (
        1.0 <= args.timeout_seconds <= MAX_TIMEOUT_SECONDS
    ):
        raise ValueError(f"--timeout-seconds must be in 1..{MAX_TIMEOUT_SECONDS:g}")
    if not math.isfinite(args.poll_seconds) or not (MIN_POLL_SECONDS <= args.poll_seconds <= 5.0):
        raise ValueError(f"--poll-seconds must be in {MIN_POLL_SECONDS:g}..5")
    if not 2 <= args.stable_full_samples <= 100:
        raise ValueError("--stable-full-samples must be in 2..100")
    maximum_polls = math.ceil(args.timeout_seconds / args.poll_seconds) + 1
    if maximum_polls > MAX_STATUS_RECORDS:
        raise ValueError(f"calibration would exceed the {MAX_STATUS_RECORDS}-record evidence bound")
    output_dir = args.output_dir.expanduser().resolve()
    if output_dir.exists():
        raise ValueError(f"refusing existing --output-dir: {output_dir}")
    if args.backend == "x5":
        require_hardware_authorization(
            hardware_authorized=args.hardware_authorized,
            suspended_or_benched=args.suspended_or_benched,
            operation="manual no-servo BNO055 calibration",
        )
        if not args.manual_calibration_authorized:
            raise HardwareAuthorizationError(
                "manual BNO055 calibration is blocked: Rob must be physically present "
                "and pass --manual-calibration-authorized for this exact session"
            )


def _open_device(
    args: argparse.Namespace,
    config: DuckConfig,
    calibration: BNO055Calibration | None,
) -> CalibrationDevice:
    if args.backend == "mock":
        return MockCalibrationDevice(
            upside_down=config.imu_upside_down,
            calibration=calibration,
        )
    return BNO055Smbus(
        bus_number=args.imu_bus,
        address=args.imu_address,
        upside_down=config.imu_upside_down,
        calibration=calibration,
    )


def _calibration_from_offsets(
    offsets: dict[str, tuple[int, int, int]], source_sha256: str
) -> BNO055Calibration:
    return BNO055Calibration.from_mapping(
        {
            "schema_version": CALIBRATION_SCHEMA_VERSION,
            "source_format": LEGACY_SOURCE_FORMAT,
            "source_sha256": source_sha256,
            **offsets,
        }
    )


def _verify_diagnostics(
    diagnostics: dict[str, object],
    calibration: BNO055Calibration,
    *,
    upside_down: bool,
) -> None:
    expected = {
        "chip_id": 0xA0,
        "operation_mode": 0x0C,
        "axis_map_config": 0x21,
        "axis_map_sign": 0x07 if upside_down else 0x04,
        "unit_selection": 0,
        "identity_verified": True,
        "upside_down": upside_down,
        "calibration_applied": True,
        "calibration_readback_verified": True,
        "calibration_readback": {
            "offsets_accelerometer": list(calibration.offsets_accelerometer),
            "offsets_gyroscope": list(calibration.offsets_gyroscope),
            "offsets_magnetometer": list(calibration.offsets_magnetometer),
        },
    }
    for field, expected_value in expected.items():
        if diagnostics.get(field) != expected_value:
            raise CalibrationCaptureError(
                f"post-capture BNO055 verification failed for {field}: "
                f"expected {expected_value!r}, read {diagnostics.get(field)!r}"
            )


def _write_exclusive(path: Path, payload: bytes) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except OSError as exc:
        raise CalibrationCaptureError(f"cannot create calibration artifact {path}: {exc}") from exc


def run_capture(args: argparse.Namespace) -> dict[str, object]:
    _validate_args(args)
    config_path = args.config.expanduser().resolve()
    config = DuckConfig.load(config_path)
    output_dir = args.output_dir.expanduser().resolve()
    started_utc = _utc_now()
    started_ns = clock_ns()
    deadline_ns = started_ns + int(args.timeout_seconds * 1e9)
    status_records: list[dict[str, object]] = []
    full_samples = 0
    last_printed_raw = -1
    device = _open_device(args, config, None)
    try:
        print(
            "Calibration active: keep still for gyro, use multiple stable orientations "
            "for accelerometer, and rotate through all axes for magnetometer.",
            flush=True,
        )
        while True:
            sampled_ns = clock_ns()
            raw, decoded = device.calibration_status()
            record = {
                "schema_version": STATUS_SCHEMA_VERSION,
                "poll": len(status_records),
                "elapsed_seconds": (sampled_ns - started_ns) / 1e9,
                "status_raw": raw,
                **decoded,
            }
            status_records.append(record)
            if raw == 0xFF:
                full_samples += 1
            else:
                full_samples = 0
            if raw != last_printed_raw or len(status_records) % 20 == 0:
                print(
                    "Calibration status: "
                    + " ".join(f"{name}={value}" for name, value in decoded.items())
                    + f" stable_full={full_samples}/{args.stable_full_samples}",
                    flush=True,
                )
                last_printed_raw = raw
            if full_samples >= args.stable_full_samples:
                break
            if sampled_ns >= deadline_ns:
                raise CalibrationCaptureError(
                    "BNO055 did not sustain full 3/3/3/3 calibration before timeout"
                )
            time.sleep(args.poll_seconds)
        offsets = device.capture_calibration_offsets()
        initial_diagnostics = device.describe()
    finally:
        device.close()

    legacy_payload = pickle.dumps(offsets, protocol=4)
    legacy_sha256 = _sha256_bytes(legacy_payload)
    in_memory_calibration = _calibration_from_offsets(offsets, legacy_sha256)
    verification_device = _open_device(args, config, in_memory_calibration)
    try:
        verification_diagnostics = verification_device.describe()
        _verify_diagnostics(
            verification_diagnostics,
            in_memory_calibration,
            upside_down=config.imu_upside_down,
        )
    finally:
        verification_device.close()

    status_payload = "".join(
        json.dumps(record, separators=(",", ":")) + "\n" for record in status_records
    ).encode("utf-8")
    software_paths = {
        "capture": Path(__file__).resolve(),
        "sensors": Path(sensors_module.__file__).resolve(),
        "imu_calibration": Path(imu_calibration_module.__file__).resolve(),
    }
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.partial-",
            dir=output_dir.parent,
        )
    )
    legacy_path = staging_dir / LEGACY_FILENAME
    profile_path = staging_dir / PROFILE_FILENAME
    status_path = staging_dir / STATUS_FILENAME
    summary_path = staging_dir / SUMMARY_FILENAME
    try:
        _write_exclusive(legacy_path, legacy_payload)
        calibration = convert_legacy_calibration(legacy_path, profile_path)
        _write_exclusive(status_path, status_payload)
        completed_utc = _utc_now()
        summary: dict[str, object] = {
            "schema_version": CAPTURE_SCHEMA_VERSION,
            "backend": args.backend,
            "informational_only": args.backend == "mock",
            "hardware_status": (
                "NOT_APPLICABLE_MOCK" if args.backend == "mock" else "REVIEW_REQUIRED"
            ),
            "run_status": "COMPLETE",
            "review_status": "REVIEW_REQUIRED",
            "started_utc": started_utc,
            "completed_utc": completed_utc,
            "config": {
                "path": str(config_path),
                "sha256": sha256_file(config_path),
                "imu_upside_down": config.imu_upside_down,
            },
            "environment": {
                "imu_i2c_device": f"/dev/i2c-{args.imu_bus}",
                "imu_address": args.imu_address,
                "timeout_seconds": args.timeout_seconds,
                "poll_seconds": args.poll_seconds,
                "stable_full_samples_required": args.stable_full_samples,
                "hardware_authorized": bool(args.hardware_authorized),
                "suspended_or_benched": bool(args.suspended_or_benched),
                "manual_calibration_authorized": bool(args.manual_calibration_authorized),
                "servo_bus_accessed": False,
                "torque_enabled": False,
                "goal_position_writes": 0,
                "policy_loaded": False,
                "policy_inference_count": 0,
            },
            "calibration": {
                "final_status_raw": int(status_records[-1]["status_raw"]),
                "stable_full_samples": full_samples,
                "polls": len(status_records),
                "elapsed_seconds": float(status_records[-1]["elapsed_seconds"]),
                "offsets": {name: list(values) for name, values in offsets.items()},
                "initial_device": initial_diagnostics,
                "post_profile_readback": verification_diagnostics,
            },
            "artifacts": {
                "legacy_pickle": {
                    "path": LEGACY_FILENAME,
                    "sha256": sha256_file(legacy_path),
                },
                "profile": {
                    "path": PROFILE_FILENAME,
                    "sha256": calibration.profile_sha256,
                    "source_sha256": calibration.source_sha256,
                },
                "status_jsonl": {
                    "path": STATUS_FILENAME,
                    "sha256": sha256_file(status_path),
                    "records": len(status_records),
                },
            },
            "software": {
                name: {"path": str(path), "sha256": sha256_file(path)}
                for name, path in software_paths.items()
            },
            "checks": {
                "full_calibration_sustained": full_samples >= args.stable_full_samples,
                "profile_source_matches_legacy": calibration.source_sha256
                == sha256_file(legacy_path),
                "exact_offset_readback": True,
                "identity_and_frozen_mapping_verified": True,
                "authorization_provenance": args.backend == "mock"
                or (
                    args.hardware_authorized
                    and args.suspended_or_benched
                    and args.manual_calibration_authorized
                ),
                "profile_candidate": args.backend == "x5",
            },
        }
        summary_payload = (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode("utf-8")
        _write_exclusive(summary_path, summary_payload)
        staging_dir.rename(output_dir)
    except BaseException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        summary = run_capture(args)
    except KeyboardInterrupt:
        print("calibration interrupted; no profile was accepted", file=sys.stderr)
        return 130
    except (
        CalibrationCaptureError,
        CalibrationError,
        ConfigError,
        HardwareAuthorizationError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        parser.error(str(exc))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
