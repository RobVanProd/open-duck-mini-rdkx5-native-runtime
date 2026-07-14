from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
from pathlib import Path

import numpy as np

from .bus import ErrorCode, MockSTS3215Bus, ServoSnapshot, STS3215Bus
from .clock import clock_ns
from .config import DuckConfig
from .constants import CONTROL_FREQUENCY_HZ, HOME_RAD, JOINT_NAMES
from .hardware_guard import (
    HardwareAuthorizationError,
    add_hardware_ack_arguments,
    require_hardware_authorization,
)
from .safety import Watchdog, WatchdogTrip
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
    parser.add_argument("--sine-joint", choices=JOINT_NAMES, default=JOINT_NAMES[0])
    parser.add_argument("--mock-latency-ms", type=float, default=0.8)
    parser.add_argument("--enable-torque", action="store_true")
    parser.add_argument(
        "--moving-gate-authorized",
        action="store_true",
        help="Assert the exact moving sine/home gate was separately authorized.",
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--home-seconds", type=float, default=2.0)
    parser.add_argument("--watchdog-failures", type=int, default=3)
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


def _verify_servos(bus, snapshot: ServoSnapshot) -> None:
    snapshot.begin_tick()
    bus.read_state_into(snapshot)
    if not snapshot.all_fresh:
        failures = [
            f"{servo_id}:{ErrorCode(int(code)).name.lower()}"
            for servo_id, code in zip(bus.ids, snapshot.status, strict=True)
            if int(code) != int(ErrorCode.OK)
        ]
        raise RuntimeError("servo verification failed: " + ", ".join(failures))


def _move_home_slowly(
    bus,
    snapshot: ServoSnapshot,
    physical_home_rad,
    *,
    home_seconds: float,
) -> None:
    if home_seconds <= 0:
        raise ValueError("--home-seconds must be positive for a moving gate")
    _verify_servos(bus, snapshot)
    start = snapshot.positions_rad.copy()
    target = start.copy()
    if bus.set_gain_vectors([2] * len(bus.ids)) is not ErrorCode.OK:
        raise RuntimeError("failed to set low startup gains")
    if bus.enable_torque() is not ErrorCode.OK:
        raise RuntimeError("failed to enable torque")
    steps = max(1, int(home_seconds * CONTROL_FREQUENCY_HZ))
    ticker = AbsoluteTicker()
    for step in range(1, steps + 1):
        ticker.wait()
        fraction = step / steps
        np.multiply(start, 1.0 - fraction, out=target)
        target += physical_home_rad * fraction
        if bus.write_positions(target) is not ErrorCode.OK:
            raise RuntimeError("home move write failed")
        snapshot.begin_tick()
        bus.read_state_into(snapshot)
        if not snapshot.all_fresh:
            raise RuntimeError("home move read failed")
    gains = [30] * len(bus.ids)
    gains[5:9] = [8, 8, 8, 8]
    if bus.set_gain_vectors(gains) is not ErrorCode.OK:
        raise RuntimeError("failed to set operating gains")
    if bus.write_positions(physical_home_rad) is not ErrorCode.OK:
        raise RuntimeError("failed to hold home target")


def run_probe(args: argparse.Namespace) -> dict[str, object]:
    if args.ticks < 2:
        raise ValueError("--ticks must be at least 2")
    if args.frequency_hz <= 0:
        raise ValueError("--frequency-hz must be positive")
    if args.sine_hz < 0:
        raise ValueError("--sine-hz must be nonnegative")
    if args.amplitude_rad < 0:
        raise ValueError("--amplitude-rad must be nonnegative")
    if args.watchdog_failures < 1:
        raise ValueError("--watchdog-failures must be positive")
    if args.bus == "serial" and args.enable_torque:
        if not args.moving_gate_authorized:
            raise HardwareAuthorizationError(
                "moving probe is blocked: pass --moving-gate-authorized only after "
                "the exact moving gate is explicitly authorized"
            )
        if args.config is None:
            raise ValueError("moving serial probe requires --config")
    physical_home = HOME_RAD.copy()
    config_sha256 = None
    if args.config is not None:
        config = DuckConfig.load(args.config)
        physical_home += config.offsets_array
        config_sha256 = _sha256(args.config)
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
    targets = physical_home.copy()
    sine_joint_index = JOINT_NAMES.index(args.sine_joint)
    series = TimingSeries(args.ticks, tracking_joint_index=sine_joint_index)
    try:
        writer = AsyncProbeWriter(
            args.output, capacity=min(max(args.ticks, 64), 4096)
        )
    except BaseException:
        try:
            bus.disable_torque()
        finally:
            bus.close()
        raise
    previous_tick_start_ns = 0
    watchdog = Watchdog(
        hard_overrun_ns=2 * int(1e9 / args.frequency_hz),
        max_consecutive_bus_failures=args.watchdog_failures,
    )
    halt_reason = None
    try:
        if args.bus == "serial":
            if bus.disable_torque() is not ErrorCode.OK:
                raise RuntimeError("failed to establish torque-off before probe")
            _verify_servos(bus, snapshot)
        if args.enable_torque:
            _move_home_slowly(
                bus,
                snapshot,
                physical_home,
                home_seconds=args.home_seconds,
            )
        ticker = AbsoluteTicker(period_ns=int(1e9 / args.frequency_hz))
        for tick in range(args.ticks):
            tick_start_ns, lateness_ns = ticker.wait()
            phase = 2.0 * math.pi * args.sine_hz * tick / args.frequency_hz
            targets[:] = physical_home
            targets[sine_joint_index] += args.amplitude_rad * math.sin(phase)
            bus.exchange_into(targets, snapshot, tick)
            tick_period_ns = (
                tick_start_ns - previous_tick_start_ns if previous_tick_start_ns else 0
            )
            previous_tick_start_ns = tick_start_ns
            tracking_targets = targets if args.bus == "mock" or args.enable_torque else None
            series.append(tick_start_ns, lateness_ns, snapshot, tracking_targets)
            writer.publish(
                tick,
                tick_start_ns,
                tick_period_ns,
                lateness_ns,
                snapshot,
                targets,
            )
            tick_work_ns = clock_ns() - tick_start_ns
            bus_ok = (
                snapshot.all_fresh
                and snapshot.write_status is ErrorCode.OK
                and snapshot.extended_status is ErrorCode.OK
                and snapshot.partial_bytes == 0
                and snapshot.unexpected_packets == 0
            )
            watchdog.observe(
                tick_period_ns=tick_period_ns,
                tick_work_ns=tick_work_ns,
                bus_ok=bus_ok,
            )
    except WatchdogTrip as exc:
        halt_reason = str(exc)
    finally:
        try:
            bus.disable_torque()
        finally:
            bus.close()
            writer.close()

    summary = series.summary(backend=args.bus, informational_only=informational_only)
    summary["ticks_requested"] = args.ticks
    summary["run_status"] = "HALTED" if halt_reason else "COMPLETE"
    summary["halt_reason"] = halt_reason
    summary["environment"] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "device": bus.device,
        "baudrate": bus.baudrate,
        "frequency_hz": args.frequency_hz,
        "timeout_ms": args.timeout_ms,
        "sine_hz": args.sine_hz,
        "amplitude_rad": args.amplitude_rad,
        "sine_joint": args.sine_joint,
        "torque_enabled": bool(args.enable_torque),
        "watchdog_consecutive_failures": args.watchdog_failures,
        "config_path": str(args.config) if args.config is not None else None,
        "config_sha256": config_sha256,
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
    return 2 if summary["run_status"] == "HALTED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
