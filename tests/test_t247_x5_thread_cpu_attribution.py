from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from tools import run_t247_x5_thread_cpu_attribution as attribution

ROOT = Path(__file__).resolve().parents[1]
GATES = ROOT / "artifacts" / "gates" / "phase_5_policy"
AUDIT = GATES / "t247_deployment_x5_periodic_latency_attribution_audit_20260731.json"
PREREGISTRATION = (
    GATES / "t247_deployment_x5_thread_cpu_attribution_preregistration_20260731.json"
)
PACKAGE = (
    GATES / "t247_deployment_x5_thread_cpu_attribution_execution_package_20260731.json"
)
POLICY_SHA256 = "dadfb446ea7c720f274a15bc65e9171c2e74d715ccfaf58adbb408b6c1365a54"


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_thread_cpu_attribution_is_preregistered_for_unchanged_t247_only() -> None:
    audit = _read(AUDIT)
    preregistration = _read(PREREGISTRATION)

    assert hashlib.sha256(AUDIT.read_bytes()).hexdigest() == (
        preregistration["earned_by"]["audit_file_sha256"]
    )
    assert hashlib.sha256(PREREGISTRATION.read_bytes()).hexdigest() == (
        attribution.PREREGISTRATION_SHA256
    )
    assert audit["deployment_policy_sha256"] == POLICY_SHA256
    assert preregistration["unchanged_assets"]["deployment_policy_sha256"] == (
        POLICY_SHA256
    )
    assert preregistration["screen"]["selection_weight"] == 0
    assert preregistration["decision_rule"]["valid_execution_retry"] is False
    assert (
        preregistration["decision_rule"]["context_route_specialization_reopened"]
        is False
    )
    assert preregistration["decision_rule"]["reserve_pass_claim"] is False
    assert preregistration["decision_rule"]["policy_training_earned"] is False
    assert preregistration["decision_rule"]["gate5_earned"] is False
    assert preregistration["safety_and_authority"]["servo_reads_or_writes"] is False
    assert preregistration["safety_and_authority"]["torque"] is False
    assert preregistration["safety_and_authority"]["motion"] is False


def test_thread_cpu_attribution_execution_package_pins_implementation() -> None:
    package = _read(PACKAGE)

    assert package["status"] == (
        "SEALED_T247_X5_THREAD_CPU_ATTRIBUTION_EXECUTION_PACKAGE"
    )
    assert package["preregistration_file_sha256"] == (
        attribution.PREREGISTRATION_SHA256
    )
    assert package["source_sha256"][
        "tools/run_t247_x5_thread_cpu_attribution.py"
    ] == hashlib.sha256(
        (ROOT / "tools/run_t247_x5_thread_cpu_attribution.py").read_bytes()
    ).hexdigest()
    assert package["classification"]["selection_weight"] == 0
    assert package["classification"]["reserve_pass_claim"] is False
    assert package["classification"]["retry"] is False
    assert package["scope"]["policy"] == "unchanged T247"
    assert package["scope"]["robot_devices"] is False
    assert package["scope"]["torque"] is False
    assert package["scope"]["motion"] is False
    assert package["scope"]["boot_change"] is False


def test_classification_identifies_kernel_or_scheduler_dominance() -> None:
    wall = np.full(1000, 1_600_000, dtype=np.int64)
    thread = wall.copy()
    wall[-20:] = 2_200_000

    result = attribution.classify_attribution(
        wall,
        thread,
        slow_reference_ms=1.8,
    )

    assert result["classification"] == "KERNEL_OR_SCHEDULER_DOMINANT"
    assert result["wall_slow_ticks"] == 20
    assert result["thread_slow_ticks"] == 0
    assert result["wall_slow_not_thread_slow_fraction"] == 1.0


def test_classification_identifies_scheduled_compute_dominance() -> None:
    wall = np.full(1000, 1_600_000, dtype=np.int64)
    thread = wall.copy()
    wall[-20:] = 2_200_000
    thread[-20:] = 2_100_000

    result = attribution.classify_attribution(
        wall,
        thread,
        slow_reference_ms=1.8,
    )

    assert result["classification"] == "SCHEDULED_COMPUTE_DOMINANT"
    assert result["wall_slow_ticks"] == 20
    assert result["thread_slow_ticks"] == 20
    assert result["wall_slow_and_thread_slow_fraction"] == 1.0


def test_classification_preserves_mixed_and_no_slow_outcomes() -> None:
    wall = np.full(1000, 1_600_000, dtype=np.int64)
    thread = wall.copy()
    wall[-20:] = 2_200_000
    thread[-10:] = 2_100_000
    mixed = attribution.classify_attribution(
        wall,
        thread,
        slow_reference_ms=1.8,
    )
    assert mixed["classification"] == "MIXED"
    assert mixed["wall_slow_and_thread_slow_fraction"] == 0.5

    no_slow = attribution.classify_attribution(
        np.full(1000, 1_600_000, dtype=np.int64),
        np.full(1000, 1_590_000, dtype=np.int64),
        slow_reference_ms=1.8,
    )
    assert no_slow["classification"] == "NO_CURRENT_SLOW_POPULATION"
    assert no_slow["wall_slow_ticks"] == 0


def test_counter_delta_keeps_only_changed_cpu7_counters() -> None:
    before = {
        "softirqs": {"RCU": 10, "TIMER": 5},
        "interrupts": {"irq13:arch_timer": 100},
    }
    after = {
        "softirqs": {"RCU": 12, "TIMER": 5},
        "interrupts": {"irq13:arch_timer": 105},
    }

    assert attribution.counter_delta(before, after) == {
        "interrupts": {"irq13:arch_timer": 5},
        "softirqs": {"RCU": 2},
    }


def test_attribution_runner_has_no_robot_interface_imports() -> None:
    source = (ROOT / "tools/run_t247_x5_thread_cpu_attribution.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "import serial",
        "import smbus2",
        "import pygame",
        "open_duck_x5.runtime",
        "open_duck_x5.bus",
        "open_duck_x5.sensors",
    ):
        assert forbidden not in source
    assert source.index("preflight_values, preflight_checks = platform_preflight") < (
        source.index("router = base.router_session")
    )
