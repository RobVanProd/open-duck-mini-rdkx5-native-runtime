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
    assert status["status"] == (
        "T251A4_X5_GRAPH_HOST_RESERVED_SCREEN_PREREGISTERED"
    )
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
    t251a2 = gates["t251a2_optimized_paced_screen"]
    assert t251a2["status"] == "HOLD"
    assert t251a2["passing_checks"] == 13
    assert t251a2["checks"] == 15
    assert t251a2["byte_exact_ticks"] == 2_298
    assert t251a2["failed_checks"] == [
        "optimized_p99_9_with_reserve",
        "optimized_p99_with_reserve",
    ]
    assert t251a2["t251b_earned"] is False
    t251a3 = gates["t251a3_single_host_component_attribution"]
    assert t251a3["status"] == "PASS_REVIEW"
    assert t251a3["selected_component"] == "graph_host"
    assert t251a3["t251b_earned"] is False
    t251a4 = gates["t251a4_graph_host_cpu_contract"]
    assert t251a4["status"] == "PASS"
    assert t251a4["byte_exact_ticks"] == 2_298
    assert t251a4["handoff_switches"] == 1
    assert t251a4["maximum_rate_excess_rad_s"] == 0.0
    assert t251a4["x5_screen_status"] == "PREREGISTERED_NOT_RUN"
    assert t251a4["t251b_earned"] is False
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

    assert validation["repository_tests"] == {"status": "PASS", "passed": 441}
    assert validation["reviewed_artifact_manifest"] == {
        "status": "PASS",
        "entries": 182,
    }
    assert repositories == {
        "policy_evidence": "https://github.com/RobVanProd/open-duck-mini-rdkx5",
        "native_runtime": ("https://github.com/RobVanProd/open-duck-mini-rdkx5-native-runtime"),
    }
