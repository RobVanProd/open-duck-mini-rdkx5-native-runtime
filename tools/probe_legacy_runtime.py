from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

from open_duck_x5.clock import clock_ns
from open_duck_x5.constants import HOME_RAD, JOINT_NAMES
from open_duck_x5.hardware_guard import (
    add_hardware_ack_arguments,
    require_hardware_authorization,
)
from open_duck_x5.timing import AbsoluteTicker


def classify(message: str | None) -> str | None:
    if not message:
        return None
    lowered = message.lower()
    if "crc" in lowered or "checksum" in lowered:
        return "crc"
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout"
    if "partial" in lowered or "short" in lowered:
        return "partial"
    return "io"


def stats_ns(values: np.ndarray) -> dict[str, float]:
    ms = values.astype(np.float64) / 1e6
    return {
        "min": float(np.min(ms)),
        "mean": float(np.mean(ms)),
        "p95": float(np.percentile(ms, 95)),
        "p99": float(np.percentile(ms, 99)),
        "p99_9": float(np.percentile(ms, 99.9)),
        "max": float(np.max(ms)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Authorized baseline probe through the preserved rustypot HWI"
    )
    parser.add_argument("--legacy-runtime", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--device", default="/dev/ttyACM0")
    parser.add_argument("--ticks", type=int, default=1000)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--sine-hz", type=float, default=0.5)
    parser.add_argument("--amplitude-rad", type=float, default=0.03)
    add_hardware_ack_arguments(parser)
    args = parser.parse_args()
    require_hardware_authorization(
        hardware_authorized=args.hardware_authorized,
        suspended_or_benched=args.suspended_or_benched,
        operation="legacy rustypot baseline probe",
    )
    if args.ticks < 2:
        parser.error("--ticks must be at least 2")

    package_root = args.legacy_runtime / "mini_bdx_runtime"
    sys.path.insert(0, str(package_root))
    from mini_bdx_runtime.duck_config import DuckConfig as LegacyDuckConfig
    from mini_bdx_runtime.rustypot_position_hwi import HWI

    config = LegacyDuckConfig(config_json_path=str(args.config))
    hwi = HWI(config, args.device)
    tick_period = np.zeros(args.ticks, dtype=np.int64)
    total = np.zeros(args.ticks, dtype=np.int64)
    position_time = np.zeros(args.ticks, dtype=np.int64)
    velocity_time = np.zeros(args.ticks, dtype=np.int64)
    write_time = np.zeros(args.ticks, dtype=np.int64)
    positions_ok = np.zeros(args.ticks, dtype=np.bool_)
    velocities_ok = np.zeros(args.ticks, dtype=np.bool_)
    read_retry_delta = np.zeros(args.ticks, dtype=np.int32)
    write_retry_delta = np.zeros(args.ticks, dtype=np.int32)
    error_classes: list[str | None] = [None] * args.ticks
    target = HOME_RAD.copy()
    ticker = AbsoluteTicker()
    previous_start = 0
    try:
        for tick in range(args.ticks):
            start_ns, _ = ticker.wait()
            tick_period[tick] = start_ns - previous_start if previous_start else 0
            previous_start = start_ns
            read_before = int(getattr(hwi, "read_error_count", 0))
            write_before = int(getattr(hwi, "write_error_count", 0))

            op_start = clock_ns()
            pos = hwi.get_present_positions()
            position_time[tick] = clock_ns() - op_start
            positions_ok[tick] = pos is not None

            op_start = clock_ns()
            vel = hwi.get_present_velocities()
            velocity_time[tick] = clock_ns() - op_start
            velocities_ok[tick] = vel is not None

            phase = 2.0 * math.pi * args.sine_hz * tick / 50.0
            target[:] = HOME_RAD
            target[0] += args.amplitude_rad * math.sin(phase)
            op_start = clock_ns()
            hwi.set_position_all(dict(zip(JOINT_NAMES, target, strict=True)))
            write_time[tick] = clock_ns() - op_start
            total[tick] = clock_ns() - start_ns
            read_retry_delta[tick] = int(getattr(hwi, "read_error_count", 0)) - read_before
            write_retry_delta[tick] = int(getattr(hwi, "write_error_count", 0)) - write_before
            error_classes[tick] = classify(getattr(hwi, "last_error", None))
    finally:
        hwi.turn_off()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for tick in range(args.ticks):
            record = {
                "schema_version": "open_duck_x5.legacy_timing_tick.v1",
                "tick": tick,
                "tick_period_ms": tick_period[tick] / 1e6 if tick else None,
                "position_read_ms": position_time[tick] / 1e6,
                "velocity_read_ms": velocity_time[tick] / 1e6,
                "write_ms": write_time[tick] / 1e6,
                "transaction_loop_ms": total[tick] / 1e6,
                "positions_ok": bool(positions_ok[tick]),
                "velocities_ok": bool(velocities_ok[tick]),
                "read_retry_error_delta": int(read_retry_delta[tick]),
                "write_retry_error_delta": int(write_retry_delta[tick]),
                "last_error_class": error_classes[tick],
            }
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")

    failed_read_ticks = int(np.count_nonzero(~positions_ok | ~velocities_ok))
    retry_read_ticks = int(np.count_nonzero(read_retry_delta))
    summary = {
        "schema_version": "open_duck_x5.legacy_timing_summary.v1",
        "status": "HARDWARE_RESULT",
        "ticks": args.ticks,
        "tick_period_ms": stats_ns(tick_period[1:]),
        "position_read_ms": stats_ns(position_time),
        "velocity_read_ms": stats_ns(velocity_time),
        "write_ms": stats_ns(write_time),
        "transaction_loop_ms": stats_ns(total),
        "failed_read_ticks": failed_read_ticks,
        "ticks_with_read_retry_errors": retry_read_ticks,
        "read_retry_error_count": int(read_retry_delta.sum()),
        "write_retry_error_count": int(write_retry_delta.sum()),
        "note": (
            "The legacy wrapper collapses low-level taxonomy; class is inferred "
            "from its last error string."
        ),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    summary_bytes = (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode("utf-8")
    args.summary.write_bytes(summary_bytes)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
