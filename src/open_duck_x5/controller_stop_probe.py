from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from .controller import ControllerReadout, create_controller
from .hardware_guard import (
    HardwareAuthorizationError,
    add_hardware_ack_arguments,
    require_hardware_authorization,
)
from .timing import AbsoluteTicker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Controller-only B-button emergency-stop mapping probe"
    )
    parser.add_argument("--controller", choices=("xbox", "f710"), required=True)
    parser.add_argument("--ticks", type=int, default=500)
    parser.add_argument("--frequency-hz", type=float, default=50.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    add_hardware_ack_arguments(parser)
    return parser


def _validate(args: argparse.Namespace) -> None:
    if args.ticks < 2:
        raise ValueError("--ticks must be at least 2")
    if not math.isfinite(args.frequency_hz) or args.frequency_hz <= 0:
        raise ValueError("--frequency-hz must be finite and positive")
    output = args.output.expanduser().resolve()
    summary = args.summary.expanduser().resolve()
    if output == summary:
        raise ValueError("--output and --summary must be distinct")
    for path in (output, summary):
        if path.exists():
            raise ValueError(f"refuse existing evidence path: {path}")


def run_probe(args: argparse.Namespace) -> dict[str, object]:
    _validate(args)
    require_hardware_authorization(
        hardware_authorized=args.hardware_authorized,
        suspended_or_benched=args.suspended_or_benched,
        operation="controller-only emergency-stop mapping probe",
    )

    output = args.output.expanduser().resolve()
    summary_path = args.summary.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    controller = create_controller(args.controller)
    readout = ControllerReadout()
    ticker = AbsoluteTicker(period_ns=int(1e9 / args.frequency_hz))
    records: list[dict[str, object]] = []
    failure: str | None = None
    emergency_stop_tick: int | None = None
    try:
        for tick in range(args.ticks):
            tick_start_ns, _ = ticker.wait()
            controller.read_into(readout)
            age_ns = tick_start_ns - readout.timestamp_ns
            record = {
                "schema_version": "open_duck_x5.controller_stop_tick.v1",
                "tick": tick,
                "timestamp_monotonic_ns": tick_start_ns,
                "connected": bool(readout.connected),
                "sample_age_ms": age_ns / 1e6,
                "pause_toggle": bool(readout.pause_toggle),
                "emergency_stop": bool(readout.emergency_stop),
            }
            records.append(record)
            if not readout.connected or age_ns < 0 or age_ns > 250_000_000:
                failure = "controller_disconnected_or_stale"
                break
            if readout.pause_toggle:
                failure = "wrong_button_a_pause_toggle_observed"
                break
            if readout.emergency_stop:
                emergency_stop_tick = tick
                break
    finally:
        controller.close()

    if emergency_stop_tick is None and failure is None:
        failure = "b_button_emergency_stop_not_observed_before_tick_cap"
    passed = failure is None and emergency_stop_tick is not None
    with output.open("x", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")

    summary: dict[str, object] = {
        "schema_version": "open_duck_x5.controller_stop_summary.v1",
        "status": "PASS" if passed else "FAIL",
        "controller": args.controller,
        "ticks_requested": args.ticks,
        "ticks_recorded": len(records),
        "frequency_hz": args.frequency_hz,
        "emergency_stop_tick": emergency_stop_tick,
        "emergency_stop_events": sum(bool(item["emergency_stop"]) for item in records),
        "pause_toggle_events": sum(bool(item["pause_toggle"]) for item in records),
        "disconnect_or_stale_events": sum(
            not bool(item["connected"])
            or float(item["sample_age_ms"]) < 0
            or float(item["sample_age_ms"]) > 250.0
            for item in records
        ),
        "failure": failure,
        "serial_access": False,
        "servo_access": False,
        "torque_enabled": False,
        "policy_loaded": False,
        "motion": False,
        "hardware_authorized": bool(args.hardware_authorized),
        "suspended_or_benched": bool(args.suspended_or_benched),
        "output": str(output),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        summary = run_probe(args)
    except (HardwareAuthorizationError, OSError, RuntimeError, ValueError) as exc:
        print(f"controller stop probe blocked: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
