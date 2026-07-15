from __future__ import annotations

import argparse
import hashlib
import json
import platform
import queue
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .bus import ErrorCode, MockSTS3215Bus, STS3215Bus
from .bus.sts3215 import ADDR_PRESENT_POSITION
from .bus.types import ERROR_NAMES
from .clock import clock_ns
from .constants import CONTROL_FREQUENCY_HZ, SERVO_IDS
from .hardware_guard import (
    HardwareAuthorizationError,
    add_hardware_ack_arguments,
    require_hardware_authorization,
)
from .safety import Watchdog, WatchdogTrip
from .telemetry import TelemetryError
from .timing import AbsoluteTicker


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(slots=True)
class SingleServoRecord:
    tick: int = 0
    tick_start_ns: int = 0
    tick_period_ns: int = 0
    round_trip_ns: int = 0
    status: int = int(ErrorCode.TIMEOUT)
    device_status: int = 0
    response_length: int = 0

    def capture(
        self,
        tick: int,
        tick_start_ns: int,
        tick_period_ns: int,
        round_trip_ns: int,
        status: ErrorCode,
        device_status: int,
        response_length: int,
    ) -> None:
        self.tick = tick
        self.tick_start_ns = tick_start_ns
        self.tick_period_ns = tick_period_ns
        self.round_trip_ns = round_trip_ns
        self.status = int(status)
        self.device_status = int(device_status)
        self.response_length = response_length

    def as_jsonable(self, servo_id: int) -> dict[str, object]:
        return {
            "schema_version": "open_duck_x5.single_servo_tick.v1",
            "tick": self.tick,
            "timestamp_monotonic_ns": self.tick_start_ns,
            "tick_period_ms": self.tick_period_ns / 1e6 if self.tick_period_ns else None,
            "servo_id": servo_id,
            "round_trip_ms": self.round_trip_ns / 1e6,
            "status": ERROR_NAMES[self.status],
            "device_status_raw": self.device_status,
            "response_length": self.response_length,
        }


class AsyncSingleServoWriter:
    def __init__(self, path: Path, servo_id: int, *, capacity: int) -> None:
        self.path = path
        self.servo_id = servo_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._free: queue.SimpleQueue[SingleServoRecord] = queue.SimpleQueue()
        self._pending: queue.Queue[SingleServoRecord | None] = queue.Queue(
            maxsize=capacity
        )
        for _ in range(capacity):
            self._free.put(SingleServoRecord())
        self.dropped = 0
        self._error: BaseException | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="single-servo-jsonl-writer", daemon=True
        )
        self._thread.start()
        self._ready.wait()
        self._raise_if_failed()

    def _raise_if_failed(self) -> None:
        if self._error is not None:
            raise TelemetryError(
                f"single-servo telemetry writer failed: {self._error}"
            ) from self._error

    def publish(
        self,
        tick: int,
        tick_start_ns: int,
        tick_period_ns: int,
        round_trip_ns: int,
        status: ErrorCode,
        device_status: int,
        response_length: int,
    ) -> None:
        self._raise_if_failed()
        try:
            record = self._free.get_nowait()
        except queue.Empty as exc:
            self.dropped += 1
            raise TelemetryError(
                "single-servo telemetry record pool exhausted"
            ) from exc
        record.capture(
            tick,
            tick_start_ns,
            tick_period_ns,
            round_trip_ns,
            status,
            device_status,
            response_length,
        )
        try:
            self._pending.put_nowait(record)
        except queue.Full as exc:
            self.dropped += 1
            self._free.put(record)
            raise TelemetryError("single-servo telemetry queue overflow") from exc

    def _run(self) -> None:
        try:
            with self.path.open("w", encoding="utf-8", buffering=1) as handle:
                self._ready.set()
                while True:
                    record = self._pending.get()
                    if record is None:
                        return
                    handle.write(
                        json.dumps(
                            record.as_jsonable(self.servo_id), separators=(",", ":")
                        )
                        + "\n"
                    )
                    self._free.put(record)
        except BaseException as exc:
            self._error = exc
            self._ready.set()

    def close(self) -> None:
        while self._thread.is_alive():
            try:
                self._pending.put(None, timeout=0.1)
                break
            except queue.Full:
                continue
        self._thread.join()
        self._raise_if_failed()


def _stats_ns(values: np.ndarray) -> dict[str, float | None]:
    if not values.size:
        return {key: None for key in ("min", "mean", "p95", "p99", "p99_9", "max")}
    values_ms = values.astype(np.float64) / 1e6
    return {
        "min": float(np.min(values_ms)),
        "mean": float(np.mean(values_ms)),
        "p95": float(np.percentile(values_ms, 95)),
        "p99": float(np.percentile(values_ms, 99)),
        "p99_9": float(np.percentile(values_ms, 99.9)),
        "max": float(np.max(values_ms)),
    }


def _bursts(failed: np.ndarray) -> tuple[int, int]:
    count = 0
    longest = 0
    current = 0
    for value in failed:
        if value:
            current += 1
            longest = max(longest, current)
        else:
            if current >= 2:
                count += 1
            current = 0
    if current >= 2:
        count += 1
    return count, longest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Torque-off single-servo echo/read timing probe for hardware Gate 1"
    )
    parser.add_argument("--bus", choices=("mock", "serial"), default="mock")
    parser.add_argument("--device", default="/dev/ttyACM0")
    parser.add_argument("--baudrate", type=int, default=1_000_000)
    parser.add_argument("--timeout-ms", type=float, default=4.0)
    parser.add_argument("--servo-id", type=int, choices=SERVO_IDS, default=SERVO_IDS[0])
    parser.add_argument("--ticks", type=int, default=10_000)
    parser.add_argument("--frequency-hz", type=float, default=CONTROL_FREQUENCY_HZ)
    parser.add_argument("--watchdog-failures", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    add_hardware_ack_arguments(parser)
    return parser


def run_probe(args: argparse.Namespace) -> dict[str, object]:
    if args.ticks < 2:
        raise ValueError("--ticks must be at least 2")
    if args.baudrate <= 0:
        raise ValueError("--baudrate must be positive")
    if (
        not np.isfinite(args.frequency_hz)
        or args.frequency_hz <= 0
        or not np.isfinite(args.timeout_ms)
        or args.timeout_ms <= 0
    ):
        raise ValueError("frequency and timeout must be finite and positive")
    if args.watchdog_failures < 1:
        raise ValueError("--watchdog-failures must be positive")
    output_path = args.output.expanduser().resolve()
    summary_path = args.summary.expanduser().resolve()
    protected_paths = {summary_path}
    if args.bus == "serial":
        protected_paths.add(Path(args.device).expanduser().resolve())
    if output_path in protected_paths or summary_path == Path(args.device).expanduser().resolve():
        raise ValueError("probe output, summary, and serial device must be distinct")
    if args.bus == "serial":
        require_hardware_authorization(
            hardware_authorized=args.hardware_authorized,
            suspended_or_benched=args.suspended_or_benched,
            operation="single-servo Gate 1 probe",
        )
        bus = STS3215Bus(
            args.device,
            baudrate=args.baudrate,
            transaction_timeout_s=args.timeout_ms / 1000.0,
        )
        informational_only = False
        if bus.disable_torque() is not ErrorCode.OK:
            bus.close()
            raise RuntimeError("failed to establish torque-off before Gate 1 setup")
    else:
        bus = MockSTS3215Bus(latency_s=0.0)
        informational_only = True

    try:
        writer = AsyncSingleServoWriter(
            args.output,
            args.servo_id,
            capacity=min(max(args.ticks, 64), 4096),
        )
    except BaseException:
        try:
            bus.disable_torque()
        finally:
            bus.close()
        raise
    round_trip_ns = np.zeros(args.ticks, dtype=np.int64)
    tick_period_ns = np.zeros(args.ticks, dtype=np.int64)
    statuses = np.full(args.ticks, int(ErrorCode.TIMEOUT), dtype=np.uint8)
    device_statuses = np.zeros(args.ticks, dtype=np.uint8)
    response_lengths = np.zeros(args.ticks, dtype=np.int16)
    ping_status = ErrorCode.TIMEOUT
    ping_device_status: int | None = None
    previous_tick_ns = 0
    watchdog = Watchdog(
        hard_overrun_ns=2 * int(1e9 / args.frequency_hz),
        max_consecutive_bus_failures=args.watchdog_failures,
    )
    halt_reason = None
    torque_off_status = ErrorCode.OK
    completed_ticks = 0
    try:
        ping_status, ping_device_status = bus.ping_with_device_status(args.servo_id)
        if ping_status is not ErrorCode.OK:
            raise RuntimeError(
                f"servo {args.servo_id} ping failed: {ping_status.name.lower()}"
            )
        ticker = AbsoluteTicker(period_ns=int(1e9 / args.frequency_hz))
        for tick in range(args.ticks):
            tick_start_ns, _ = ticker.wait()
            tick_period_ns[tick] = (
                tick_start_ns - previous_tick_ns if previous_tick_ns else 0
            )
            previous_tick_ns = tick_start_ns
            transaction_start_ns = clock_ns()
            status, device_status, response = bus.read_register_with_device_status(
                args.servo_id, ADDR_PRESENT_POSITION, 2
            )
            elapsed_ns = clock_ns() - transaction_start_ns
            round_trip_ns[tick] = elapsed_ns
            statuses[tick] = int(status)
            device_statuses[tick] = int(device_status or 0)
            response_lengths[tick] = len(response)
            writer.publish(
                tick,
                tick_start_ns,
                int(tick_period_ns[tick]),
                elapsed_ns,
                status,
                int(device_status or 0),
                len(response),
            )
            completed_ticks = tick + 1
            watchdog.observe(
                tick_period_ns=int(tick_period_ns[tick]),
                tick_work_ns=clock_ns() - tick_start_ns,
                bus_ok=status is ErrorCode.OK,
            )
    except (TelemetryError, WatchdogTrip) as exc:
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

    completed_statuses = statuses[:completed_ticks]
    status_counts = {
        ERROR_NAMES[int(code)]: int(np.count_nonzero(completed_statuses == int(code)))
        for code in ErrorCode
    }
    failures = completed_statuses != int(ErrorCode.OK)
    failure_count = int(np.count_nonzero(failures))
    device_alarm_count = int(np.count_nonzero(device_statuses[:completed_ticks]))
    voltage_alarm_count = int(
        np.count_nonzero(device_statuses[:completed_ticks] & 0x01)
    )
    unexpected_response_lengths = int(
        np.count_nonzero(response_lengths[:completed_ticks] != 2)
    )
    burst_count, max_burst = _bursts(failures)
    summary = {
        "schema_version": "open_duck_x5.single_servo_summary.v1",
        "backend": args.bus,
        "informational_only": informational_only,
        "review_status": (
            "INFORMATIONAL_ONLY" if informational_only else "REVIEW_REQUIRED"
        ),
        "hardware_gate_status": (
            "NOT_APPLICABLE_MOCK" if informational_only else "REVIEW_REQUIRED"
        ),
        "run_status": "HALTED" if halt_reason else "COMPLETE",
        "halt_reason": halt_reason,
        "servo_id": args.servo_id,
        "ticks": completed_ticks,
        "ticks_requested": args.ticks,
        "ping_status": ping_status.name.lower(),
        "ping_device_status_raw": ping_device_status,
        "tick_period_ms": _stats_ns(tick_period_ns[1:completed_ticks]),
        "round_trip_ms": _stats_ns(round_trip_ns[:completed_ticks]),
        "transaction_status_counts": status_counts,
        "transactions_failed": failure_count,
        "device_alarm_reply_count": device_alarm_count,
        "voltage_alarm_reply_count": voltage_alarm_count,
        "unexpected_response_length_count": unexpected_response_lengths,
        "transaction_failure_rate": (
            failure_count / completed_ticks if completed_ticks else 0.0
        ),
        "read_burst_count": burst_count,
        "max_read_burst_ticks": max_burst,
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "device": bus.device,
            "baudrate": bus.baudrate,
            "frequency_hz": args.frequency_hz,
            "timeout_ms": args.timeout_ms,
            "torque_enabled": False,
            "torque_off_status": torque_off_status.name.lower(),
            "watchdog_consecutive_failures": args.watchdog_failures,
            "telemetry_records_dropped": writer.dropped,
            "hardware_authorized": bool(args.hardware_authorized),
            "suspended_or_benched": bool(args.suspended_or_benched),
        },
        "jsonl_sha256": _sha256(args.output),
    }
    complete_stream = (
        halt_reason is None
        and completed_ticks == args.ticks
        and writer.dropped == 0
    )
    torque_off_confirmed = torque_off_status is ErrorCode.OK
    authorization_provenance = args.bus == "mock" or (
        args.hardware_authorized and args.suspended_or_benched
    )
    summary["gates"] = {
        "complete_record_stream": complete_stream,
        "torque_off_confirmed": torque_off_confirmed,
        "authorization_provenance": authorization_provenance,
        "ping_ok": ping_status is ErrorCode.OK,
        "zero_transaction_failures": failure_count == 0,
        "zero_device_alarms": device_alarm_count == 0
        and not bool(ping_device_status),
        "zero_unexpected_response_lengths": unexpected_response_lengths == 0,
        "zero_read_bursts": burst_count == 0,
        "gate1_candidate": args.bus == "serial"
        and complete_stream
        and torque_off_confirmed
        and authorization_provenance
        and ping_status is ErrorCode.OK
        and failure_count == 0
        and device_alarm_count == 0
        and not bool(ping_device_status)
        and unexpected_response_lengths == 0
        and burst_count == 0,
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
    except (HardwareAuthorizationError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 2 if summary["run_status"] == "HALTED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
