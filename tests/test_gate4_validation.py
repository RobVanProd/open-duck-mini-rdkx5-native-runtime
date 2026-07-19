from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest

from open_duck_x5.constants import HOME_RAD
from open_duck_x5.gate4_validation import (
    EXPECTED_ARCHIVE_SHA256,
    EXPECTED_SOURCE_COMMIT,
    Gate4ValidationError,
    validate_gate4_stage,
)


def test_gate4_validator_freezes_source_archive_identity() -> None:
    assert EXPECTED_SOURCE_COMMIT == "c5f27598b68fa7d69d81d0675f50a06435ecdaf8"
    assert (
        EXPECTED_ARCHIVE_SHA256
        == "5ee4aa30fb11e411ec7cea797c70ebf5aa53d1278e8c873544825253b193ffc8"
    )


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = Path(__file__).parents[1]
    config = root / "duck_config.example.json"
    config_sha = hashlib.sha256(config.read_bytes()).hexdigest()
    timing = tmp_path / "timing.jsonl"
    tick_periods = [20.0, 20.0, 20.0]
    records = []
    tracking_errors = []
    for tick in range(4):
        targets = HOME_RAD.copy()
        targets[0] += 0.03 * math.sin(2.0 * math.pi * 0.25 * tick / 50.0)
        actual = targets.copy()
        actual[0] -= 0.001
        absolute = np.abs(actual - targets)
        tracking_errors.append(float(absolute[0]))
        records.append(
            {
                "schema_version": "open_duck_x5.timing_tick.v2",
                "tick": tick,
                "timestamp_monotonic_ns": 1_000_000_000 + tick * 20_000_000,
                "tick_period_ms": None if tick == 0 else tick_periods[tick - 1],
                "release_lateness_ms": 0.001,
                "serial": {
                    "group_round_trip_ms": 2.5,
                    "extended_round_trip_ms": 0.5,
                    "bus_total_ms": 3.0,
                    "write_status": "ok",
                    "per_servo_status": ["ok"] * 14,
                    "per_servo_device_status": [0] * 14,
                    "stale": [False] * 14,
                    "partial_bytes": 0,
                    "unexpected_packets": 0,
                },
                "extended": {
                    "servo_id": 20,
                    "status": "ok",
                    "device_status_raw": 0,
                },
                "motion": {
                    "target_positions_rad": targets.tolist(),
                    "actual_positions_rad": actual.tolist(),
                    "absolute_error_rad": absolute.tolist(),
                },
            }
        )
    timing.write_text(
        "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
    )
    source = (
        root / "artifacts/gates/phase_7_hardware/gate_2_all14_home/cpu_governor_ab/summary.json"
    )
    summary = copy.deepcopy(json.loads(source.read_text(encoding="utf-8")))
    summary["ticks"] = summary["ticks_requested"] = 4
    summary["bus_total_population"]["observations"] = 4
    summary["transactions_expected"] = 64
    summary["transactions_failed"] = 0
    summary["transaction_failure_rate"] = 0.0
    summary["transaction_failure_percent"] = 0.0
    summary["tick_period_ms"].update(min=20.0, mean=20.0, p95=20.0, p99=20.0, p99_9=20.0, max=20.0)
    summary["bus_total_ms"].update(min=3.0, mean=3.0, p95=3.0, p99=3.0, p99_9=3.0, max=3.0)
    tracking = summary["tracking_absolute_error_rad"]
    tracking.update(
        samples=4,
        min=min(tracking_errors),
        mean=float(np.mean(tracking_errors)),
        p95=float(np.percentile(tracking_errors, 95)),
        p99=float(np.percentile(tracking_errors, 99)),
        p99_9=float(np.percentile(tracking_errors, 99.9)),
        max=max(tracking_errors),
    )
    summary["tracking_joint_index"] = 0
    environment = summary["environment"]
    environment.update(
        device="/dev/ttyS1",
        baudrate=1_000_000,
        frequency_hz=50.0,
        timeout_ms=4.0,
        home_seconds=5.0,
        sine_hz=0.25,
        amplitude_rad=0.03,
        sine_joint="left_hip_yaw",
        torque_enabled=True,
        moving_gate_authorized=True,
        hardware_authorized=True,
        suspended_or_benched=True,
        config_sha256=config_sha,
        torque_off_status="ok",
        telemetry_records_dropped=0,
    )
    gates = summary["gates"]
    gates.update(
        complete_record_stream=True,
        torque_off_confirmed=True,
        realtime_verified_when_required=True,
        authorization_provenance=True,
        moving_gate_scope=True,
        gate2_home_hold_candidate=False,
        gate4_sine_candidate=True,
        tick_p99_at_most_21_ms=True,
        tick_p99_9_at_most_22_ms=True,
        bus_max_under_5_ms=True,
        transaction_failure_below_0_1_percent=True,
        zero_read_bursts=True,
        zero_device_alarms=True,
        tracking_p95_at_most_0_011_rad=True,
    )
    summary["jsonl_sha256"] = hashlib.sha256(timing.read_bytes()).hexdigest()
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    return timing, summary_path, config


def test_gate4_validator_recomputes_raw_sine_and_statistics(tmp_path: Path) -> None:
    timing, summary, config = _fixture(tmp_path)
    result = validate_gate4_stage(
        timing_path=timing,
        summary_path=summary,
        config_path=config,
        stage_name="sine_0_25",
        expected_config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
        expected_ticks=4,
    )
    assert result["stage"] == "sine_0_25"
    assert result["tracking_p95_rad"] == pytest.approx(0.001)


def test_gate4_validator_rejects_quiet_target_contract_drift(tmp_path: Path) -> None:
    timing, summary, config = _fixture(tmp_path)
    rows = timing.read_text(encoding="utf-8").splitlines()
    record = json.loads(rows[2])
    record["motion"]["target_positions_rad"][1] += 0.001
    rows[2] = json.dumps(record, separators=(",", ":"))
    timing.write_text("\n".join(rows) + "\n", encoding="utf-8")
    payload = json.loads(summary.read_text(encoding="utf-8"))
    payload["jsonl_sha256"] = hashlib.sha256(timing.read_bytes()).hexdigest()
    summary.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(Gate4ValidationError, match="target 1"):
        validate_gate4_stage(
            timing_path=timing,
            summary_path=summary,
            config_path=config,
            stage_name="sine_0_25",
            expected_config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
            expected_ticks=4,
        )


def test_gate4_validator_rejects_summary_boolean_without_direct_threshold(tmp_path: Path) -> None:
    timing, summary, config = _fixture(tmp_path)
    payload = json.loads(summary.read_text(encoding="utf-8"))
    payload["tracking_absolute_error_rad"]["p95"] = 0.02
    payload["gates"]["tracking_p95_at_most_0_011_rad"] = True
    summary.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(Gate4ValidationError, match="tracking p95"):
        validate_gate4_stage(
            timing_path=timing,
            summary_path=summary,
            config_path=config,
            stage_name="sine_0_25",
            expected_config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
            expected_ticks=4,
        )
