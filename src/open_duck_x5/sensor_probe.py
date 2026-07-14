from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
from pathlib import Path

import numpy as np

from .clock import clock_ns
from .config import ConfigError, DuckConfig
from .hardware_guard import (
    HardwareAuthorizationError,
    add_hardware_ack_arguments,
    require_hardware_authorization,
)
from .sensors import BNO055Smbus, MockSensorHub, SensorHub, SensorReadout, X5FootContacts
from .timing import AbsoluteTicker

SENSOR_LABELS = (
    "upright",
    "nose_forward",
    "nose_back",
    "left_tilt",
    "right_tilt",
    "no_contacts",
    "left_contact",
    "right_contact",
    "both_contacts",
)
MAX_SAMPLES = 100_000


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect labeled, no-motion X5 IMU/contact evidence"
    )
    parser.add_argument("--backend", choices=("mock", "x5"), default="mock")
    parser.add_argument("--label", choices=SENSOR_LABELS, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=250)
    parser.add_argument("--frequency-hz", type=float, default=50.0)
    parser.add_argument("--sensor-frequency-hz", type=float, default=100.0)
    parser.add_argument("--stale-after-ms", type=float, default=40.0)
    parser.add_argument("--imu-bus", type=int, default=5)
    parser.add_argument("--imu-address", type=lambda value: int(value, 0), default=0x28)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    add_hardware_ack_arguments(parser)
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stats(values: np.ndarray, *, scale: float = 1.0) -> dict[str, float]:
    scaled = values.astype(np.float64) * scale
    return {
        "min": float(np.min(scaled)),
        "mean": float(np.mean(scaled)),
        "p95": float(np.percentile(scaled, 95)),
        "max": float(np.max(scaled)),
    }


def _axis_stats(values: np.ndarray) -> dict[str, dict[str, float]]:
    return {
        axis: _stats(values[:, index]) for index, axis in enumerate(("x", "y", "z"))
    }


def _validate_args(args: argparse.Namespace) -> None:
    if not 2 <= args.samples <= MAX_SAMPLES:
        raise ValueError(f"--samples must be in 2..{MAX_SAMPLES}")
    for name in ("frequency_hz", "sensor_frequency_hz", "stale_after_ms"):
        value = float(getattr(args, name))
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"--{name.replace('_', '-')} must be finite and positive")
    if args.imu_bus < 0:
        raise ValueError("--imu-bus must be nonnegative")
    if not 0 <= args.imu_address <= 0x7F:
        raise ValueError("--imu-address must be a 7-bit I2C address")
    if args.output.resolve() == args.summary.resolve():
        raise ValueError("--output and --summary must be different files")
    config_path = args.config.expanduser().resolve()
    if args.output.expanduser().resolve() == config_path:
        raise ValueError("--output must not overwrite --config")
    if args.summary.expanduser().resolve() == config_path:
        raise ValueError("--summary must not overwrite --config")


def _create_hub(args: argparse.Namespace, config: DuckConfig):
    if args.backend == "mock":
        return MockSensorHub()
    require_hardware_authorization(
        hardware_authorized=args.hardware_authorized,
        suspended_or_benched=args.suspended_or_benched,
        operation=f"labeled X5 sensor probe ({args.label})",
    )
    contacts = X5FootContacts()
    try:
        imu = BNO055Smbus(
            bus_number=args.imu_bus,
            address=args.imu_address,
            upside_down=config.imu_upside_down,
        )
    except BaseException:
        contacts.close()
        raise
    return SensorHub(
        imu,
        contacts,
        sample_frequency_hz=args.sensor_frequency_hz,
        stale_after_s=args.stale_after_ms / 1000.0,
    )


def run_probe(args: argparse.Namespace) -> dict[str, object]:
    _validate_args(args)
    config_path = args.config.expanduser().resolve()
    config = DuckConfig.load(config_path)
    hub = _create_hub(args, config)
    samples = args.samples
    tick_start_ns = np.zeros(samples, dtype=np.int64)
    tick_period_ns = np.zeros(samples, dtype=np.int64)
    release_lateness_ns = np.zeros(samples, dtype=np.int64)
    gyro = np.zeros((samples, 3), dtype=np.float64)
    acceleration = np.zeros((samples, 3), dtype=np.float64)
    contacts = np.zeros((samples, 2), dtype=np.float32)
    imu_timestamp_ns = np.zeros(samples, dtype=np.int64)
    contacts_timestamp_ns = np.zeros(samples, dtype=np.int64)
    imu_age_ns = np.zeros(samples, dtype=np.int64)
    contacts_age_ns = np.zeros(samples, dtype=np.int64)
    imu_stale = np.ones(samples, dtype=np.bool_)
    contacts_stale = np.ones(samples, dtype=np.bool_)
    readout = SensorReadout()
    previous_tick_ns = 0
    completed = 0
    try:
        ticker = AbsoluteTicker(period_ns=int(1e9 / args.frequency_hz))
        for index in range(samples):
            started_ns, lateness_ns = ticker.wait()
            now_ns = clock_ns()
            hub.read_into(readout, now_ns)
            tick_start_ns[index] = started_ns
            tick_period_ns[index] = started_ns - previous_tick_ns if previous_tick_ns else 0
            previous_tick_ns = started_ns
            release_lateness_ns[index] = lateness_ns
            np.copyto(gyro[index], readout.gyro_rad_s)
            np.copyto(acceleration[index], readout.acceleration_m_s2)
            np.copyto(contacts[index], readout.contacts)
            imu_timestamp_ns[index] = readout.imu_timestamp_ns
            contacts_timestamp_ns[index] = readout.contacts_timestamp_ns
            imu_age_ns[index] = readout.imu_age_ns
            contacts_age_ns[index] = readout.contacts_age_ns
            imu_stale[index] = readout.imu_stale
            contacts_stale[index] = readout.contacts_stale
            completed = index + 1
    finally:
        hub.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for index in range(completed):
            record = {
                "schema_version": "open_duck_x5.sensor_tick.v1",
                "sample": index,
                "label": args.label,
                "timestamp_monotonic_ns": int(tick_start_ns[index]),
                "tick_period_ms": (
                    float(tick_period_ns[index]) / 1e6 if tick_period_ns[index] else None
                ),
                "release_lateness_ms": float(release_lateness_ns[index]) / 1e6,
                "imu": {
                    "sample_timestamp_ns": int(imu_timestamp_ns[index]),
                    "age_ms": float(imu_age_ns[index]) / 1e6,
                    "stale": bool(imu_stale[index]),
                    "gyro_rad_s": gyro[index].tolist(),
                    "acceleration_m_s2": acceleration[index].tolist(),
                },
                "contacts": {
                    "sample_timestamp_ns": int(contacts_timestamp_ns[index]),
                    "age_ms": float(contacts_age_ns[index]) / 1e6,
                    "stale": bool(contacts_stale[index]),
                    "left": float(contacts[index, 0]),
                    "right": float(contacts[index, 1]),
                },
            }
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")

    imu_stale_count = int(np.count_nonzero(imu_stale[:completed]))
    contacts_stale_count = int(np.count_nonzero(contacts_stale[:completed]))
    imu_timestamp_repeats = int(np.count_nonzero(np.diff(imu_timestamp_ns[:completed]) <= 0))
    contact_timestamp_repeats = int(
        np.count_nonzero(np.diff(contacts_timestamp_ns[:completed]) <= 0)
    )
    summary: dict[str, object] = {
        "schema_version": "open_duck_x5.sensor_summary.v1",
        "backend": args.backend,
        "informational_only": args.backend == "mock",
        "run_status": "COMPLETE",
        "review_status": "REVIEW_REQUIRED",
        "label": args.label,
        "samples": completed,
        "samples_requested": samples,
        "config": {
            "path": str(config_path),
            "sha256": _sha256(config_path),
            "imu_upside_down": config.imu_upside_down,
        },
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "frequency_hz": args.frequency_hz,
            "sensor_frequency_hz": args.sensor_frequency_hz,
            "stale_after_ms": args.stale_after_ms,
            "imu_bus": args.imu_bus,
            "imu_address": args.imu_address,
            "servo_bus_accessed": False,
            "torque_enabled": False,
            "goal_position_writes": 0,
        },
        "timing": {
            "tick_period_ms": _stats(tick_period_ns[1:completed], scale=1e-6),
            "release_lateness_ms": _stats(
                release_lateness_ns[:completed], scale=1e-6
            ),
        },
        "imu": {
            "gyro_rad_s": _axis_stats(gyro[:completed]),
            "acceleration_m_s2": _axis_stats(acceleration[:completed]),
            "age_ms": _stats(imu_age_ns[:completed], scale=1e-6),
            "stale_count": imu_stale_count,
            "stale_rate": imu_stale_count / completed,
            "nonincreasing_timestamp_count": imu_timestamp_repeats,
        },
        "contacts": {
            "left_mean": float(np.mean(contacts[:completed, 0])),
            "right_mean": float(np.mean(contacts[:completed, 1])),
            "left_true_count": int(np.count_nonzero(contacts[:completed, 0] >= 0.5)),
            "right_true_count": int(np.count_nonzero(contacts[:completed, 1] >= 0.5)),
            "age_ms": _stats(contacts_age_ns[:completed], scale=1e-6),
            "stale_count": contacts_stale_count,
            "stale_rate": contacts_stale_count / completed,
            "nonincreasing_timestamp_count": contact_timestamp_repeats,
            "frozen_polarity": "raw GPIO false -> contact true",
        },
        "checks": {
            "zero_imu_stale": imu_stale_count == 0,
            "zero_contacts_stale": contacts_stale_count == 0,
            "strictly_increasing_imu_timestamps": imu_timestamp_repeats == 0,
            "strictly_increasing_contact_timestamps": contact_timestamp_repeats == 0,
            "orientation_and_contact_label_match": "REVIEW_REQUIRED",
        },
        "jsonl_sha256": _sha256(args.output),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_bytes(
        (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        summary = run_probe(args)
    except (
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
