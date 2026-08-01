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
    assert status["status"] == "T247_X5_CONTEXT_ROUTE_SCREEN_SEALED"
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
    assert t251a4["x5_screen_status"] == "HOLD_P99"
    assert t251a4["x5_screen_checks_passed"] == 17
    assert t251a4["x5_screen_checks"] == 18
    assert t251a4["x5_screen_failed_checks"] == ["stage_p99_within_reserve"]
    assert t251a4["next_measured_component"] == "target"
    assert t251a4["t251b_earned"] is False
    t251a5 = gates["t251a5_target_cpu_contract"]
    assert t251a5["status"] == "PASS"
    assert t251a5["byte_exact_ticks"] == 2_298
    assert t251a5["handoff_switches"] == 1
    assert t251a5["maximum_rate_excess_rad_s"] == 0.0
    assert t251a5["offsets_immutable"] is True
    assert t251a5["locomotion_desired_sent_buffer_alias"] is True
    assert t251a5["local_target_microbenchmark_samples"] == 20_000
    assert t251a5["corrected_to_predecessor_median_ratio"] <= 0.75
    assert t251a5["x5_screen_status"] == "HOLD_P99"
    assert t251a5["x5_screen_checks_passed"] == 21
    assert t251a5["x5_screen_checks"] == 22
    assert t251a5["x5_screen_failed_checks"] == ["stage_p99_within_reserve"]
    assert t251a5["next_measured_component"] == "observation"
    assert t251a5["t251b_earned"] is False
    t251a6 = gates["t251a6_observation_cpu_contract"]
    assert t251a6["status"] == "CLOSED_TOO_SMALL"
    assert t251a6["byte_exact_ticks"] == 2_298
    assert t251a6["handoff_switches"] == 1
    assert t251a6["maximum_rate_excess_rad_s"] == 0.0
    assert t251a6["local_observation_microbenchmark_samples"] == 20_000
    assert t251a6["corrected_to_predecessor_median_ratio"] > 0.75
    assert t251a6["x5_screen_status"] == "NOT_EARNED"
    assert t251a6["next_measured_component"] == "transaction_residual"
    assert t251a6["t251b_earned"] is False
    t251a7 = gates["t251a7_transaction_residual_cpu_contract"]
    assert t251a7["status"] == "CLOSED_TOO_SMALL"
    assert t251a7["byte_exact_ticks"] == 2_298
    assert t251a7["handoff_switches"] == 1
    assert t251a7["maximum_rate_excess_rad_s"] == 0.0
    assert t251a7["fallback_diagnostic_cases_exact"] == 7
    assert t251a7["fault_boundary_cases_exact"] == 6
    assert t251a7["local_transaction_microbenchmark_samples"] == 20_000
    assert t251a7["corrected_to_predecessor_median_ratio"] > 0.75
    assert t251a7["x5_screen_status"] == "NOT_EARNED"
    assert t251a7["next_measured_component"] == "observer_stage"
    assert t251a7["t251b_earned"] is False
    t251a8 = gates["t251a8_observer_stage_cpu_contract"]
    assert t251a8["status"] == "CLOSED_TOO_SMALL"
    assert t251a8["byte_exact_ticks"] == 2_298
    assert t251a8["handoff_switches"] == 1
    assert t251a8["maximum_rate_excess_rad_s"] == 0.0
    assert t251a8["boundary_contract_exact"] is True
    assert t251a8["local_observer_stage_microbenchmark_samples"] == 20_000
    assert t251a8["corrected_to_predecessor_stage_median_ratio"] > 0.75
    assert (
        t251a8["corrected_to_predecessor_stage_plus_commit_median_ratio"]
        <= 1.1
    )
    assert t251a8["x5_screen_status"] == "NOT_EARNED"
    assert t251a8["component_local_optimization"] == "EXHAUSTED"
    assert t251a8["t251b_earned"] is False
    specialization = gates["t247_deployment_context_route_specialization"]
    assert specialization["status"] == "PASS_CPU_CONTRACT_X5_SCREEN_PREREGISTERED"
    assert specialization["policy"] == "T247_HOME_NEGATIVE_HALF_ADAPTER_FINAL"
    assert specialization["policy_weights_unchanged"] is True
    assert specialization["complete_routes"] == 6
    assert specialization["cpu_contract_status"] == "PASS"
    assert specialization["cpu_contract_checks_passed"] == 14
    assert specialization["cpu_contract_checks"] == 14
    assert specialization["worst_local_p50_ratio"] <= 0.88
    assert specialization["worst_local_p99_ratio"] <= 0.88
    assert specialization["x5_screen_status"] == "SEALED_READY_TO_RUN"
    assert specialization["x5_execution_package_file_sha256"] == (
        "daed01700cfa385b5a4d97c084cc2b5c6666b9cbb15be32f6f5b5067eedcb521"
    )
    assert specialization["policy_training_earned"] is False
    assert specialization["production_integration_earned"] is False
    assert specialization["gate5_earned"] is False
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

    assert validation["repository_tests"] == {"status": "PASS", "passed": 485}
    assert validation["reviewed_artifact_manifest"] == {
        "status": "PASS",
        "entries": 204,
    }
    assert repositories == {
        "policy_evidence": "https://github.com/RobVanProd/open-duck-mini-rdkx5",
        "native_runtime": ("https://github.com/RobVanProd/open-duck-mini-rdkx5-native-runtime"),
    }
