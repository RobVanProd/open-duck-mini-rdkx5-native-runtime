from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from open_duck_x5 import runtime as runtime_module
from open_duck_x5.control_summary import (
    ControlSummaryError,
    summarize_control_run,
)
from open_duck_x5.control_summary import (
    main as summary_main,
)
from open_duck_x5.runtime import main as runtime_main
from open_duck_x5.t247_command_routes import (
    T247_CALIBRATOR_SHA256,
    T247_COMMAND_MANIFEST_SHA256,
    T247_CONTEXT_ROUTER_SHA256,
    T247_P30_SHA256,
    T247_POLICY_CONTRACT,
    T247_POLICY_SHA256,
    T247_REFERENCE_SHA256,
    T247_RUNTIME_CONTRACT_ID,
)


def _example_config() -> Path:
    return Path(__file__).parents[1] / "duck_config.example.json"


def _summary_validator() -> Draft202012Validator:
    path = Path(__file__).parents[1] / "schemas/control_summary.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _realtime_event(start_timestamp: int) -> dict[str, object]:
    return {
        "schema_version": "open_duck_x5.runtime_event.v1",
        "timestamp_monotonic_ns": start_timestamp,
        "event": "realtime_verified",
        "details": {
            "cpu": 5,
            "scheduler": "SCHED_FIFO",
            "priority": 80,
            "isolated": True,
            "affinity": [5],
            "initial_affinity": [0, 1, 2, 3, 4, 5],
            "housekeeping_affinity": [0, 1, 2, 3, 4],
            "background_threads": [
                {
                    "tid": 101,
                    "affinity": [0, 1, 2, 3, 4],
                    "scheduler": 0,
                    "priority": 0,
                }
            ],
        },
    }


def _startup_readiness_event(first_tick_timestamp: int) -> dict[str, object]:
    tick_start = first_tick_timestamp - 20_000_000
    return {
        "schema_version": "open_duck_x5.runtime_event.v1",
        "timestamp_monotonic_ns": tick_start + 4_000_000,
        "event": "startup_readiness",
        "details": {
            "status": "PASS",
            "failures": [],
            "paused": True,
            "policy_staged": False,
            "policy_committed_ticks": None,
            "phase": 0.0,
            "tick_start_monotonic_ns": tick_start,
            "tick_work_ms": 4.0,
            "release_lateness_ms": 0.0,
            "next_release_monotonic_ns": first_tick_timestamp,
            "bus_total_ms": 3.9,
            "group_round_trip_ms": 3.0,
            "extended_round_trip_ms": 0.5,
            "write_status": "ok",
            "all_fresh": True,
            "per_servo_status": ["ok"] * 14,
            "per_servo_device_status": [0] * 14,
            "extended_status": "ok",
            "extended_device_status": 0,
            "imu_stale": False,
            "contacts_stale": False,
            "partial_bytes": 0,
            "unexpected_packets": 0,
        },
    }


def _insert_startup_readiness(records: list[dict[str, object]]) -> None:
    start = records[0]
    realtime = next(
        (record for record in records if record.get("event") == "realtime_verified"),
        None,
    )
    lower_timestamp = int(start["timestamp_monotonic_ns"])
    if realtime is not None:
        lower_timestamp = max(lower_timestamp, int(realtime["timestamp_monotonic_ns"]))
    readiness_tick_start = lower_timestamp + 1_000_000
    first_tick_timestamp = readiness_tick_start + 20_000_000
    ticks = [record for record in records if record.get("tick") is not None]
    for index, tick in enumerate(ticks):
        tick["timestamp_monotonic_ns"] = first_tick_timestamp + index * 20_000_000
        tick["tick_period_ms"] = 20.0
    halt = records[-1]
    halt["timestamp_monotonic_ns"] = first_tick_timestamp + len(ticks) * 20_000_000
    insertion_index = 2 if realtime is not None else 1
    records.insert(insertion_index, _startup_readiness_event(first_tick_timestamp))


def _run_paused(
    tmp_path: Path, *, ticks: int = 5, config: Path | None = None
) -> Path:
    telemetry = tmp_path / "paused-control.jsonl"
    config = _example_config() if config is None else config
    assert (
        runtime_main(
            [
                "--bus",
                "mock",
                "--config",
                str(config),
                "--telemetry",
                str(telemetry),
                "--home-seconds",
                "0.001",
                "--max-ticks",
                str(ticks),
            ]
        )
        == 0
    )
    return telemetry


def _synthetic_t247_telemetry(tmp_path: Path, *, fixed_x: float = 0.08) -> Path:
    source = _run_paused(tmp_path, ticks=1)
    records = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    start = records[0]
    template = records[1]
    halt = records[-1]
    active_ticks = 252
    details = start["details"]
    details["contract_id"] = T247_RUNTIME_CONTRACT_ID
    details["fixed_command_x"] = fixed_x
    details["max_ticks"] = active_ticks + 1
    details["max_active_ticks"] = active_ticks
    details["policy"] = {
        "contract": T247_POLICY_CONTRACT,
        "path": "/frozen/policy.onnx",
        "sha256": T247_POLICY_SHA256,
        "calibration_ticks": 250,
        "calibrator_inputs": {
            "obs": [1, 115],
            "previous_action": [1, 14],
            "h_in": [1, 64],
        },
        "locomotion_inputs": {
            "obs": [1, 115],
            "previous_action": [1, 14],
            "h_in": [1, 64],
            "calibration_context": [1, 64],
        },
        "outputs": {
            "action": [1, 14],
            "previous_action_out": [1, 14],
            "h_out": [1, 64],
        },
        "context_routes": 6,
        "exact_command_routes": 24,
        "fallback_preserved": True,
        "assets": {
            "calibrator": {"path": "/frozen/calibrator.onnx", "sha256": T247_CALIBRATOR_SHA256},
            "command_route_manifest": {
                "path": "/frozen/manifest.json",
                "sha256": T247_COMMAND_MANIFEST_SHA256,
            },
            "p30_fit": {"path": "/frozen/p30.json", "sha256": T247_P30_SHA256},
            "reference_table": {
                "path": "/frozen/reference.npz",
                "sha256": T247_REFERENCE_SHA256,
            },
            "context_route_root": {
                "path": "/frozen/context-routes",
                "verified_models": 6,
                "router_sha256": T247_CONTEXT_ROUTER_SHA256,
            },
            "command_route_root": {
                "path": "/frozen/command-routes",
                "verified_models": 24,
            },
        },
    }
    tick_records = []
    first_timestamp = int(start["timestamp_monotonic_ns"]) + 20_000_000
    for index in range(active_ticks):
        tick = deepcopy(template)
        tick["tick"] = index
        tick["timestamp_monotonic_ns"] = first_timestamp + index * 20_000_000
        tick["tick_period_ms"] = None if index == 0 else 20.0
        tick["paused"] = False
        tick["observation_valid"] = True
        observation = [0.0] * 115
        stage = "calibration" if index < 250 else "locomotion"
        if stage == "locomotion":
            observation[6] = fixed_x
        tick["observation"] = observation
        tick["action"] = [0.0] * 14
        tick["extended"]["servo_id"] = details["servo_ids"][index % 14]
        tick["policy_host"] = {
            "stage": stage,
            "selected_context_route": (
                "lower-cond1" if index >= 249 else None
            ),
            "selected_command_route": (
                ("x000" if fixed_x == 0.0 else "x080")
                if stage == "locomotion"
                else ("fallback" if index == 249 else None)
            ),
        }
        tick_records.append(tick)
    halt["timestamp_monotonic_ns"] = first_timestamp + active_ticks * 20_000_000
    output = tmp_path / "synthetic-t247.jsonl"
    output.write_text(
        "\n".join(json.dumps(record) for record in (start, *tick_records, halt)) + "\n",
        encoding="utf-8",
    )
    return output


def test_paused_mock_control_summary_is_structurally_complete_but_not_gate5(
    tmp_path: Path,
) -> None:
    telemetry = _run_paused(tmp_path)
    output = tmp_path / "paused-summary.json"
    assert summary_main(["--input", str(telemetry), "--output", str(output)]) == 0

    summary = json.loads(output.read_text(encoding="utf-8"))
    _summary_validator().validate(summary)
    assert summary["source"]["sha256"] == hashlib.sha256(telemetry.read_bytes()).hexdigest()
    assert summary["backend"] == "mock"
    assert summary["informational_only"] is True
    assert summary["hardware_gate_status"] == "NOT_APPLICABLE_MOCK"
    assert summary["run_status"] == "COMPLETE"
    assert summary["ticks"] == 5
    assert summary["paused_ticks"] == 5
    assert summary["active_policy_ticks"] == 0
    assert summary["bus"]["transactions_expected"] == 80
    assert summary["bus"]["transactions_failed"] == 0
    assert summary["bus"]["device_alarm_reply_count"] == 0
    assert summary["bus"]["voltage_alarm_reply_count"] == 0
    assert summary["telemetry_records_dropped"] == 0
    assert summary["safety"] == {
        "torque_off_attempted": True,
        "torque_off_status": "ok",
        "torque_off_error": None,
        "torque_off_confirmed": True,
    }
    assert summary["gates"]["complete_record_stream"] is True
    assert summary["gates"]["torque_off_confirmed"] is True
    assert summary["gates"]["zero_device_alarms"] is True
    assert summary["gates"]["policy_ticks_present"] is False
    assert summary["gates"]["gate5_timing_and_bus_candidate"] is False
    assert summary["envelope"]["total_events"] == 0
    assert sum(summary["extended_telemetry_coverage"].values()) == 5


def test_active_policy_summary_preserves_provenance_command_and_envelope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    raw_config = json.loads(_example_config().read_text(encoding="utf-8"))
    raw_config["start_paused"] = False
    config = tmp_path / "active-config.json"
    config.write_text(json.dumps(raw_config), encoding="utf-8")
    policy_path = tmp_path / "candidate-101.onnx"
    policy_path.write_bytes(b"fake frozen 101x14 policy")
    telemetry = tmp_path / "active-control.jsonl"

    class FakePolicy:
        @staticmethod
        def infer(_observation: np.ndarray) -> np.ndarray:
            return np.ones(14, dtype=np.float32)

    monkeypatch.setattr(runtime_module, "OnnxPolicy", lambda _path: FakePolicy())
    assert (
        runtime_main(
            [
                "--bus",
                "mock",
                "--config",
                str(config),
                "--policy",
                str(policy_path),
                "--fixed-command-x",
                "0.08",
                "--telemetry",
                str(telemetry),
                "--home-seconds",
                "0.001",
                "--max-ticks",
                "8",
                "--max-active-ticks",
                "5",
            ]
        )
        == 0
    )

    summary = summarize_control_run(telemetry)
    _summary_validator().validate(summary)
    assert summary["active_policy_ticks"] == 5
    assert summary["active_ticks_requested"] == 5
    assert summary["ticks"] == 5
    assert summary["ticks_requested"] == 8
    assert summary["paused_ticks"] == 0
    assert summary["command"]["fixed_x"] == 0.08
    assert summary["command"]["matches_fixed_x"] is True
    assert summary["command"]["max_abs_non_x"] == 0.0
    assert summary["provenance"]["policy"]["sha256"] == hashlib.sha256(
        policy_path.read_bytes()
    ).hexdigest()
    assert summary["provenance"]["config"]["sha256"] == hashlib.sha256(
        config.read_bytes()
    ).hexdigest()
    assert summary["envelope"]["total_events"] > 0
    assert summary["gates"]["complete_record_stream"] is True
    assert summary["gates"]["zero_non_x_commands"] is True


def test_t247_summary_validates_calibration_locomotion_and_route_sequence(
    tmp_path: Path,
) -> None:
    telemetry = _synthetic_t247_telemetry(tmp_path)
    start = json.loads(telemetry.read_text(encoding="utf-8").splitlines()[0])
    event_schema = json.loads(
        (Path(__file__).parents[1] / "schemas/runtime_event.schema.json").read_text()
    )
    Draft202012Validator(event_schema).validate(start)

    summary = summarize_control_run(telemetry)

    _summary_validator().validate(summary)
    assert summary["active_policy_ticks"] == 252
    assert summary["command"]["observed_x"]["min"] == 0.08
    assert summary["command"]["observed_x"]["max"] == 0.08
    assert summary["command"]["matches_fixed_x"] is True
    assert summary["gates"]["t247_stage_sequence_exact"] is True
    assert summary["gates"]["t247_route_sequence_exact"] is True


def test_t247_summary_rejects_wrong_locomotion_route(tmp_path: Path) -> None:
    telemetry = _synthetic_t247_telemetry(tmp_path)
    records = [json.loads(line) for line in telemetry.read_text(encoding="utf-8").splitlines()]
    records[-2]["policy_host"]["selected_command_route"] = "x000"
    telemetry.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ControlSummaryError, match="command route differs"):
        summarize_control_run(telemetry)


def test_t247_summary_rejects_legacy_top_level_contract_id(tmp_path: Path) -> None:
    telemetry = _synthetic_t247_telemetry(tmp_path)
    records = [json.loads(line) for line in telemetry.read_text(encoding="utf-8").splitlines()]
    records[0]["details"]["contract_id"] = "open-duck-mini.best-walk.101x14.v1"
    telemetry.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ControlSummaryError, match="wrong runtime contract ID"):
        summarize_control_run(telemetry)


def test_summary_rejects_tick_discontinuity(tmp_path: Path) -> None:
    telemetry = _run_paused(tmp_path, ticks=3)
    records = [json.loads(line) for line in telemetry.read_text(encoding="utf-8").splitlines()]
    tick_records = [record for record in records if record.get("tick") is not None]
    tick_records[1]["tick"] = 7
    telemetry.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ControlSummaryError, match="discontinuity"):
        summarize_control_run(telemetry)


def test_summary_cannot_mark_dropped_telemetry_complete(tmp_path: Path) -> None:
    telemetry = _run_paused(tmp_path, ticks=3)
    records = [json.loads(line) for line in telemetry.read_text(encoding="utf-8").splitlines()]
    records[-1]["telemetry_records_dropped"] = 1
    telemetry.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    summary = summarize_control_run(telemetry)

    assert summary["run_status"] == "HALTED"
    assert summary["gates"]["complete_record_stream"] is False
    assert summary["gates"]["gate5_timing_and_bus_candidate"] is False


def test_summary_cannot_pass_without_confirmed_torque_off(tmp_path: Path) -> None:
    telemetry = _run_paused(tmp_path, ticks=3)
    records = [json.loads(line) for line in telemetry.read_text(encoding="utf-8").splitlines()]
    records[-1]["torque_off_status"] = "io"
    records[-1]["torque_off_error"] = "cleanup torque-off failed: io"
    telemetry.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    summary = summarize_control_run(telemetry)

    assert summary["run_status"] == "HALTED"
    assert summary["safety"]["torque_off_confirmed"] is False
    assert summary["gates"]["torque_off_confirmed"] is False
    assert summary["gates"]["gate5_timing_and_bus_candidate"] is False


def test_synthetic_serial_summary_always_requires_human_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    raw_config = json.loads(_example_config().read_text(encoding="utf-8"))
    raw_config["start_paused"] = False
    config = tmp_path / "synthetic-active-config.json"
    config.write_text(json.dumps(raw_config), encoding="utf-8")
    policy_path = tmp_path / "synthetic-candidate.onnx"
    policy_path.write_bytes(b"synthetic 101x14 policy metadata only")
    telemetry = tmp_path / "synthetic-serial.jsonl"

    class FakePolicy:
        @staticmethod
        def infer(_observation: np.ndarray) -> np.ndarray:
            return np.zeros(14, dtype=np.float32)

    monkeypatch.setattr(runtime_module, "OnnxPolicy", lambda _path: FakePolicy())
    assert (
        runtime_main(
            [
                "--bus",
                "mock",
                "--config",
                str(config),
                "--policy",
                str(policy_path),
                "--fixed-command-x",
                "0.08",
                "--telemetry",
                str(telemetry),
                "--home-seconds",
                "0.001",
                "--max-ticks",
                "4",
                "--max-active-ticks",
                "3",
            ]
        )
        == 0
    )
    records = [json.loads(line) for line in telemetry.read_text(encoding="utf-8").splitlines()]
    start = records[0]
    details = start["details"]
    details["bus"]["backend"] = "serial"
    details["bus"]["device"] = "/dev/ttyACM0"
    details["config"]["start_paused"] = True
    details["controller"] = "xbox"
    details["realtime_required"] = True
    details["gate5_authorized"] = True
    details["hardware_authorized"] = True
    details["suspended_or_benched"] = True
    realtime_event = _realtime_event(int(start["timestamp_monotonic_ns"]))
    records.insert(1, realtime_event)
    telemetry.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    summary = summarize_control_run(telemetry)

    assert summary["backend"] == "serial"
    assert summary["informational_only"] is False
    assert summary["review_status"] == "REVIEW_REQUIRED"
    assert summary["hardware_gate_status"] == "REVIEW_REQUIRED"
    assert summary["startup_readiness"] is None
    assert summary["gates"]["startup_readiness_passed"] is False
    assert summary["gates"]["gate5_timing_and_bus_candidate"] is False

    _insert_startup_readiness(records)
    telemetry.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    ready_summary = summarize_control_run(telemetry)

    _summary_validator().validate(ready_summary)
    assert ready_summary["startup_readiness"]["status"] == "PASS"
    assert ready_summary["gates"]["startup_readiness_passed"] is True
    assert ready_summary["timing"]["tick_period_ms"]["min"] == 20.0


def test_startup_readiness_is_ordered_and_anchors_first_tick_period(
    tmp_path: Path,
) -> None:
    telemetry = _run_paused(tmp_path, ticks=3)
    records = [json.loads(line) for line in telemetry.read_text(encoding="utf-8").splitlines()]
    _insert_startup_readiness(records)
    telemetry.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    summary = summarize_control_run(telemetry)

    _summary_validator().validate(summary)
    assert summary["startup_readiness"]["status"] == "PASS"
    assert summary["timing"]["tick_period_ms"] == {
        "min": 20.0,
        "mean": 20.0,
        "p95": 20.0,
        "p99": 20.0,
        "p99_9": 20.0,
        "max": 20.0,
    }


def test_summary_rejects_duplicate_or_late_startup_readiness(tmp_path: Path) -> None:
    telemetry = _run_paused(tmp_path, ticks=2)
    records = [json.loads(line) for line in telemetry.read_text(encoding="utf-8").splitlines()]
    _insert_startup_readiness(records)
    duplicate = deepcopy(records)
    duplicate.insert(2, deepcopy(duplicate[1]))
    telemetry.write_text(
        "\n".join(json.dumps(record) for record in duplicate) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ControlSummaryError, match="duplicated or out of order"):
        summarize_control_run(telemetry)

    readiness = records.pop(1)
    records.insert(2, readiness)
    telemetry.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ControlSummaryError, match="duplicated or out of order"):
        summarize_control_run(telemetry)


def test_summary_rejects_dirty_pass_or_null_first_period_after_readiness(
    tmp_path: Path,
) -> None:
    telemetry = _run_paused(tmp_path, ticks=2)
    records = [json.loads(line) for line in telemetry.read_text(encoding="utf-8").splitlines()]
    _insert_startup_readiness(records)
    dirty = deepcopy(records)
    dirty[1]["details"]["all_fresh"] = False
    telemetry.write_text(
        "\n".join(json.dumps(record) for record in dirty) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ControlSummaryError, match="PASS record is not clean"):
        summarize_control_run(telemetry)

    first_tick = next(record for record in records if record.get("tick") == 0)
    first_tick["tick_period_ms"] = None
    telemetry.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ControlSummaryError, match="tick 0 period must be numeric"):
        summarize_control_run(telemetry)


def test_summary_refuses_to_overwrite_control_jsonl(tmp_path: Path) -> None:
    telemetry = _run_paused(tmp_path, ticks=2)
    before = telemetry.read_bytes()
    with pytest.raises(SystemExit):
        summary_main(["--input", str(telemetry), "--output", str(telemetry)])
    assert telemetry.read_bytes() == before


def test_summary_cannot_overwrite_recorded_config(tmp_path: Path) -> None:
    config = tmp_path / "duck_config.json"
    original = _example_config().read_bytes()
    config.write_bytes(original)
    telemetry = _run_paused(tmp_path, ticks=2, config=config)

    with pytest.raises(SystemExit):
        summary_main(["--input", str(telemetry), "--output", str(config)])

    assert config.read_bytes() == original
