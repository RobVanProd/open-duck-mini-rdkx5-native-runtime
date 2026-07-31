from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "status" / "policy_gate.json"


def _status() -> dict[str, object]:
    return json.loads(STATUS.read_text(encoding="utf-8"))


def test_policy_gate_status_records_green_offline_and_blocked_hardware() -> None:
    status = _status()
    gates = status["gates"]
    authority = status["authority"]

    assert status["schema_version"] == "open_duck.runtime_policy_gate_status.v2"
    assert status["status"] == "T251_X5_NO_MOTION_CPU_PREFLIGHT_HOLD_TIMING"
    assert status["offline_policy_green"] is True
    assert status["robot_clearance"] is False
    assert gates["t249b_full_r2"] == {
        "status": "PASS",
        "green_conditions": 20,
        "conditions": 20,
        "green_cells": 320,
        "cells": 320,
    }
    assert gates["t250_native_runtime_integration"]["status"] == "PASS"
    assert gates["t250_native_runtime_integration"]["passing_checks"] == 25
    assert gates["t250_native_runtime_integration"]["maximum_numeric_delta"] == 0.0
    t251 = gates["t251_x5_no_motion_cpu_preflight"]
    assert t251["status"] == "HOLD"
    assert t251["passing_checks"] == 15
    assert t251["checks"] == 18
    assert t251["failed_checks"] == [
        "stage_latency_max",
        "stage_latency_p99",
        "stage_latency_p99_9",
    ]
    assert gates["opt_in_production_integration"] == "NOT_PREREGISTERED"
    assert gates["gate_5"] == "NOT_RUN"
    assert authority["production_runtime_integration_earned"] is False
    assert authority["gate_5_authorized_by_this_status"] is False
    assert authority["robot_motion_authorized_by_this_status"] is False


def test_policy_gate_status_pins_exact_two_stage_abi_and_assets() -> None:
    status = _status()
    abi = status["candidate_abi"]
    assets = status["selected_assets"]

    assert abi["calibrator_inputs"] == {
        "obs": [1, 115],
        "previous_action": [1, 14],
        "h_in": [1, 64],
    }
    assert abi["policy_inputs"] == {
        "obs": [1, 115],
        "previous_action": [1, 14],
        "h_in": [1, 64],
        "calibration_context": [1, 64],
    }
    assert abi["policy_outputs"] == {
        "continuous_actions": [1, 14],
        "previous_action_out": [1, 14],
        "h_out": [1, 64],
    }
    assert assets["persistence_witness"]["step"] == 1_003_520
    assert assets["deployment_terminal"]["step"] == 2_007_040
    assert assets["deployment_terminal"]["sha256"] == (
        "dadfb446ea7c720f274a15bc65e9171c2e74d715ccfaf58adbb408b6c1365a54"
    )
    assert assets["calibrator"]["sha256"] == (
        "0f3aebfd9946a6271fdb14adec3d68d556648f270984639d372c973a7d7dc576"
    )


def test_policy_gate_status_pins_current_validation_and_repositories() -> None:
    status = _status()
    validation = status["validation"]
    repositories = status["repositories"]

    assert validation["repository_tests"] == {"status": "PASS", "passed": 408}
    assert validation["reviewed_artifact_manifest"] == {
        "status": "PASS",
        "entries": 172,
    }
    assert repositories == {
        "policy_evidence": "https://github.com/RobVanProd/open-duck-mini-rdkx5",
        "native_runtime": ("https://github.com/RobVanProd/open-duck-mini-rdkx5-native-runtime"),
    }
