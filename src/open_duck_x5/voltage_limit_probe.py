from __future__ import annotations

import argparse
import json
import platform
import re
import sys
from pathlib import Path

from .bus import ErrorCode, MockSTS3215Bus, STS3215Bus
from .bus.sts3215 import ADDR_MAX_INPUT_VOLTAGE, ADDR_MODEL
from .clock import clock_ns
from .constants import SERVO_IDS, SERVO_SYNC_READ_IDS
from .hardware_guard import (
    HardwareAuthorizationError,
    add_hardware_ack_arguments,
    require_hardware_authorization,
)

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Torque-off all-servo model and voltage-limit diagnostic"
    )
    parser.add_argument("--bus", choices=("mock", "serial"), default="mock")
    parser.add_argument("--device", default="/dev/ttyS1")
    parser.add_argument("--baudrate", type=int, default=1_000_000)
    parser.add_argument("--timeout-ms", type=float, default=4.0)
    parser.add_argument("--watchdog-failures", type=int, default=2)
    parser.add_argument("--repository-commit", default="NOT_APPLICABLE")
    parser.add_argument("--output", type=Path, required=True)
    add_hardware_ack_arguments(parser)
    return parser


def _read(
    bus: MockSTS3215Bus | STS3215Bus, servo_id: int, address: int
) -> tuple[dict[str, object], bool]:
    start_ns = clock_ns()
    status, device_error, parameters = bus.read_register_with_device_status(
        servo_id, address, 2
    )
    complete = (
        status in (ErrorCode.OK, ErrorCode.DEVICE)
        and device_error is not None
        and len(parameters) == 2
    )
    return (
        {
            "address": address,
            "length": 2,
            "response_status": status.name.lower(),
            "device_status_raw": device_error,
            "data": list(parameters),
            "response_length": len(parameters),
            "round_trip_ms": (clock_ns() - start_ns) / 1e6,
        },
        complete,
    )


def run_probe(args: argparse.Namespace) -> dict[str, object]:
    if args.baudrate <= 0 or args.timeout_ms <= 0:
        raise ValueError("baudrate and timeout must be positive")
    if args.watchdog_failures < 1:
        raise ValueError("--watchdog-failures must be positive")
    output_path = args.output.expanduser().resolve()
    if args.bus == "serial":
        require_hardware_authorization(
            hardware_authorized=args.hardware_authorized,
            suspended_or_benched=args.suspended_or_benched,
            operation="all-servo model and voltage-limit diagnostic",
        )
        if not COMMIT_RE.fullmatch(args.repository_commit):
            raise ValueError("serial limit diagnostic requires a 40-hex repository commit")
        if output_path == Path(args.device).expanduser().resolve():
            raise ValueError("diagnostic output and serial device must be distinct")
        bus = STS3215Bus(
            args.device,
            baudrate=args.baudrate,
            transaction_timeout_s=args.timeout_ms / 1000.0,
        )
        informational_only = False
    else:
        bus = MockSTS3215Bus(latency_s=0.0)
        informational_only = True

    initial_torque_off = bus.disable_torque()
    if initial_torque_off is not ErrorCode.OK:
        try:
            bus.disable_torque()
        finally:
            bus.close()
        raise RuntimeError(
            f"failed to establish torque off: {initial_torque_off.name.lower()}"
        )

    records: list[dict[str, object]] = []
    halt_reason: str | None = None
    consecutive_failures = 0
    final_torque_off = ErrorCode.TIMEOUT
    try:
        for wire_index, servo_id in enumerate(SERVO_SYNC_READ_IDS):
            model, model_complete = _read(bus, servo_id, ADDR_MODEL)
            consecutive_failures = 0 if model_complete else consecutive_failures + 1
            limits: dict[str, object] | None = None
            limits_complete = False
            if consecutive_failures < args.watchdog_failures:
                limits, limits_complete = _read(
                    bus, servo_id, ADDR_MAX_INPUT_VOLTAGE
                )
                consecutive_failures = 0 if limits_complete else consecutive_failures + 1

            model_data = model["data"]
            limit_data = limits["data"] if limits is not None else []
            records.append(
                {
                    "wire_index": wire_index,
                    "logical_index": SERVO_IDS.index(servo_id),
                    "servo_id": servo_id,
                    "model_read": model,
                    "voltage_limit_read": limits,
                    "model_raw": (
                        int(model_data[0]) | (int(model_data[1]) << 8)
                        if model_complete
                        else None
                    ),
                    "model_low": int(model_data[0]) if model_complete else None,
                    "model_high": int(model_data[1]) if model_complete else None,
                    "max_voltage_raw": int(limit_data[0]) if limits_complete else None,
                    "max_voltage_v": int(limit_data[0]) * 0.1 if limits_complete else None,
                    "min_voltage_raw": int(limit_data[1]) if limits_complete else None,
                    "min_voltage_v": int(limit_data[1]) * 0.1 if limits_complete else None,
                }
            )
            if consecutive_failures >= args.watchdog_failures:
                halt_reason = (
                    "consecutive configuration-read transport failures reached "
                    f"{args.watchdog_failures}"
                )
                break
    except Exception as exc:
        halt_reason = f"model/limit diagnostic exception: {exc}"
    finally:
        try:
            final_torque_off = bus.disable_torque()
        finally:
            bus.close()

    if final_torque_off is not ErrorCode.OK:
        cutoff = f"final torque-off failed: {final_torque_off.name.lower()}"
        halt_reason = f"{halt_reason}; {cutoff}" if halt_reason else cutoff

    complete_all14 = len(records) == len(SERVO_IDS) and all(
        record["model_raw"] is not None and record["max_voltage_raw"] is not None
        for record in records
    )
    models = {record["model_raw"] for record in records if record["model_raw"] is not None}
    limits = {
        (record["max_voltage_raw"], record["min_voltage_raw"])
        for record in records
        if record["max_voltage_raw"] is not None
    }
    finding = (
        "incomplete_transport"
        if not complete_all14
        else "uniform_model_and_limits"
        if len(models) == 1 and len(limits) == 1
        else "mixed_model_or_limits"
    )
    summary = {
        "schema_version": "open_duck_x5.voltage_limit_diagnostic.v1",
        "backend": args.bus,
        "informational_only": informational_only,
        "review_status": "INFORMATIONAL_ONLY" if informational_only else "REVIEW_REQUIRED",
        "hardware_gate_status": "NOT_ADVANCED_DIAGNOSTIC_ONLY",
        "run_status": "HALTED" if halt_reason else "COMPLETE",
        "halt_reason": halt_reason,
        "finding": finding,
        "read_order": list(SERVO_SYNC_READ_IDS),
        "register_reads": [
            {"address": ADDR_MODEL, "length": 2, "meaning": "model/version"},
            {
                "address": ADDR_MAX_INPUT_VOLTAGE,
                "length": 2,
                "meaning": "maximum/minimum input voltage",
            },
        ],
        "volts_per_count": 0.1,
        "records": records,
        "complete_all14": complete_all14,
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "device": bus.device,
            "baudrate": bus.baudrate,
            "timeout_ms": args.timeout_ms,
            "repository_commit": args.repository_commit,
            "hardware_authorized": bool(args.hardware_authorized),
            "suspended_or_benched": bool(args.suspended_or_benched),
        },
        "safety": {
            "torque_enable_requested": False,
            "goal_position_write_count": 0,
            "eeprom_write_count": 0,
            "initial_torque_off_status": initial_torque_off.name.lower(),
            "final_torque_off_status": final_torque_off.name.lower(),
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(
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
