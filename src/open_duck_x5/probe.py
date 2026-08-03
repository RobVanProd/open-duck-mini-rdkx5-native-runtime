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
from .controller import ControllerReadout, create_controller
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
    parser.add_argument("--device", default="/dev/ttyS1")
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
    parser.add_argument("--controller", choices=("none", "xbox", "f710"), default="none")
    parser.add_argument(
        "--startup-readiness-exchange",
        action="store_true",
        help=(
            "Require one separately recorded full-shape torque-off exchange before the "
            "measured ticker population. The exchange is never retried or discarded."
        ),
    )
    parser.add_argument(
        "--startup-readiness-output",
        type=Path,
        help="Dedicated JSON result for --startup-readiness-exchange.",
    )
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
    details = [
        f"{servo_id}:0x{int(device_status):02x}"
        for servo_id, device_status in zip(
            bus.ids, snapshot.device_status, strict=True
        )
        if int(device_status) != 0
    ]
    if snapshot.extended_device_status:
        details.append(
            f"extended-{snapshot.extended_servo_id}:"
            f"0x{int(snapshot.extended_device_status):02x}"
        )
    return ", ".join(details)


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
    if reject_device_alarms and snapshot.any_device_alarm:
        raise RuntimeError(
            "servo verification reported device alarm: "
            + _device_alarm_details(bus, snapshot)
        )


def _read_controller_or_trip(
    controller,
    readout: ControllerReadout,
    *,
    reject_toggle: bool,
) -> None:
    controller.read_into(readout)
    now_ns = clock_ns()
    if not readout.connected or now_ns - readout.timestamp_ns > 250_000_000:
        raise WatchdogTrip("physical controller state is disconnected or stale")
    if readout.emergency_stop:
        raise WatchdogTrip("physical controller emergency stop requested")
    if reject_toggle and readout.pause_toggle:
        raise WatchdogTrip("physical controller toggled during startup readiness")


def _startup_readiness_record(
    bus,
    snapshot: ServoSnapshot,
    *,
    tick_start_ns: int,
    tick_work_ns: int,
    hard_overrun_ns: int,
    release_lateness_ns: int,
    next_measured_tick_start_ns: int,
) -> dict[str, object]:
    per_servo_status = [ErrorCode(int(code)).name.lower() for code in snapshot.status]
    failures: list[str] = []
    if snapshot.write_status is not ErrorCode.OK:
        failures.append(f"write:{snapshot.write_status.name.lower()}")
    failures.extend(
        f"{servo_id}:{status}"
        for servo_id, status in zip(bus.ids, per_servo_status, strict=True)
        if status != "ok"
    )
    if snapshot.extended_status is not ErrorCode.OK:
        failures.append(
            f"extended-{snapshot.extended_servo_id}:"
            f"{snapshot.extended_status.name.lower()}"
        )
    if snapshot.partial_bytes:
        failures.append(f"partial-bytes:{snapshot.partial_bytes}")
    if snapshot.unexpected_packets:
        failures.append(f"unexpected-packets:{snapshot.unexpected_packets}")
    if snapshot.any_device_alarm:
        failures.append("device-alarm:" + _device_alarm_details(bus, snapshot))
    bus_total_ms = snapshot.bus_total_ns / 1e6
    if bus_total_ms >= 5.0:
        failures.append(f"bus-total-ms:{bus_total_ms:.6f}")
    tick_work_ms = tick_work_ns / 1e6
    if tick_work_ns > hard_overrun_ns:
        failures.append(f"tick-work-ms:{tick_work_ms:.6f}")
    next_period_ms = (
        (next_measured_tick_start_ns - tick_start_ns) / 1e6
        if next_measured_tick_start_ns > 0
        else None
    )
    return {
        "schema_version": "open_duck_x5.startup_readiness_exchange.v1",
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "tick_start_monotonic_ns": tick_start_ns,
        "tick_work_ms": tick_work_ms,
        "release_lateness_ms": release_lateness_ns / 1e6,
        "next_measured_tick_period_ms": next_period_ms,
        "bus_total_ms": bus_total_ms,
        "group_round_trip_ms": snapshot.group_round_trip_ns / 1e6,
        "extended_round_trip_ms": snapshot.extended_round_trip_ns / 1e6,
        "write_status": snapshot.write_status.name.lower(),
        "per_servo_status": per_servo_status,
        "per_servo_device_status": snapshot.device_status.tolist(),
        "extended_status": snapshot.extended_status.name.lower(),
        "extended_servo_id": snapshot.extended_servo_id,
        "extended_device_status": snapshot.extended_device_status,
        "partial_bytes": snapshot.partial_bytes,
        "unexpected_packets": snapshot.unexpected_packets,
        "all_fresh": snapshot.all_fresh,
        "instrumentation": {
            "bus_start_ns": snapshot.trace_bus_start_ns,
            "bus_end_ns": snapshot.trace_bus_end_ns,
            "group_write_end_ns": snapshot.trace_group_write_end_ns,
            "group_first_rx_ns": snapshot.trace_group_first_rx_ns,
            "group_last_rx_ns": snapshot.trace_group_last_rx_ns,
            "group_end_ns": snapshot.trace_group_end_ns,
            "group_read_calls": snapshot.trace_group_read_calls,
            "group_parse_calls": snapshot.trace_group_parse_calls,
            "group_parser_mode": snapshot.trace_group_parser_mode,
            "extended_write_end_ns": snapshot.trace_extended_write_end_ns,
            "extended_first_rx_ns": snapshot.trace_extended_first_rx_ns,
            "extended_last_rx_ns": snapshot.trace_extended_last_rx_ns,
            "extended_end_ns": snapshot.trace_extended_end_ns,
        },
    }


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
        if snapshot.any_device_alarm:
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
    if args.startup_readiness_exchange != (args.startup_readiness_output is not None):
        raise ValueError(
            "--startup-readiness-exchange and --startup-readiness-output must be used together"
        )
    if args.startup_readiness_exchange and args.enable_torque:
        raise ValueError("startup readiness exchange is currently torque-off only")
    readiness_path = (
        args.startup_readiness_output.expanduser().resolve()
        if args.startup_readiness_output is not None
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
    if readiness_path is not None:
        output_paths.append(readiness_path)
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
    if args.controller != "none" and args.bus != "serial":
        raise ValueError("a physical controller can only accompany a serial timing probe")
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
    controller = None
    controller_readout = ControllerReadout()
    if args.controller != "none":
        try:
            controller = create_controller(args.controller)
            # Opening a Linux UHID consumer can trigger BlueZ/GATT setup. Drain
            # the bounded joydev initialization batch before serial is opened so
            # that work cannot become part of the first servo transaction.
            _read_controller_or_trip(
                controller,
                controller_readout,
                reject_toggle=False,
            )
        except BaseException:
            if controller is not None:
                controller.close()
            raise

    try:
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
    except BaseException:
        if controller is not None:
            controller.close()
        raise

    snapshot = ServoSnapshot.create()
    snapshot.instrumentation_enabled = bool(args.instrument_transactions)
    targets = physical_home.copy()
    sine_joint_index = JOINT_NAMES.index(args.sine_joint)
    series = TimingSeries(args.ticks, tracking_joint_index=sine_joint_index)
    transaction_trace = (
        TransactionTraceSeries(args.ticks) if args.instrument_transactions else None
    )
    readiness_snapshot = ServoSnapshot.create()
    readiness_snapshot.instrumentation_enabled = True
    readiness_tick_start_ns = 0
    readiness_tick_work_ns = 0
    readiness_release_lateness_ns = 0
    first_measured_tick_start_ns = 0
    readiness_record: dict[str, object] | None = None
    try:
        writer = AsyncProbeWriter(
            args.output, capacity=min(max(args.ticks, 64), 4096)
        )
    except BaseException:
        try:
            bus.disable_torque()
        finally:
            bus.close()
            if controller is not None:
                controller.close()
        raise
    previous_tick_start_ns = 0
    watchdog = Watchdog(
        hard_overrun_ns=2 * int(1e9 / args.frequency_hz),
        max_consecutive_bus_failures=args.watchdog_failures,
    )

    def check_stop_and_controller() -> None:
        _raise_if_stop_requested(args)
        if controller is not None:
            _read_controller_or_trip(
                controller,
                controller_readout,
                reject_toggle=True,
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
        if controller is not None:
            _read_controller_or_trip(
                controller,
                controller_readout,
                reject_toggle=True,
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
                stop_check=check_stop_and_controller,
                watchdog=watchdog,
            )
        ticker = AbsoluteTicker(period_ns=int(1e9 / args.frequency_hz))
        if args.startup_readiness_exchange:
            _raise_if_stop_requested(args)
            readiness_tick_start_ns, readiness_release_lateness_ns = ticker.wait()
            _raise_if_stop_requested(args)
            if controller is not None:
                _read_controller_or_trip(
                    controller,
                    controller_readout,
                    reject_toggle=True,
                )
            bus.exchange_into(targets, readiness_snapshot, 0)
            readiness_tick_work_ns = clock_ns() - readiness_tick_start_ns
            readiness_record = _startup_readiness_record(
                bus,
                readiness_snapshot,
                tick_start_ns=readiness_tick_start_ns,
                tick_work_ns=readiness_tick_work_ns,
                hard_overrun_ns=watchdog.hard_overrun_ns,
                release_lateness_ns=readiness_release_lateness_ns,
                next_measured_tick_start_ns=0,
            )
            if readiness_record["status"] != "PASS":
                raise WatchdogTrip(
                    "startup readiness exchange failed: "
                    + ", ".join(str(value) for value in readiness_record["failures"])
                )
            previous_tick_start_ns = readiness_tick_start_ns
        for tick in range(args.ticks):
            _raise_if_stop_requested(args)
            tick_start_ns, lateness_ns = ticker.wait()
            _raise_if_stop_requested(args)
            if tick == 0:
                first_measured_tick_start_ns = tick_start_ns
            if controller is not None:
                _read_controller_or_trip(
                    controller,
                    controller_readout,
                    reject_toggle=False,
                )
            phase = 2.0 * math.pi * args.sine_hz * tick / args.frequency_hz
            targets[:] = physical_home
            targets[sine_joint_index] += args.amplitude_rad * math.sin(phase)
            bus.exchange_into(targets, snapshot, tick)
            if args.enable_torque and snapshot.any_device_alarm:
                raise WatchdogTrip(
                    "servo device alarm during moving probe: "
                    + _device_alarm_details(bus, snapshot)
                )
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
            if controller is not None:
                controller.close()
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
    if readiness_record is not None:
        readiness_record = _startup_readiness_record(
            bus,
            readiness_snapshot,
            tick_start_ns=readiness_tick_start_ns,
            tick_work_ns=readiness_tick_work_ns,
            hard_overrun_ns=watchdog.hard_overrun_ns,
            release_lateness_ns=readiness_release_lateness_ns,
            next_measured_tick_start_ns=first_measured_tick_start_ns,
        )
        if readiness_path is None:
            raise AssertionError("startup readiness record lacks an output path")
        try:
            readiness_path.parent.mkdir(parents=True, exist_ok=True)
            readiness_path.write_text(
                json.dumps(readiness_record, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            readiness_reason = f"startup readiness output failed: {exc}"
            halt_reason = (
                f"{halt_reason}; {readiness_reason}" if halt_reason else readiness_reason
            )

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
        "controller": args.controller,
        "controller_backend": (
            type(controller).__name__ if controller is not None else None
        ),
        "startup_readiness_exchange": bool(args.startup_readiness_exchange),
        "startup_readiness_output": (
            str(readiness_path) if readiness_path is not None else None
        ),
        "hardware_authorized": bool(args.hardware_authorized),
        "suspended_or_benched": bool(args.suspended_or_benched),
        "moving_gate_authorized": bool(args.moving_gate_authorized),
        "config_path": str(args.config) if args.config is not None else None,
        "config_sha256": config_sha256,
        "telemetry_records_dropped": writer.dropped,
        "realtime": asdict(realtime_state) if realtime_state is not None else None,
    }
    summary["startup_readiness"] = readiness_record
    measured_bus_max = summary["bus_total_ms"]["max"]
    readiness_bus_max = (
        float(readiness_record["bus_total_ms"])
        if readiness_record is not None
        else None
    )
    overall_bus_values = [
        float(value)
        for value in (measured_bus_max, readiness_bus_max)
        if value is not None
    ]
    summary["overall_bus_max_ms"] = max(overall_bus_values) if overall_bus_values else None
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
    readiness_passed = not args.startup_readiness_exchange or (
        readiness_record is not None and readiness_record["status"] == "PASS"
    )
    overall_bus_passed = (
        summary["overall_bus_max_ms"] is not None
        and summary["overall_bus_max_ms"] < 5.0
    )
    core_timing_and_bus = all(bool(summary["gates"][name]) for name in core_gate_names)
    hardware_base = (
        args.bus == "serial"
        and complete_stream
        and torque_off_confirmed
        and realtime_verified
        and authorization_provenance
        and moving_scope
        and readiness_passed
        and overall_bus_passed
        and core_timing_and_bus
    )
    summary["gates"].update(
        {
            "complete_record_stream": complete_stream,
            "torque_off_confirmed": torque_off_confirmed,
            "realtime_verified_when_required": realtime_verified,
            "authorization_provenance": authorization_provenance,
            "moving_gate_scope": moving_scope,
            "startup_readiness_required": bool(args.startup_readiness_exchange),
            "startup_readiness_passed": readiness_passed,
            "overall_bus_max_under_5_ms": overall_bus_passed,
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
