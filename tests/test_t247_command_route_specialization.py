from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATES = ROOT / "artifacts" / "gates" / "phase_5_policy"
AUDIT = GATES / "t247_deployment_command_route_specialization_audit_20260801.json"
PREREGISTRATION = (
    GATES
    / "t247_deployment_command_route_specialization_preregistration_20260801.json"
)
REVIEW = GATES / "t247_deployment_command_route_specialization_review_20260801.json"
X5_PREREGISTRATION = (
    GATES
    / "t247_deployment_x5_command_route_reserved_screen_preregistration_20260801.json"
)
X5_PACKAGE = (
    GATES / "t247_deployment_x5_command_route_execution_package_20260801.json"
)


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_command_route_audit_selects_exact_all_route_contract() -> None:
    audit = _read(AUDIT)
    preregistration = _read(PREREGISTRATION)

    assert hashlib.sha256(AUDIT.read_bytes()).hexdigest() == (
        preregistration["earned_by"]["audit_file_sha256"]
    )
    assert audit["mechanism"]["policy_weights_changed"] is False
    assert audit["mechanism"]["policy_abi_changed"] is False
    assert audit["mechanism"]["fallback_required"] is True
    assert preregistration["implementation_scope"]["generated_models"] == 24
    assert preregistration["implementation_scope"]["exact_commands_m_s"] == [
        0.0,
        0.074,
        0.077,
        0.08,
    ]
    assert preregistration["cpu_contract"]["expected_one_step_cases"] == 6144
    assert preregistration["cpu_contract"]["expected_route_switch_ticks"] == 7920
    assert preregistration["decision_rule"]["x5_execution_now"] is False
    assert preregistration["safety_and_authority"]["torque"] is False
    assert preregistration["safety_and_authority"]["motion"] is False


def test_command_route_cpu_review_earns_only_separate_no_device_x5_screen() -> None:
    review = _read(REVIEW)
    x5 = _read(X5_PREREGISTRATION)
    package = _read(X5_PACKAGE)

    assert hashlib.sha256(REVIEW.read_bytes()).hexdigest() == (
        x5["earned_by"]["review_file_sha256"]
    )
    assert review["result"]["checks_passed"] == 15
    assert review["result"]["checks_total"] == 15
    assert review["derivation"]["generated_models"] == 24
    assert review["semantic_result"]["one_step_cases"] == 6144
    assert review["semantic_result"]["route_switch_ticks"] == 7920
    assert review["semantic_result"]["fallback_ticks"] > 0
    assert review["semantic_result"]["all_2298_tick_chains_byte_exact"] is True
    assert review["semantic_result"]["all_maximum_rate_excess_rad_s"] == 0.0
    assert review["timing_result"]["worst_p50_ratio"] <= 0.88
    assert review["timing_result"]["worst_p99_ratio"] <= 0.88
    assert x5["screen"]["reserve_limits_ms"] == {
        "p99": 1.8,
        "p99_9": 2.5,
        "max": 4.0,
    }
    assert len(x5["screen"]["arms"]) == 2
    assert x5["decision_rule"]["retry"] is False
    assert x5["safety_and_authority"]["servo_reads_or_writes"] is False
    assert x5["safety_and_authority"]["torque"] is False
    assert x5["safety_and_authority"]["motion"] is False
    assert package["status"] == "SEALED_T247_X5_COMMAND_ROUTE_EXECUTION_PACKAGE"
    assert package["preregistration_file_sha256"] == hashlib.sha256(
        X5_PREREGISTRATION.read_bytes()
    ).hexdigest()
    assert package["source_sha256"][
        "tools/run_t247_x5_command_route_reserved_screen.py"
    ] == hashlib.sha256(
        (ROOT / "tools/run_t247_x5_command_route_reserved_screen.py").read_bytes()
    ).hexdigest()
    assert package["scope"]["robot_devices"] is False
    assert package["scope"]["torque"] is False
    assert package["scope"]["motion"] is False


def test_command_route_tools_are_no_device_and_keep_fallback() -> None:
    sources = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "tools/derive_t247_command_route_variants.py",
            "tools/verify_t247_command_route_specialization.py",
            "tools/run_t247_x5_command_route_reserved_screen.py",
        )
    )
    for forbidden in (
        "import serial",
        "import smbus2",
        "import pygame",
        "open_duck_x5.runtime",
        "open_duck_x5.bus",
        "open_duck_x5.sensors",
    ):
        assert forbidden not in sources
    assert "fallback_rule" in sources
    runner = (
        ROOT / "tools/run_t247_x5_command_route_reserved_screen.py"
    ).read_text(encoding="utf-8")
    assert runner.index("corrected.platform_preflight") < runner.index(
        "router = base.router_session"
    )
    assert not list((ROOT / "artifacts").rglob("*.onnx"))
