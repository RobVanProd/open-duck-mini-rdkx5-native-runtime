from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class Gate2ValidationError(RuntimeError):
    pass


def validate_gate2_summary(
    summary: dict[str, Any], *, moving: bool, expected_config_sha256: str
) -> None:
    try:
        environment = summary["environment"]
        realtime = environment["realtime"]
        gates = summary["gates"]
        bus_population = summary["bus_total_population"]
        failure_counts = summary["transaction_failure_counts"]
        background_threads = realtime["background_threads"]
        checks = {
            "run complete": summary["run_status"] == "COMPLETE",
            "no halt": summary["halt_reason"] is None,
            "10,000 ticks": summary["ticks"]
            == summary["ticks_requested"]
            == 10_000,
            "complete population": bus_population["observations"] == 10_000,
            "complete-sweep population": (
                bus_population["observation"] == "complete_tick_sweep"
                and bus_population["statistic"] == "sample_max_over_completed_ticks"
                and bus_population["components"]
                == [
                    "goal_sync_write_all_14",
                    "state_sync_read_0x82_all_14",
                    "extended_read_one_servo",
                ]
            ),
            "160,000 transactions": summary["transactions_expected"] == 160_000,
            "final torque off": environment["torque_off_status"] == "ok",
            "hardware authorized": environment["hardware_authorized"] is True,
            "supported": environment["suspended_or_benched"] is True,
            "movement scope": environment["moving_gate_authorized"] is moving,
            "torque scope": environment["torque_enabled"] is moving,
            "zero amplitude": environment["amplitude_rad"] == 0.0,
            "five-second home": environment["home_seconds"] == 5.0,
            "frozen config": environment["config_sha256"]
            == expected_config_sha256,
            "UART endpoint": environment["device"] == "/dev/ttyS1",
            "one megabaud": environment["baudrate"] == 1_000_000,
            "50 Hz": environment["frequency_hz"] == 50.0,
            "RT CPU": realtime["cpu"] == 7 and realtime["affinity"] == [7],
            "RT scheduler": realtime["scheduler"] == "SCHED_FIFO"
            and realtime["priority"] >= 80,
            "isolated": realtime["isolated"] is True,
            "initial affinity": realtime["initial_affinity"] == list(range(8)),
            "housekeeping": realtime["housekeeping_affinity"] == list(range(7)),
            "background isolation": all(
                7 not in thread["affinity"] for thread in background_threads
            ),
            "complete stream": gates["complete_record_stream"] is True,
            "tick p99": gates["tick_p99_at_most_21_ms"] is True
            and summary["tick_period_ms"]["p99"] <= 21.0,
            "tick p99.9": gates["tick_p99_9_at_most_22_ms"] is True
            and summary["tick_period_ms"]["p99_9"] <= 22.0,
            "bus max": gates["bus_max_under_5_ms"] is True
            and summary["bus_total_ms"]["max"] < 5.0,
            "failure rate": gates["transaction_failure_below_0_1_percent"]
            is True
            and summary["transaction_failure_percent"] < 0.1,
            "zero bursts": gates["zero_read_bursts"] is True
            and summary["read_burst_count"] == 0
            and summary["max_read_burst_ticks"] == 0,
            "zero partial": failure_counts["partial"] == 0
            and summary["partial_byte_count"] == 0,
            "zero unexpected": failure_counts["unexpected_id"] == 0
            and failure_counts["unexpected_packet"] == 0
            and summary["unexpected_packet_count"] == 0,
            "zero alarms": gates["zero_device_alarms"] is True
            and summary["device_alarm_reply_count"] == 0,
            "zero drops": environment["telemetry_records_dropped"] == 0,
            "cutoff confirmed": gates["torque_off_confirmed"] is True,
            "moving scope gate": gates["moving_gate_scope"] is moving,
            "gate candidate": gates["gate2_home_hold_candidate"] is moving,
        }
        if moving:
            checks["tracking population"] = (
                summary["tracking_absolute_error_rad"]["samples"] == 10_000
            )
    except (KeyError, TypeError) as exc:
        raise Gate2ValidationError(f"summary structure is incomplete: {exc}") from exc

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise Gate2ValidationError("summary validation failed: " + ", ".join(failed))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a frozen Gate 2 stage")
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--stage", choices=("preflight", "home_hold"), required=True)
    parser.add_argument("--expected-config-sha256", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = json.loads(args.summary.read_text(encoding="utf-8"))
        validate_gate2_summary(
            summary,
            moving=args.stage == "home_hold",
            expected_config_sha256=args.expected_config_sha256,
        )
    except (OSError, json.JSONDecodeError, Gate2ValidationError) as exc:
        print(f"result=FAIL reason={exc}")
        return 2
    print(f"result=PASS stage={args.stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
