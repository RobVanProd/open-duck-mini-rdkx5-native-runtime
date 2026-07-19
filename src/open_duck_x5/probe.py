from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import signal
import sys
from dataclasses import asdict
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
from .realtime import RealtimeSetupError, configure_realtime, prepare_realtime
from .safety import Watchdog, WatchdogTrip
from .telemetry import AsyncProbeWriter, TelemetryError
from .timing import AbsoluteTicker, TimingSeries
from .transaction_trace import TransactionTraceSeries


class ProbeInterrupted(RuntimeError):
    pass


def _raise_if_stop_requested(args: argparse.Namespace) -> None:
    signum = getattr(args, "stop_signal", None)
    if signum is not None:
        raise ProbeInterrupted(f"signal:{signum}")


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
    parser.add_argument("--require-realtime", action="store_true")
    parser.add_argument("--rt-cpu", type=int, default=7)
    parser.add_argument("--rt-priority", type=int, default=80)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument(
        "--instrument-transactions",
        action="store_true",
        help="Capture preallocated application-level transaction stage timestamps.",
    )
    parser.add_argument(
        "--instrumentation-output",
        type=Path,
        help="Post-loop JSONL destination for --instrument-transactions.",
    )
    add_hardware_ack_arguments(parser)
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _device_alarm_details(bus, snapshot: ServoSnapshot) -> str:
    return ", ".join(
        f"{servo_id}:0x{int(device_status):02x}"
        for servo_id, device_status in zip(
            bus.ids, snapshot.device_status, strict=True
        )
        if int(device_status) != 0
    )


def _verify_servos(
    bus, snapshot: ServoSnapshot, *, reject_device_alarms: bool
) -> None:
    snapshot.begin_tick()
    bus.read_state_into(snapshot)
    if not snapshot.all_fresh:
        failures = [
            f"{servo_id}:{ErrorCode(int(code)).name.lower()}"
            for servo_id, code in zip(bus.ids, snapshot.status, strict=True)
            if int(code) != int(ErrorCode.OK)
        ]
        raise RuntimeError("servo verification failed: " + ", ".join(failures))
    if reject_device_alarms and snapshot.device_alarm_count:
        raise RuntimeError(
            "servo verification reported device alarm: "
            + _device_alarm_details(bus, snapshot)
        )


def _move_home_slowly(
    bus,
    snapshot: ServoSnapshot,
    physical_home_rad,
    *,
    home_seconds: float,
    stop_check,
    watchdog: Watchdog,
) -> None:
    if home_seconds <= 0:
        raise ValueError("--home-seconds must be positive for a moving gate")
    _verify_servos(bus, snapshot, reject_device_alarms=True)
    start = snapshot.positions_rad.copy()
    target = start.copy()
    if bus.set_gain_vectors([2] * len(bus.ids)) is not ErrorCode.OK:
        raise RuntimeError("failed to set low startup gains")
    if bus.enable_torque() is not ErrorCode.OK:
        raise RuntimeError("failed to enable torque")
    steps = max(1, int(home_seconds * CONTROL_FREQUENCY_HZ))
    ticker = AbsoluteTicker()
    previous_tick_start_ns = 0
    for step in range(1, steps + 1):
        stop_check()
        tick_start_ns, _ = ticker.wait()
        stop_check()
        fraction = step / steps
        np.multiply(start, 1.0 - fraction, out=target)
        target += physical_home_rad * fraction
        if bus.write_positions(target) is not ErrorCode.OK:
            raise RuntimeError("home move write failed")
        snapshot.begin_tick()
        bus.read_state_into(snapshot)
        if not snapshot.all_fresh:
            raise RuntimeError("home move read failed")
        if snapshot.device_alarm_count:
            raise RuntimeError(
                "home move device alarm: " + _device_alarm_details(bus, snapshot)
            )
        tick_period_ns = (
            tick_start_ns - previous_tick_start_ns if previous_tick_start_ns else 0
        )
        previous_tick_start_ns = tick_start_ns
        watchdog.observe(
            tick_period_ns=tick_period_ns,
            tick_work_ns=clock_ns() - tick_start_ns,
            bus_ok=True,
        )
    gains = [30] * len(bus.ids)
    gains[5:9] = [8, 8, 8, 8]
    if bus.set_gain_vectors(gains) is not ErrorCode.OK:
        raise RuntimeError("failed to set operating gains")
    if bus.write_positions(physical_home_rad) is not ErrorCode.OK:
        raise RuntimeError("failed to hold home target")


def run_probe(args: argparse.Namespace) -> dict[str, object]:
    if args.ticks < 2:
        raise ValueError("--ticks must be at least 2")
    if args.baudrate <= 0:
        raise ValueError("--baudrate must be positive")
    for name in ("timeout_ms", "frequency_hz", "home_seconds"):
        value = float(getattr(args, name))
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"--{name.replace('_', '-')} must be finite and positive")
    for name in ("sine_hz", "amplitude_rad", "mock_latency_ms"):
        value = float(getattr(args, name))
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"--{name.replace('_', '-')} must be finite and nonnegative")
    if args.watchdog_failures < 1:
        raise ValueError("--watchdog-failures must be positive")
    if args.rt_cpu < 0:
        raise ValueError("--rt-cpu must be nonnegative")
    if not 1 <= args.rt_priority <= 99:
        raise ValueError("--rt-priority must be in 1..99 for SCHED_FIFO")
    output_path = args.output.expanduser().resolve()
    summary_path = args.summary.expanduser().resolve()
    if args.instrument_transactions != (args.instrumentation_output is not None):
        raise ValueError(
            "--instrument-transactions and --instrumentation-output must be used together"
        )
    instrumentation_path = (
        args.instrumentation_output.expanduser().resolve()
        if args.instrumentation_output is not None
        else None
    )
    protected_paths: set[Path] = set()
    if args.config is not None:
        protected_paths.add(args.config.expanduser().resolve())
    if args.bus == "serial":
        protected_paths.add(Path(args.device).expanduser().resolve())
    output_paths = [output_path, summary_path]
    if instrumentation_path is not None:
        output_paths.append(instrumentation_path)
    if len(set(output_paths)) != len(output_paths) or any(
        path in protected_paths for path in output_paths
    ):
        raise ValueError(
            "probe output, summary, instrumentation, config, and serial device must be distinct"
        )
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
        if not args.require_realtime:
            raise RealtimeSetupError("serial timing probe requires --require-realtime")
    realtime_preparation = None
    realtime_state = None
    if args.require_realtime:
        # Partition before the JSON writer thread is created. It then inherits
        # housekeeping affinity and cannot contend with the control loop.
        realtime_preparation = prepare_realtime(cpu=args.rt_cpu, require_isolated=True)
    if args.bus == "serial":
        bus = STS3215Bus(
            args.device,
            baudrate=args.baudrate,
            transaction_timeout_s=args.timeout_ms / 1000.0,
        )
        informational_only = False
        if bus.disable_torque() is not ErrorCode.OK:
            bus.close()
            raise RuntimeError("failed to establish torque-off before probe setup")
    else:
        bus = MockSTS3215Bus(latency_s=args.mock_latency_ms / 1000.0)
        informational_only = True

    snapshot = ServoSnapshot.create()
    snapshot.instrumentation_enabled = bool(args.instrument_transactions)
    targets = physical_home.copy()
    sine_joint_index = JOINT_NAMES.index(args.sine_joint)
    series = TimingSeries(args.ticks, tracking_joint_index=sine_joint_index)
    transaction_trace = (
        TransactionTraceSeries(args.ticks) if args.instrument_transactions else None
    )
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
    torque_off_status = ErrorCode.OK
    try:
        _raise_if_stop_requested(args)
        if realtime_preparation is not None:
            realtime_state = configure_realtime(
                preparation=realtime_preparation,
                priority=args.rt_priority,
            )
        if args.bus == "serial":
            _verify_servos(
                bus,
                snapshot,
                reject_device_alarms=bool(args.enable_torque),
            )
        if args.enable_torque:
            _move_home_slowly(
                bus,
                snapshot,
                physical_home,
                home_seconds=args.home_seconds,
                stop_check=lambda: _raise_if_stop_requested(args),
                watchdog=watchdog,
            )
        ticker = AbsoluteTicker(period_ns=int(1e9 / args.frequency_hz))
        for tick in range(args.ticks):
            _raise_if_stop_requested(args)
            tick_start_ns, lateness_ns = ticker.wait()
            _raise_if_stop_requested(args)
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
            if transaction_trace is not None:
                transaction_trace.append(tick, snapshot)
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
    except (ProbeInterrupted, TelemetryError, WatchdogTrip) as exc:
        halt_reason = str(exc)
    finally:
        try:
            torque_off_status = bus.disable_torque()
        finally:
            bus.close()
            writer.close()
    if torque_off_status is not ErrorCode.OK:
        cutoff_reason = f"cleanup torque-off failed: {torque_off_status.name.lower()}"
        halt_reason = f"{halt_reason}; {cutoff_reason}" if halt_reason else cutoff_reason
    if transaction_trace is not None and instrumentation_path is not None:
        try:
            transaction_trace.write_jsonl(instrumentation_path)
        except OSError as exc:
            trace_reason = f"transaction trace write failed: {exc}"
            halt_reason = f"{halt_reason}; {trace_reason}" if halt_reason else trace_reason

    summary = series.summary(backend=args.bus, informational_only=informational_only)
    summary["ticks_requested"] = args.ticks
    summary["run_status"] = "HALTED" if halt_reason else "COMPLETE"
    summary["halt_reason"] = halt_reason
    summary["review_status"] = (
        "INFORMATIONAL_ONLY" if informational_only else "REVIEW_REQUIRED"
    )
    summary["hardware_gate_status"] = (
        "NOT_APPLICABLE_MOCK" if informational_only else "REVIEW_REQUIRED"
    )
    summary["environment"] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "device": bus.device,
        "baudrate": bus.baudrate,
        "frequency_hz": args.frequency_hz,
        "timeout_ms": args.timeout_ms,
        "home_seconds": args.home_seconds,
        "sine_hz": args.sine_hz,
        "amplitude_rad": args.amplitude_rad,
        "sine_joint": args.sine_joint,
        "torque_enabled": bool(args.enable_torque),
        "torque_off_status": torque_off_status.name.lower(),
        "watchdog_consecutive_failures": args.watchdog_failures,
        "hardware_authorized": bool(args.hardware_authorized),
        "suspended_or_benched": bool(args.suspended_or_benched),
        "moving_gate_authorized": bool(args.moving_gate_authorized),
        "config_path": str(args.config) if args.config is not None else None,
        "config_sha256": config_sha256,
        "telemetry_records_dropped": writer.dropped,
        "realtime": asdict(realtime_state) if realtime_state is not None else None,
    }
    summary["jsonl_sha256"] = _sha256(args.output)
    core_gate_names = (
        "tick_p99_at_most_21_ms",
        "tick_p99_9_at_most_22_ms",
        "zero_read_bursts",
        "transaction_failure_below_0_1_percent",
        "zero_device_alarms",
        "bus_max_under_5_ms",
    )
    complete_stream = (
        halt_reason is None
        and series.count == args.ticks
        and writer.dropped == 0
    )
    torque_off_confirmed = torque_off_status is ErrorCode.OK
    realtime_verified = args.bus == "mock" or realtime_state is not None
    authorization_provenance = args.bus == "mock" or (
        args.hardware_authorized and args.suspended_or_benched
    )
    moving_scope = args.bus == "mock" or (
        args.enable_torque
        and args.moving_gate_authorized
        and config_sha256 is not None
    )
    core_timing_and_bus = all(bool(summary["gates"][name]) for name in core_gate_names)
    hardware_base = (
        args.bus == "serial"
        and complete_stream
        and torque_off_confirmed
        and realtime_verified
        and authorization_provenance
        and moving_scope
        and core_timing_and_bus
    )
    summary["gates"].update(
        {
            "complete_record_stream": complete_stream,
            "torque_off_confirmed": torque_off_confirmed,
            "realtime_verified_when_required": realtime_verified,
            "authorization_provenance": authorization_provenance,
            "moving_gate_scope": moving_scope,
            "gate2_home_hold_candidate": hardware_base
            and args.enable_torque
            and args.amplitude_rad == 0.0,
            "gate4_sine_candidate": hardware_base
            and args.enable_torque
            and args.amplitude_rad == 0.03
            and args.sine_hz in (0.25, 0.5)
            and bool(summary["gates"]["tracking_p95_at_most_0_011_rad"]),
        }
    )
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    summary_bytes = (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode("utf-8")
    args.summary.write_bytes(summary_bytes)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.stop_signal = None

    def request_stop(signum, frame) -> None:
        del frame
        args.stop_signal = signum

    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        try:
            summary = run_probe(args)
        except (
            HardwareAuthorizationError,
            RealtimeSetupError,
            ValueError,
            RuntimeError,
        ) as exc:
            parser.error(str(exc))
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 2 if summary["run_status"] == "HALTED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
