from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sys
from pathlib import Path
from typing import Any

from .bus import ErrorCode, MockSTS3215Bus, STS3215Bus
from .bus.sts3215 import (
    ADDR_LOCK,
    ADDR_MAX_INPUT_VOLTAGE,
    ADDR_PRESENT_VOLTAGE,
)
from .clock import clock_ns
from .constants import SERVO_SYNC_READ_IDS
from .hardware_guard import (
    HardwareAuthorizationError,
    add_hardware_ack_arguments,
    require_hardware_authorization,
)

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_MAX_RAW = 80
EXPECTED_MIN_RAW = 40
TARGET_MAX_RAW = 84
VOLTAGE_ERROR_MASK = 0x01


class ConfigurationHalt(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Guarded torque-off STS3215 maximum-voltage alarm update to 8.4 V"
    )
    parser.add_argument("--bus", choices=("mock", "serial"), default="mock")
    parser.add_argument("--device", default="/dev/ttyS1")
    parser.add_argument("--baudrate", type=int, default=1_000_000)
    parser.add_argument("--timeout-ms", type=float, default=10.0)
    parser.add_argument("--repository-commit", default="NOT_APPLICABLE")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--journal",
        type=Path,
        help="append-only operation journal (default: OUTPUT with .jsonl suffix)",
    )
    parser.add_argument(
        "--confirm-max-voltage-8v4",
        action="store_true",
        help="Confirm the reviewed request to change only register 14 from 80 to 84.",
    )
    add_hardware_ack_arguments(parser)
    return parser


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("x", encoding="utf-8", newline="\n")
        self.sequence = 0

    def write(self, event: str, **fields: object) -> None:
        record = {
            "sequence": self.sequence,
            "monotonic_ns": clock_ns(),
            "event": event,
            **fields,
        }
        self._handle.write(json.dumps(record, sort_keys=True) + "\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self.sequence += 1

    def close(self) -> None:
        self._handle.close()


def _status_name(status: ErrorCode) -> str:
    return status.name.lower()


def _read(
    bus: MockSTS3215Bus | STS3215Bus,
    journal: Journal,
    servo_id: int,
    address: int,
    length: int,
) -> tuple[ErrorCode, int | None, bytes]:
    start_ns = clock_ns()
    status, device_status, data = bus.read_register_with_device_status(
        servo_id, address, length
    )
    journal.write(
        "read",
        servo_id=servo_id,
        address=address,
        length=length,
        transport_status=_status_name(status),
        device_status_raw=device_status,
        data=list(data),
        round_trip_ms=(clock_ns() - start_ns) / 1e6,
    )
    return status, device_status, data


def _require_read(
    bus: MockSTS3215Bus | STS3215Bus,
    journal: Journal,
    servo_id: int,
    address: int,
    length: int,
) -> tuple[int, bytes]:
    status, device_status, data = _read(bus, journal, servo_id, address, length)
    if status is not ErrorCode.OK or device_status is None or len(data) != length:
        raise ConfigurationHalt(
            f"servo {servo_id} register {address} read failed: "
            f"transport={_status_name(status)} length={len(data)}/{length}"
        )
    return device_status, data


def _write(
    bus: MockSTS3215Bus | STS3215Bus,
    journal: Journal,
    servo_id: int,
    address: int,
    data: bytes,
) -> tuple[ErrorCode, int | None]:
    start_ns = clock_ns()
    status, device_status = bus.write_register_with_device_status(
        servo_id, address, data
    )
    journal.write(
        "write",
        servo_id=servo_id,
        address=address,
        data=list(data),
        transport_status=_status_name(status),
        device_status_raw=device_status,
        round_trip_ms=(clock_ns() - start_ns) / 1e6,
    )
    return status, device_status


def _read_limits(
    bus: MockSTS3215Bus | STS3215Bus, journal: Journal, servo_id: int
) -> dict[str, int]:
    device_status, data = _require_read(
        bus, journal, servo_id, ADDR_MAX_INPUT_VOLTAGE, 2
    )
    return {
        "servo_id": servo_id,
        "device_status_raw": device_status,
        "max_voltage_raw": int(data[0]),
        "min_voltage_raw": int(data[1]),
    }


def _read_voltage_status(
    bus: MockSTS3215Bus | STS3215Bus, journal: Journal, servo_id: int
) -> dict[str, int | float | bool]:
    device_status, data = _require_read(
        bus, journal, servo_id, ADDR_PRESENT_VOLTAGE, 1
    )
    raw = int(data[0])
    return {
        "servo_id": servo_id,
        "device_status_raw": device_status,
        "voltage_alarm": bool(device_status & VOLTAGE_ERROR_MASK),
        "present_voltage_raw": raw,
        "present_voltage_v": raw * 0.1,
    }


def _relock(
    bus: MockSTS3215Bus | STS3215Bus,
    journal: Journal,
    servo_id: int,
    unlocked: set[int],
    write_attempts: dict[str, int],
    *,
    emergency: bool = False,
) -> None:
    write_attempts["lock"] += 1
    status, _ = _write(bus, journal, servo_id, ADDR_LOCK, b"\x01")
    _, lock_data = _require_read(bus, journal, servo_id, ADDR_LOCK, 1)
    if lock_data != b"\x01":
        raise ConfigurationHalt(
            f"servo {servo_id} EEPROM relock did not verify after "
            f"{_status_name(status)} acknowledgement: {lock_data.hex()}"
        )
    if status is not ErrorCode.OK:
        journal.write(
            "write_ack_recovered_by_readback",
            servo_id=servo_id,
            address=ADDR_LOCK,
            transport_status=_status_name(status),
            verified_data=[1],
        )
    unlocked.discard(servo_id)
    journal.write(
        "emergency_relock_verified" if emergency else "relock_verified",
        servo_id=servo_id,
    )


def _configure_servo(
    bus: MockSTS3215Bus | STS3215Bus,
    journal: Journal,
    servo_id: int,
    unlocked: set[int],
    write_attempts: dict[str, int],
) -> dict[str, Any]:
    write_attempts["lock"] += 1
    # The unlock instruction may reach the servo even if its acknowledgement
    # is lost.  Track the unit as possibly unlocked before transmission so the
    # finally path always attempts a relock.
    unlocked.add(servo_id)
    unlock_status, _ = _write(bus, journal, servo_id, ADDR_LOCK, b"\x00")
    _, lock_data = _require_read(bus, journal, servo_id, ADDR_LOCK, 1)
    if lock_data != b"\x00":
        raise ConfigurationHalt(
            f"servo {servo_id} EEPROM unlock did not verify after "
            f"{_status_name(unlock_status)} acknowledgement: {lock_data.hex()}"
        )
    if unlock_status is not ErrorCode.OK:
        journal.write(
            "write_ack_recovered_by_readback",
            servo_id=servo_id,
            address=ADDR_LOCK,
            transport_status=_status_name(unlock_status),
            verified_data=[0],
        )

    write_attempts["maximum_voltage"] += 1
    limit_status, _ = _write(
        bus,
        journal,
        servo_id,
        ADDR_MAX_INPUT_VOLTAGE,
        bytes((TARGET_MAX_RAW,)),
    )
    limits = _read_limits(bus, journal, servo_id)
    if (
        limits["max_voltage_raw"] != TARGET_MAX_RAW
        or limits["min_voltage_raw"] != EXPECTED_MIN_RAW
    ):
        raise ConfigurationHalt(
            f"servo {servo_id} limit write did not verify after "
            f"{_status_name(limit_status)} acknowledgement: "
            f"max={limits['max_voltage_raw']} min={limits['min_voltage_raw']}"
        )
    if limit_status is not ErrorCode.OK:
        journal.write(
            "write_ack_recovered_by_readback",
            servo_id=servo_id,
            address=ADDR_MAX_INPUT_VOLTAGE,
            transport_status=_status_name(limit_status),
            verified_data=[TARGET_MAX_RAW, EXPECTED_MIN_RAW],
        )
    _relock(bus, journal, servo_id, unlocked, write_attempts)

    voltage = _read_voltage_status(bus, journal, servo_id)
    if voltage["voltage_alarm"]:
        raise ConfigurationHalt(
            f"servo {servo_id} voltage alarm remained asserted after verified 8.4 V update"
        )
    journal.write("servo_update_verified", servo_id=servo_id)
    return {"limits": limits, "voltage": voltage}


def _verify_existing_target(
    bus: MockSTS3215Bus | STS3215Bus,
    journal: Journal,
    servo_id: int,
    limits: dict[str, int],
    unlocked: set[int],
    write_attempts: dict[str, int],
) -> dict[str, Any]:
    _, lock_data = _require_read(bus, journal, servo_id, ADDR_LOCK, 1)
    if lock_data == b"\x00":
        unlocked.add(servo_id)
        journal.write("preexisting_target_found_unlocked", servo_id=servo_id)
        _relock(bus, journal, servo_id, unlocked, write_attempts, emergency=True)
    elif lock_data != b"\x01":
        raise ConfigurationHalt(
            f"servo {servo_id} has unexpected EEPROM lock value {lock_data.hex()}"
        )
    voltage = _read_voltage_status(bus, journal, servo_id)
    if voltage["voltage_alarm"]:
        raise ConfigurationHalt(
            f"servo {servo_id} retained voltage alarm with existing 8.4 V limit"
        )
    journal.write("preexisting_target_verified", servo_id=servo_id)
    return {
        "servo_id": servo_id,
        "lock_raw": 1,
        "limits": limits,
        "voltage": voltage,
    }


def _write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(
        (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    temporary.replace(path)


def run_configuration(args: argparse.Namespace) -> dict[str, Any]:
    if not args.confirm_max_voltage_8v4:
        raise ValueError("blocked: pass --confirm-max-voltage-8v4 for this reviewed EEPROM change")
    if args.baudrate <= 0 or args.timeout_ms <= 0:
        raise ValueError("baudrate and timeout must be positive")

    output_path = args.output.expanduser().resolve()
    journal_path = (
        args.journal.expanduser().resolve()
        if args.journal is not None
        else output_path.with_suffix(".jsonl")
    )
    if output_path == journal_path:
        raise ValueError("summary output and journal must be distinct")
    if output_path.exists() or journal_path.exists():
        raise ValueError("configuration evidence paths must not already exist")

    if args.bus == "serial":
        require_hardware_authorization(
            hardware_authorized=args.hardware_authorized,
            suspended_or_benched=args.suspended_or_benched,
            operation="all-servo maximum-voltage alarm EEPROM update to 8.4 V",
        )
        if not COMMIT_RE.fullmatch(args.repository_commit):
            raise ValueError("serial voltage-limit update requires a 40-hex repository commit")
        device_path = Path(args.device).expanduser().resolve()
        if output_path == device_path or journal_path == device_path:
            raise ValueError("configuration evidence paths and serial device must be distinct")
        bus: MockSTS3215Bus | STS3215Bus = STS3215Bus(
            args.device,
            baudrate=args.baudrate,
            transaction_timeout_s=args.timeout_ms / 1000.0,
        )
        informational_only = False
    else:
        bus = MockSTS3215Bus(latency_s=0.0)
        informational_only = True

    journal = Journal(journal_path)
    journal.write(
        "start",
        backend=args.bus,
        repository_commit=args.repository_commit,
        target_max_voltage_raw=TARGET_MAX_RAW,
    )
    initial_torque_off = ErrorCode.TIMEOUT
    final_torque_off = ErrorCode.TIMEOUT
    halt_reason: str | None = None
    finding = "configuration_not_started"
    preflight: list[dict[str, int]] = []
    preexisting_verified: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    final_records: list[dict[str, Any]] = []
    unlocked: set[int] = set()
    write_attempts = {"maximum_voltage": 0, "lock": 0}

    try:
        initial_torque_off = bus.disable_torque()
        journal.write("initial_torque_off", status=_status_name(initial_torque_off))
        if initial_torque_off is not ErrorCode.OK:
            raise ConfigurationHalt(
                f"failed to issue initial all-servo torque off: {_status_name(initial_torque_off)}"
            )

        preflight = [
            _read_limits(bus, journal, servo_id) for servo_id in SERVO_SYNC_READ_IDS
        ]
        observed = {
            (record["max_voltage_raw"], record["min_voltage_raw"])
            for record in preflight
        }
        allowed = {
            (EXPECTED_MAX_RAW, EXPECTED_MIN_RAW),
            (TARGET_MAX_RAW, EXPECTED_MIN_RAW),
        }
        if not observed.issubset(allowed):
            finding = "preflight_mismatch"
            raise ConfigurationHalt(
                "preflight limits were outside the recoverable 8.0/4.0 V and 8.4/4.0 V states: "
                f"{sorted(observed)}"
            )
        preflight_by_id = {record["servo_id"]: record for record in preflight}
        already_targeted = [
            servo_id
            for servo_id in SERVO_SYNC_READ_IDS
            if preflight_by_id[servo_id]["max_voltage_raw"] == TARGET_MAX_RAW
        ]
        pending = [
            servo_id
            for servo_id in SERVO_SYNC_READ_IDS
            if preflight_by_id[servo_id]["max_voltage_raw"] == EXPECTED_MAX_RAW
        ]
        for servo_id in already_targeted:
            preexisting_verified.append(
                _verify_existing_target(
                    bus,
                    journal,
                    servo_id,
                    preflight_by_id[servo_id],
                    unlocked,
                    write_attempts,
                )
            )
        if not pending:
            finding = "already_configured"
        else:
            for servo_id in pending:
                # Each successful servo update consists of unlock, one limit
                # write, verified relock, and a voltage-status read. The first
                # pending ID is the canary for a fresh or resumed run.
                update = _configure_servo(
                    bus, journal, servo_id, unlocked, write_attempts
                )
                updates.append({"servo_id": servo_id, **update})
            finding = (
                "resumed_and_configured_all14"
                if already_targeted
                else "configured_all14"
            )

        for servo_id in SERVO_SYNC_READ_IDS:
            limits = _read_limits(bus, journal, servo_id)
            voltage = _read_voltage_status(bus, journal, servo_id)
            final_records.append({"servo_id": servo_id, "limits": limits, "voltage": voltage})
        if any(
            record["limits"]["max_voltage_raw"] != TARGET_MAX_RAW
            or record["limits"]["min_voltage_raw"] != EXPECTED_MIN_RAW
            or record["voltage"]["voltage_alarm"]
            for record in final_records
        ):
            finding = "final_verification_failed"
            raise ConfigurationHalt("final all-servo limit/status verification failed")
    except ConfigurationHalt as exc:
        halt_reason = str(exc)
        if finding == "configuration_not_started":
            finding = "configuration_halted"
        journal.write("halt", reason=halt_reason, finding=finding)
    except Exception as exc:  # preserve evidence and fail closed on an unexpected path
        halt_reason = f"unexpected configuration exception: {exc}"
        finding = "configuration_exception"
        journal.write("halt", reason=halt_reason, finding=finding)
    finally:
        for servo_id in tuple(unlocked):
            try:
                _relock(
                    bus,
                    journal,
                    servo_id,
                    unlocked,
                    write_attempts,
                    emergency=True,
                )
            except Exception as exc:
                relock_failure = f"servo {servo_id} emergency relock failed: {exc}"
                halt_reason = f"{halt_reason}; {relock_failure}" if halt_reason else relock_failure
                finding = "emergency_relock_failed"
                journal.write("emergency_relock_failed", servo_id=servo_id, reason=str(exc))
        if initial_torque_off is ErrorCode.OK and not final_records:
            for servo_id in SERVO_SYNC_READ_IDS:
                try:
                    limits = _read_limits(bus, journal, servo_id)
                    voltage = _read_voltage_status(bus, journal, servo_id)
                    final_records.append(
                        {"servo_id": servo_id, "limits": limits, "voltage": voltage}
                    )
                except Exception as exc:
                    journal.write(
                        "final_audit_read_failed", servo_id=servo_id, reason=str(exc)
                    )
        try:
            final_torque_off = bus.disable_torque()
            journal.write("final_torque_off", status=_status_name(final_torque_off))
        except Exception as exc:
            failure = f"final torque-off exception: {exc}"
            halt_reason = f"{halt_reason}; {failure}" if halt_reason else failure
            finding = "final_torque_off_failed"
        finally:
            try:
                bus.close()
            except Exception as exc:
                failure = f"bus close exception: {exc}"
                halt_reason = f"{halt_reason}; {failure}" if halt_reason else failure
                finding = "configuration_exception"
                journal.write("close_failed", reason=str(exc))
            finally:
                journal.write("closed")
                journal.close()

    if final_torque_off is not ErrorCode.OK:
        failure = f"final torque-off failed: {_status_name(final_torque_off)}"
        halt_reason = f"{halt_reason}; {failure}" if halt_reason else failure
        finding = "final_torque_off_failed"

    run_status = "COMPLETE" if halt_reason is None else "HALTED"
    summary: dict[str, Any] = {
        "schema_version": "open_duck_x5.voltage_limit_configuration.v1",
        "backend": args.bus,
        "informational_only": informational_only,
        "review_status": "INFORMATIONAL_ONLY" if informational_only else "REVIEW_REQUIRED",
        "hardware_gate_status": "NOT_ADVANCED_CONFIGURATION_ONLY",
        "run_status": run_status,
        "halt_reason": halt_reason,
        "finding": finding,
        "read_order": list(SERVO_SYNC_READ_IDS),
        "canary_servo_id": next(
            (
                record["servo_id"]
                for record in preflight
                if record["max_voltage_raw"] == EXPECTED_MAX_RAW
            ),
            None,
        ),
        "volts_per_count": 0.1,
        "expected_initial": {
            "max_voltage_raw": EXPECTED_MAX_RAW,
            "min_voltage_raw": EXPECTED_MIN_RAW,
        },
        "target": {
            "max_voltage_raw": TARGET_MAX_RAW,
            "min_voltage_raw": EXPECTED_MIN_RAW,
        },
        "preflight": preflight,
        "preexisting_verified": preexisting_verified,
        "updates": updates,
        "final_records": final_records,
        "journal": str(journal_path),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "device": bus.device,
            "baudrate": bus.baudrate,
            "timeout_ms": args.timeout_ms,
            "repository_commit": args.repository_commit,
            "hardware_authorized": bool(args.hardware_authorized),
            "suspended_or_benched": bool(args.suspended_or_benched),
            "eeprom_confirmation": bool(args.confirm_max_voltage_8v4),
        },
        "safety": {
            "torque_enable_requested": False,
            "goal_position_write_count": 0,
            "minimum_voltage_write_count": 0,
            "maximum_voltage_write_attempt_count": write_attempts["maximum_voltage"],
            "lock_control_write_attempt_count": write_attempts["lock"],
            "initial_torque_off_status": _status_name(initial_torque_off),
            "final_torque_off_status": _status_name(final_torque_off),
            "all_known_unlocked_servos_relocked": not unlocked,
        },
    }
    _write_summary(output_path, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        summary = run_configuration(args)
    except (HardwareAuthorizationError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["run_status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
