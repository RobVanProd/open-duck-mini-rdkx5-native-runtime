from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .config import DuckConfig
from .constants import HOME_RAD, JOINT_NAMES

EXPECTED_TICKS = 10_000
EXPECTED_CONFIG_SHA256 = "131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b"
EXPECTED_SOURCE_COMMIT = "__GATE4_SOURCE_COMMIT__"
EXPECTED_ARCHIVE_SHA256 = "__GATE4_ARCHIVE_SHA256__"
SINE_JOINT = "left_hip_yaw"
SINE_JOINT_INDEX = JOINT_NAMES.index(SINE_JOINT)


class Gate4ValidationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StageContract:
    name: str
    frequency_hz: float
    amplitude_rad: float
    moving: bool


STAGES = {
    "preflight": StageContract("preflight", 0.25, 0.0, False),
    "sine_0_25": StageContract("sine_0_25", 0.25, 0.03, True),
    "sine_0_5": StageContract("sine_0_5", 0.5, 0.03, True),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check(condition: bool, name: str, failures: list[str]) -> None:
    if not condition:
        failures.append(name)


def _close(left: float, right: float, *, atol: float = 1e-9) -> bool:
    return (
        math.isfinite(left)
        and math.isfinite(right)
        and math.isclose(left, right, rel_tol=0.0, abs_tol=atol)
    )


def _percentile(values: list[float], percentile: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), percentile))


def _load_config(config_path: Path, expected_config_sha256: str) -> np.ndarray:
    if _sha256(config_path) != expected_config_sha256:
        raise Gate4ValidationError("config SHA-256 does not match the frozen calibration")
    config = DuckConfig.load(config_path)
    return HOME_RAD + config.offsets_array


def validate_gate4_stage(
    *,
    timing_path: Path,
    summary_path: Path,
    config_path: Path,
    stage_name: str,
    expected_config_sha256: str = EXPECTED_CONFIG_SHA256,
    expected_ticks: int = EXPECTED_TICKS,
) -> dict[str, Any]:
    try:
        stage = STAGES[stage_name]
    except KeyError as exc:
        raise Gate4ValidationError(f"unknown frozen stage: {stage_name}") from exc

    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Gate4ValidationError(f"could not read summary: {exc}") from exc

    physical_home = _load_config(config_path, expected_config_sha256)
    failures: list[str] = []
    try:
        environment = summary["environment"]
        realtime = environment["realtime"]
        gates = summary["gates"]
        population = summary["bus_total_population"]
        failure_counts = summary["transaction_failure_counts"]
        tracking = summary["tracking_absolute_error_rad"]
        background_threads = realtime["background_threads"]
        _check(
            summary["schema_version"] == "open_duck_x5.timing_summary.v2",
            "summary schema",
            failures,
        )
        _check(
            summary["backend"] == "serial" and summary["informational_only"] is False,
            "serial evidence",
            failures,
        )
        _check(
            summary["review_status"] == "REVIEW_REQUIRED"
            and summary["hardware_gate_status"] == "REVIEW_REQUIRED",
            "review-required labels",
            failures,
        )
        _check(
            summary["run_status"] == "COMPLETE" and summary["halt_reason"] is None,
            "run complete",
            failures,
        )
        _check(
            summary["ticks"] == summary["ticks_requested"] == expected_ticks,
            "frozen tick population",
            failures,
        )
        _check(population["observations"] == expected_ticks, "complete bus population", failures)
        _check(
            population["observation"] == "complete_tick_sweep"
            and population["statistic"] == "sample_max_over_completed_ticks"
            and population["components"]
            == [
                "goal_sync_write_all_14",
                "state_sync_read_0x82_all_14",
                "extended_read_one_servo",
            ],
            "complete-sweep definition",
            failures,
        )
        _check(
            summary["transactions_expected"] == expected_ticks * 16,
            "transaction population",
            failures,
        )
        _check(environment["device"] == "/dev/ttyS1", "UART endpoint", failures)
        _check(environment["baudrate"] == 1_000_000, "one megabaud", failures)
        _check(environment["frequency_hz"] == 50.0, "50 Hz", failures)
        _check(environment["timeout_ms"] == 4.0, "four millisecond timeout", failures)
        _check(environment["home_seconds"] == 5.0, "five-second home entry", failures)
        _check(environment["watchdog_consecutive_failures"] == 2, "two-failure watchdog", failures)
        _check(environment["sine_joint"] == SINE_JOINT, "frozen sine joint", failures)
        _check(environment["sine_hz"] == stage.frequency_hz, "frozen sine frequency", failures)
        _check(
            environment["amplitude_rad"] == stage.amplitude_rad, "frozen sine amplitude", failures
        )
        _check(environment["torque_enabled"] is stage.moving, "torque scope", failures)
        _check(
            environment["moving_gate_authorized"] is stage.moving,
            "moving authorization scope",
            failures,
        )
        _check(environment["hardware_authorized"] is True, "hardware authorization", failures)
        _check(environment["suspended_or_benched"] is True, "supported robot", failures)
        _check(environment["config_sha256"] == expected_config_sha256, "frozen config", failures)
        _check(environment["torque_off_status"] == "ok", "final torque off", failures)
        _check(environment["telemetry_records_dropped"] == 0, "zero telemetry drops", failures)
        _check(realtime["cpu"] == 7 and realtime["affinity"] == [7], "RT CPU affinity", failures)
        _check(
            realtime["scheduler"] == "SCHED_FIFO" and realtime["priority"] >= 80,
            "RT scheduler",
            failures,
        )
        _check(realtime["isolated"] is True, "CPU isolation", failures)
        _check(realtime["initial_affinity"] == list(range(8)), "initial affinity", failures)
        _check(
            realtime["housekeeping_affinity"] == list(range(7)), "housekeeping affinity", failures
        )
        _check(
            all(7 not in item["affinity"] for item in background_threads),
            "background isolation",
            failures,
        )
        _check(gates["complete_record_stream"] is True, "complete record stream", failures)
        _check(gates["torque_off_confirmed"] is True, "torque-off gate", failures)
        _check(gates["realtime_verified_when_required"] is True, "real-time gate", failures)
        _check(gates["authorization_provenance"] is True, "authorization provenance", failures)
        _check(gates["moving_gate_scope"] is stage.moving, "moving scope gate", failures)
        _check(
            gates["tick_p99_at_most_21_ms"] is True and summary["tick_period_ms"]["p99"] <= 21.0,
            "tick p99",
            failures,
        )
        _check(
            gates["tick_p99_9_at_most_22_ms"] is True
            and summary["tick_period_ms"]["p99_9"] <= 22.0,
            "tick p99.9",
            failures,
        )
        _check(
            gates["bus_max_under_5_ms"] is True and summary["bus_total_ms"]["max"] < 5.0,
            "bus maximum",
            failures,
        )
        _check(
            gates["transaction_failure_below_0_1_percent"] is True
            and summary["transaction_failure_rate"] < 0.001,
            "failure rate",
            failures,
        )
        _check(
            gates["zero_read_bursts"] is True
            and summary["read_burst_count"] == 0
            and summary["max_read_burst_ticks"] == 0,
            "zero read bursts",
            failures,
        )
        _check(
            gates["zero_device_alarms"] is True and summary["device_alarm_reply_count"] == 0,
            "zero device alarms",
            failures,
        )
        _check(summary["voltage_alarm_reply_count"] == 0, "zero voltage alarms", failures)
        _check(
            failure_counts["partial"] == 0 and summary["partial_byte_count"] == 0,
            "zero partial data",
            failures,
        )
        _check(
            failure_counts["unexpected_id"] == 0
            and failure_counts["unexpected_packet"] == 0
            and summary["unexpected_packet_count"] == 0,
            "zero unexpected packets",
            failures,
        )
        _check(gates["gate2_home_hold_candidate"] is False, "not Gate 2", failures)
        if stage.moving:
            _check(gates["gate4_sine_candidate"] is True, "Gate 4 candidate", failures)
            _check(summary["tracking_joint_index"] == SINE_JOINT_INDEX, "tracking joint", failures)
            _check(tracking["samples"] == expected_ticks, "complete tracking population", failures)
            _check(
                gates["tracking_p95_at_most_0_011_rad"] is True and tracking["p95"] <= 0.011,
                "tracking p95",
                failures,
            )
        else:
            _check(gates["gate4_sine_candidate"] is False, "preflight is not Gate 4", failures)
            _check(tracking["samples"] == 0, "preflight has no tracking population", failures)
    except (KeyError, TypeError) as exc:
        raise Gate4ValidationError(f"summary structure is incomplete: {exc}") from exc

    tick_periods: list[float] = []
    bus_totals: list[float] = []
    tracking_errors: list[float] = []
    raw_failures = 0
    burst_count = 0
    max_burst = 0
    current_burst = 0
    previous_timestamp = -1
    row_count = 0
    try:
        with timing_path.open("r", encoding="utf-8") as handle:
            for row_count, line in enumerate(handle, start=1):
                record = json.loads(line)
                tick = row_count - 1
                _check(
                    record.get("schema_version") == "open_duck_x5.timing_tick.v2",
                    f"row {tick} schema",
                    failures,
                )
                _check(record.get("tick") == tick, f"row {tick} sequence", failures)
                timestamp = int(record["timestamp_monotonic_ns"])
                _check(timestamp > previous_timestamp, f"row {tick} monotonic timestamp", failures)
                previous_timestamp = timestamp
                tick_period = record["tick_period_ms"]
                if tick == 0:
                    _check(tick_period is None, "first tick has no period", failures)
                else:
                    period_value = float(tick_period)
                    _check(
                        math.isfinite(period_value) and period_value > 0,
                        f"row {tick} tick period",
                        failures,
                    )
                    tick_periods.append(period_value)
                serial = record["serial"]
                extended = record["extended"]
                motion = record["motion"]
                statuses = list(serial["per_servo_status"])
                stale = list(serial["stale"])
                device_status = list(serial["per_servo_device_status"])
                targets = list(motion["target_positions_rad"])
                actual = list(motion["actual_positions_rad"])
                absolute = list(motion["absolute_error_rad"])
                _check(
                    len(statuses) == len(stale) == len(device_status) == 14,
                    f"row {tick} servo vectors",
                    failures,
                )
                _check(
                    len(targets) == len(actual) == len(absolute) == 14,
                    f"row {tick} motion vectors",
                    failures,
                )
                bus_total = float(serial["bus_total_ms"])
                _check(
                    math.isfinite(bus_total) and bus_total >= 0, f"row {tick} bus time", failures
                )
                bus_totals.append(bus_total)
                _check(int(serial["partial_bytes"]) == 0, f"row {tick} partial bytes", failures)
                _check(
                    int(serial["unexpected_packets"]) == 0,
                    f"row {tick} unexpected packets",
                    failures,
                )
                _check(
                    all(int(value) == 0 for value in device_status),
                    f"row {tick} device alarm",
                    failures,
                )
                _check(
                    int(extended["device_status_raw"]) == 0, f"row {tick} extended alarm", failures
                )
                group_failed = any(status != "ok" for status in statuses)
                if group_failed:
                    current_burst += 1
                    max_burst = max(max_burst, current_burst)
                else:
                    if current_burst >= 2:
                        burst_count += 1
                    current_burst = 0
                raw_failures += sum(status != "ok" for status in statuses)
                raw_failures += serial["write_status"] != "ok"
                raw_failures += extended["status"] != "ok"
                raw_failures += int(serial["unexpected_packets"])
                expected = physical_home.copy()
                expected[SINE_JOINT_INDEX] += stage.amplitude_rad * math.sin(
                    2.0 * math.pi * stage.frequency_hz * tick / 50.0
                )
                for joint_index, (target, expected_target, measured, error) in enumerate(
                    zip(targets, expected, actual, absolute, strict=True)
                ):
                    target_value = float(target)
                    measured_value = float(measured)
                    error_value = float(error)
                    _check(
                        _close(target_value, float(expected_target)),
                        f"row {tick} target {joint_index}",
                        failures,
                    )
                    _check(
                        _close(error_value, abs(measured_value - target_value)),
                        f"row {tick} error {joint_index}",
                        failures,
                    )
                if stage.moving:
                    _check(
                        statuses[SINE_JOINT_INDEX] == "ok" and stale[SINE_JOINT_INDEX] is False,
                        f"row {tick} tracking freshness",
                        failures,
                    )
                    tracking_errors.append(float(absolute[SINE_JOINT_INDEX]))
    except (
        OSError,
        json.JSONDecodeError,
        IndexError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise Gate4ValidationError(f"timing stream is invalid: {exc}") from exc

    if current_burst >= 2:
        burst_count += 1
    _check(row_count == expected_ticks, "raw row population", failures)
    _check(len(tick_periods) == expected_ticks - 1, "tick-period population", failures)
    _check(len(bus_totals) == expected_ticks, "bus-time population", failures)
    _check(raw_failures == summary.get("transactions_failed"), "raw failure count", failures)
    _check(burst_count == 0 and max_burst == 0, "raw zero read bursts", failures)
    _check(summary.get("jsonl_sha256") == _sha256(timing_path), "raw JSONL SHA-256", failures)
    if tick_periods:
        _check(
            _close(
                _percentile(tick_periods, 99), float(summary["tick_period_ms"]["p99"]), atol=1e-7
            ),
            "raw tick p99",
            failures,
        )
        _check(
            _close(
                _percentile(tick_periods, 99.9),
                float(summary["tick_period_ms"]["p99_9"]),
                atol=1e-7,
            ),
            "raw tick p99.9",
            failures,
        )
    if bus_totals:
        _check(
            _close(max(bus_totals), float(summary["bus_total_ms"]["max"]), atol=1e-9),
            "raw bus maximum",
            failures,
        )
    if stage.moving and tracking_errors:
        _check(
            _close(
                _percentile(tracking_errors, 95),
                float(summary["tracking_absolute_error_rad"]["p95"]),
                atol=1e-9,
            ),
            "raw tracking p95",
            failures,
        )

    if failures:
        unique = list(dict.fromkeys(failures))
        preview = ", ".join(unique[:20])
        if len(unique) > 20:
            preview += f", ... ({len(unique)} failed checks)"
        raise Gate4ValidationError("stage validation failed: " + preview)

    return {
        "stage": stage.name,
        "ticks": expected_ticks,
        "frequency_hz": stage.frequency_hz,
        "amplitude_rad": stage.amplitude_rad,
        "moving": stage.moving,
        "timing_sha256": _sha256(timing_path),
        "summary_sha256": _sha256(summary_path),
        "tick_p99_ms": summary["tick_period_ms"]["p99"],
        "tick_p99_9_ms": summary["tick_period_ms"]["p99_9"],
        "bus_max_ms": summary["bus_total_ms"]["max"],
        "transaction_failure_percent": summary["transaction_failure_percent"],
        "read_burst_count": summary["read_burst_count"],
        "tracking_p95_rad": summary["tracking_absolute_error_rad"]["p95"],
        "torque_off_status": summary["environment"]["torque_off_status"],
    }


def _verify_checksum_manifest(run_root: Path) -> None:
    manifest_path = run_root / "sha256sums.txt"
    try:
        entries = manifest_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise Gate4ValidationError(f"could not read checksum manifest: {exc}") from exc
    if not entries:
        raise Gate4ValidationError("checksum manifest is empty")
    for line in entries:
        try:
            digest, relative = line.split(None, 1)
        except ValueError as exc:
            raise Gate4ValidationError("checksum manifest line is malformed") from exc
        relative = relative.strip()
        if relative.startswith("*"):
            relative = relative[1:]
        path = (run_root / relative).resolve()
        if run_root.resolve() not in path.parents:
            raise Gate4ValidationError("checksum manifest escapes the run root")
        if _sha256(path) != digest:
            raise Gate4ValidationError(f"checksum mismatch: {relative}")


def validate_gate4_run(
    *,
    run_root: Path,
    config_path: Path,
    expected_source_commit: str = EXPECTED_SOURCE_COMMIT,
    expected_archive_sha256: str = EXPECTED_ARCHIVE_SHA256,
    expected_config_sha256: str = EXPECTED_CONFIG_SHA256,
    check_manifest: bool = False,
) -> dict[str, Any]:
    stages = {
        name: validate_gate4_stage(
            timing_path=run_root / name / "timing.jsonl",
            summary_path=run_root / name / "summary.json",
            config_path=config_path,
            stage_name=name,
            expected_config_sha256=expected_config_sha256,
        )
        for name in STAGES
    }
    try:
        metadata = json.loads((run_root / "metadata.json").read_text(encoding="utf-8"))
        checks = {
            "runner schema": metadata["schema_version"] == "open_duck_x5.gate4_runner.v1",
            "source commit": metadata["source_commit"] == expected_source_commit,
            "source archive": metadata["source_archive_sha256"] == expected_archive_sha256,
            "config": metadata["config_sha256"] == expected_config_sha256,
            "UART": metadata["serial_device"] == "/dev/ttyS1",
            "joint": metadata["sine_joint"] == SINE_JOINT,
            "ticks": metadata["ticks_per_stage"] == EXPECTED_TICKS,
            "home entry": metadata["home_seconds"] == 5.0,
            "amplitude": metadata["amplitude_rad"] == 0.03,
            "frequency order": metadata["frequency_order_hz"] == [0.25, 0.5],
            "no policy": metadata["policy_loaded"] is False,
            "preflight torque off": metadata["preflight_torque_enable_requested"] is False,
            "moving torque": metadata["sine_torque_enable_requested"] is True,
            "all probes": all(
                metadata[name] == 0
                for name in (
                    "preflight_probe_status",
                    "sine_0_25_probe_status",
                    "sine_0_5_probe_status",
                )
            ),
            "all stage validators": all(
                metadata[name] == 0
                for name in (
                    "preflight_validation_status",
                    "sine_0_25_validation_status",
                    "sine_0_5_validation_status",
                )
            ),
            "governor restored": metadata["governor_restore_status"] == 0,
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise Gate4ValidationError(f"runner metadata is incomplete: {exc}") from exc
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise Gate4ValidationError("run validation failed: " + ", ".join(failed))
    try:
        governor_before = (run_root / "governor-before.txt").read_text(encoding="utf-8").strip()
        governor_during = (run_root / "governor-during.txt").read_text(encoding="utf-8").strip()
        governor_after = (run_root / "governor-after.txt").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise Gate4ValidationError(f"governor evidence is incomplete: {exc}") from exc
    if (governor_before, governor_during, governor_after) != (
        "schedutil",
        "performance",
        "schedutil",
    ):
        raise Gate4ValidationError(
            "governor evidence does not show schedutil/performance/schedutil"
        )
    if check_manifest:
        _verify_checksum_manifest(run_root)
    return {
        "schema_version": "open_duck_x5.gate4_review.v1",
        "status": "REVIEW_CANDIDATE",
        "source_commit": expected_source_commit,
        "source_archive_sha256": expected_archive_sha256,
        "config_sha256": expected_config_sha256,
        "serial_device": "/dev/ttyS1",
        "sine_joint": SINE_JOINT,
        "policy_loaded": False,
        "stage_order": list(STAGES),
        "stages": stages,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Independently validate frozen Gate 4 evidence")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--stage", choices=tuple(STAGES))
    mode.add_argument("--run-root", type=Path)
    parser.add_argument("--timing", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-manifest", action="store_true")
    parser.add_argument("--expected-source-commit", default=EXPECTED_SOURCE_COMMIT)
    parser.add_argument("--expected-archive-sha256", default=EXPECTED_ARCHIVE_SHA256)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.stage is not None:
            if args.timing is None or args.summary is None:
                raise Gate4ValidationError("--stage requires --timing and --summary")
            result = validate_gate4_stage(
                timing_path=args.timing,
                summary_path=args.summary,
                config_path=args.config,
                stage_name=args.stage,
            )
        else:
            result = validate_gate4_run(
                run_root=args.run_root,
                config_path=args.config,
                expected_source_commit=args.expected_source_commit,
                expected_archive_sha256=args.expected_archive_sha256,
                check_manifest=args.check_manifest,
            )
        if args.output is not None:
            args.output.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
    except (Gate4ValidationError, OSError) as exc:
        print(f"result=FAIL reason={exc}")
        return 2
    print(f"result=PASS scope={args.stage or 'complete_run'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
