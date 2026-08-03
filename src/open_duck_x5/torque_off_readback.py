from __future__ import annotations

import argparse
import json
import platform
import re
import sys
from pathlib import Path

from .bus import ErrorCode, MockSTS3215Bus, STS3215Bus
from .bus.sts3215 import ADDR_TORQUE_ENABLE
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
        description="Independently disable torque and read register 40 on all servos"
    )
    parser.add_argument("--bus", choices=("mock", "serial"), default="mock")
    parser.add_argument("--device", default="/dev/ttyS1")
    parser.add_argument("--baudrate", type=int, default=1_000_000)
    parser.add_argument("--timeout-ms", type=float, default=4.0)
    parser.add_argument("--repository-commit", default="NOT_APPLICABLE")
    parser.add_argument("--output", type=Path, required=True)
    add_hardware_ack_arguments(parser)
    return parser


def run_readback(args: argparse.Namespace) -> dict[str, object]:
    if args.baudrate <= 0:
        raise ValueError("--baudrate must be positive")
    if args.timeout_ms <= 0:
        raise ValueError("--timeout-ms must be positive")
    output_path = args.output.expanduser().resolve()
    if args.bus == "serial":
        require_hardware_authorization(
            hardware_authorized=args.hardware_authorized,
            suspended_or_benched=args.suspended_or_benched,
            operation="all-servo torque-off register readback",
        )
        if not COMMIT_RE.fullmatch(args.repository_commit):
            raise ValueError("serial torque readback requires a 40-hex repository commit")
        if output_path == Path(args.device).expanduser().resolve():
            raise ValueError("readback output and serial device must be distinct")
        bus = STS3215Bus(
            args.device,
            baudrate=args.baudrate,
            transaction_timeout_s=args.timeout_ms / 1000.0,
        )
        informational_only = False
    else:
        bus = MockSTS3215Bus(latency_s=0.0)
        informational_only = True

    initial_disable = ErrorCode.TIMEOUT
    final_disable = ErrorCode.TIMEOUT
    halt_reason: str | None = None
    records: list[dict[str, object]] = []
    try:
        initial_disable = bus.disable_torque()
        if initial_disable is not ErrorCode.OK:
            halt_reason = f"initial torque-off failed: {initial_disable.name.lower()}"
        else:
            for wire_index, servo_id in enumerate(SERVO_SYNC_READ_IDS):
                start_ns = clock_ns()
                status, device_status, payload = bus.read_register_with_device_status(
                    servo_id, ADDR_TORQUE_ENABLE, 1
                )
                end_ns = clock_ns()
                complete = (
                    status in (ErrorCode.OK, ErrorCode.DEVICE)
                    and device_status is not None
                    and len(payload) == 1
                )
                records.append(
                    {
                        "wire_index": wire_index,
                        "logical_index": SERVO_IDS.index(servo_id),
                        "servo_id": servo_id,
                        "register_address": ADDR_TORQUE_ENABLE,
                        "response_status": status.name.lower(),
                        "device_status_raw": device_status,
                        "response_length": len(payload),
                        "torque_enable_raw": int(payload[0]) if complete else None,
                        "round_trip_ms": (end_ns - start_ns) / 1e6,
                    }
                )
                if not complete:
                    halt_reason = f"incomplete torque readback at servo {servo_id}"
                    break
    except Exception as exc:
        halt_reason = f"torque readback exception: {exc}"
    finally:
        try:
            final_disable = bus.disable_torque()
        finally:
            bus.close()

    if final_disable is not ErrorCode.OK:
        cutoff = f"final torque-off failed: {final_disable.name.lower()}"
        halt_reason = f"{halt_reason}; {cutoff}" if halt_reason else cutoff
    complete_all14 = len(records) == len(SERVO_IDS) and all(
        record["response_length"] == 1
        and record["device_status_raw"] is not None
        and record["response_status"] in ("ok", "device")
        for record in records
    )
    all_zero = complete_all14 and all(
        record["torque_enable_raw"] == 0 for record in records
    )
    checks = {
        "initial_disable_ok": initial_disable is ErrorCode.OK,
        "complete_all_14": complete_all14,
        "all_14_torque_enable_registers_zero": all_zero,
        "final_disable_ok": final_disable is ErrorCode.OK,
    }
    summary = {
        "schema_version": "open_duck_x5.torque_off_readback.v1",
        "status": "PASS" if all(checks.values()) and halt_reason is None else "FAIL",
        "backend": args.bus,
        "informational_only": informational_only,
        "review_status": "INFORMATIONAL_ONLY" if informational_only else "REVIEW_REQUIRED",
        "run_status": "HALTED" if halt_reason else "COMPLETE",
        "halt_reason": halt_reason,
        "register_address": ADDR_TORQUE_ENABLE,
        "read_order": list(SERVO_SYNC_READ_IDS),
        "records": records,
        "checks": checks,
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
            "initial_torque_off_status": initial_disable.name.lower(),
            "final_torque_off_status": final_disable.name.lower(),
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
        summary = run_readback(args)
    except (HardwareAuthorizationError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
