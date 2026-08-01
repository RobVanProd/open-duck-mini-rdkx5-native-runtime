from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATES = ROOT / "artifacts" / "gates" / "phase_5_policy"
PREREGISTRATION = (
    GATES / "t247_deployment_context_route_specialization_preregistration_20260731.json"
)
RESULT = GATES / "t247_deployment_context_route_specialization_result_20260731.json"
REVIEW = GATES / "t247_deployment_context_route_specialization_review_20260731.json"
X5_PREREGISTRATION = (
    GATES / "t247_deployment_x5_context_route_reserved_screen_preregistration_20260731.json"
)
X5_PACKAGE = (
    GATES / "t247_deployment_x5_context_route_execution_package_20260731.json"
)
INVALID_X5_REVIEW = (
    GATES / "t247_deployment_x5_context_route_invalid_execution_review_20260731.json"
)
CORRECTED_X5_PREREGISTRATION = (
    GATES / "t247_deployment_x5_context_route_corrected_screen_preregistration_20260731.json"
)
POLICY_SHA256 = "dadfb446ea7c720f274a15bc65e9171c2e74d715ccfaf58adbb408b6c1365a54"


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_context_route_contract_keeps_t247_frozen_and_covers_all_routes() -> None:
    preregistration = _read(PREREGISTRATION)
    result = _read(RESULT)
    routes = preregistration["implementation_scope"]["routes"]

    assert preregistration["nomenclature"]["frozen_policy"] == (
        "T247_HOME_NEGATIVE_HALF_ADAPTER_FINAL"
    )
    assert preregistration["unchanged_assets"]["deployment_policy_sha256"] == (
        POLICY_SHA256
    )
    assert result["deployment_policy_sha256"] == POLICY_SHA256
    assert routes == [
        "lower-cond0",
        "lower-cond1",
        "positive-cond0",
        "positive-cond1",
        "tail-cond0",
        "tail-cond1",
    ]
    assert set(result["derivation"]["variants"]) == set(routes)


def test_context_route_cpu_result_passes_exact_semantics_and_materiality() -> None:
    result = _read(RESULT)
    checks = result["checks"]
    timing = result["local_timing_contract"]

    assert result["status"] == "PASS_T247_CONTEXT_ROUTE_SPECIALIZATION_CPU_CONTRACT"
    assert result["checks_passed"] == result["checks_total"] == 14
    assert result["failed_checks"] == []
    assert all(checks.values())
    assert result["actual_chain_semantics"]["all_ticks_byte_exact"] is True
    assert result["actual_chain_semantics"]["selected_route"] == "lower-cond0"
    assert result["actual_chain_semantics"]["maximum_rate_excess_rad_s"] == 0.0
    assert timing["all_outputs_byte_exact"] is True
    assert timing["all_routes_p50_materiality_pass"] is True
    assert timing["all_routes_p99_materiality_pass"] is True
    for route in timing["routes"].values():
        assert route["specialized_to_source_p50_ratio"] <= 0.88
        assert route["specialized_to_source_p99_ratio"] <= 0.88


def test_review_earns_only_a_separately_preregistered_no_motion_x5_screen() -> None:
    review = _read(REVIEW)
    x5 = _read(X5_PREREGISTRATION)
    package = _read(X5_PACKAGE)
    invalid = _read(INVALID_X5_REVIEW)
    corrected = _read(CORRECTED_X5_PREREGISTRATION)

    assert review["decision"]["cpu_contract"] == "PASS"
    assert review["decision"]["x5_screen_executed"] is False
    assert review["decision"]["production_integration_earned"] is False
    assert review["decision"]["gate5_earned"] is False
    assert x5["status"] == (
        "PREREGISTERED_ONE_T247_X5_NO_MOTION_CONTEXT_ROUTE_RESERVED_SCREEN"
    )
    assert x5["screen"]["reference_reserve_limits_ms"] == {
        "p99": 1.8,
        "p99_9": 2.5,
        "max": 4.0,
    }
    assert x5["safety_and_scope"]["servo_reads_or_writes"] is False
    assert x5["safety_and_scope"]["torque"] is False
    assert x5["safety_and_scope"]["motion"] is False
    assert x5["decision_rule"]["retry"] is False
    assert package["status"] == "SEALED_T247_X5_CONTEXT_ROUTE_EXECUTION_PACKAGE"
    assert package["preregistration_file_sha256"] == (
        "1fe2b2103967a25ce6ed84d60b620c3021e2daba461d0d9eb230a5299513ac05"
    )
    assert package["scope"]["policy"] == "unchanged T247"
    assert package["scope"]["robot_devices"] is False
    assert invalid["status"] == (
        "INVALID_T247_X5_CONTEXT_ROUTE_EXECUTION_NOT_A_MECHANISM_FALSIFICATION"
    )
    assert invalid["admissible_semantic_evidence"]["all_2298_ticks_byte_exact"] is True
    assert invalid["validity_decision"]["mechanism_closed"] is False
    assert invalid["validity_decision"]["old_contract_retry"] is False
    assert corrected["status"] == (
        "PREREGISTERED_ONE_CORRECTED_T247_X5_CONTEXT_ROUTE_SCREEN"
    )
    assert corrected["screen"]["reference_reserve_limits_ms"] == {
        "p99": 1.8,
        "p99_9": 2.5,
        "max": 4.0,
    }
    assert corrected["decision_rule"]["valid_execution_retry"] is False


def test_specialization_tools_do_not_import_robot_interfaces_or_commit_onnx() -> None:
    sources = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "tools/derive_t247_context_route_variants.py",
            "tools/verify_t247_context_route_specialization.py",
            "tools/run_t247_x5_context_route_reserved_screen.py",
        )
    )
    for forbidden in ("import serial", "import smbus2", "import pygame", "open_duck_x5.runtime"):
        assert forbidden not in sources
    assert not list((ROOT / "artifacts").rglob("*.onnx"))
