from __future__ import annotations

import argparse
import json
import math
import platform
import sys
from pathlib import Path

from .bus import MockSTS3215Bus, ServoSnapshot, STS3215Bus
from .constants import CONTROL_FREQUENCY_HZ, HOME_RAD
from .hardware_guard import (
    HardwareAuthorizationError,
    add_hardware_ack_arguments,
    require_hardware_authorization,
)
from .telemetry import AsyncProbeWriter
from .timing import AbsoluteTicker, TimingSeries


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure per-tick servo transaction timing")
    parser.add_argument("--bus", choices=("mock", "serial"), default="mock")
    parser.add_argument("--device", default="/dev/ttyACM0")
    parser.add_argument("--baudrate", type=int, default=1_000_000)
    parser.add_argument("--timeout-ms", type=float, default=4.0)
    parser.add_argument("--ticks", type=int, default=1000)
    parser.add_argument("--frequency-hz", type=float, default=CONTROL_FREQUENCY_HZ)
    parser.add_argument("--sine-hz", type=float, default=0.5)
    parser.add_argument("--amplitude-rad", type=float, default=0.03)
    parser.add_argument("--mock-latency-ms", type=float, default=0.8)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    add_hardware_ack_arguments(parser)
    return parser


def run_probe(args: argparse.Namespace) -> dict[str, object]:
    if args.ticks < 2:
        raise ValueError("--ticks must be at least 2")
    if args.frequency_hz <= 0:
        raise ValueError("--frequency-hz must be positive")
    if args.bus == "serial":
        require_hardware_authorization(
            hardware_authorized=args.hardware_authorized,
            suspended_or_benched=args.suspended_or_benched,
            operation="serial timing probe",
        )
        bus = STS3215Bus(
            args.device,
            baudrate=args.baudrate,
            transaction_timeout_s=args.timeout_ms / 1000.0,
        )
        informational_only = False
    else:
        bus = MockSTS3215Bus(latency_s=args.mock_latency_ms / 1000.0)
        informational_only = True

    snapshot = ServoSnapshot.create()
    targets = HOME_RAD.copy()
    series = TimingSeries(args.ticks)
    writer = AsyncProbeWriter(args.output, capacity=min(max(args.ticks, 64), 4096))
    ticker = AbsoluteTicker(period_ns=int(1e9 / args.frequency_hz))
    previous_tick_start_ns = 0
    try:
        for tick in range(args.ticks):
            tick_start_ns, lateness_ns = ticker.wait()
            phase = 2.0 * math.pi * args.sine_hz * tick / args.frequency_hz
            targets[:] = HOME_RAD
            targets[0] += args.amplitude_rad * math.sin(phase)
            bus.exchange_into(targets, snapshot, tick)
            tick_period_ns = (
                tick_start_ns - previous_tick_start_ns if previous_tick_start_ns else 0
            )
            previous_tick_start_ns = tick_start_ns
            series.append(tick_start_ns, lateness_ns, snapshot)
            writer.publish(
                tick,
                tick_start_ns,
                tick_period_ns,
                lateness_ns,
                snapshot,
            )
    finally:
        try:
            bus.disable_torque()
        finally:
            bus.close()
            writer.close()

    summary = series.summary(backend=args.bus, informational_only=informational_only)
    summary["environment"] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "device": bus.device,
        "baudrate": bus.baudrate,
        "frequency_hz": args.frequency_hz,
        "timeout_ms": args.timeout_ms,
        "telemetry_records_dropped": writer.dropped,
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    summary_bytes = (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode("utf-8")
    args.summary.write_bytes(summary_bytes)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        summary = run_probe(args)
    except (HardwareAuthorizationError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
