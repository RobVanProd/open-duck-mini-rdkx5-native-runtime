from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

PREREGISTRATION = Path(
    "artifacts/gates/phase_5_policy/"
    "t251a_x5_compute_attribution_preregistration_20260731.json"
)
RUNNER = Path("tools/run_winner_v13_x5_compute_attribution.py")
LAUNCHER = Path("setup/run_winner_v13_x5_compute_attribution.sh")
REVIEW = Path(
    "artifacts/gates/phase_5_policy/"
    "t251a_x5_compute_attribution_review_20260731.json"
)


def load_runner_module() -> object:
    import importlib.util

    spec = importlib.util.spec_from_file_location("t251a_runner", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_t251a_preregistration_is_exact_attribution_only() -> None:
    assert hashlib.sha256(PREREGISTRATION.read_bytes()).hexdigest() == (
        "c113807cff15d7638015f5463ff6a363e25554db6ee9d6f45d13a65e48f42634"
    )
    value = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    assert value["status"] == "PREREGISTERED_T251A_X5_COMPUTE_ATTRIBUTION"
    assert value["earned_by"]["status"] == "HOLD_T251_X5_NO_MOTION_CPU_PREFLIGHT"
    assert [arm["id"] for arm in value["arms_in_fixed_order"]] == [
        "full_host_gc_enabled",
        "full_host_gc_disabled",
        "graph_only_gc_disabled",
        "component_profile_gc_disabled",
    ]
    assert value["unchanged_contract"]["t251_limits_ms"] == {
        "p99": 2.0,
        "p99_9": 3.0,
        "max": 5.0,
    }
    decision = value["decision_rule"]
    assert decision["no_threshold_change"] is True
    assert decision["no_t251_pass_claim"] is True
    assert decision["no_blind_rerun"] is True
    assert decision["policy_training_earned"] is False
    assert decision["production_integration_earned"] is False
    assert decision["gate5_earned"] is False
    authority = value["authority"]
    assert authority["serial_bus"] is False
    assert authority["servo_reads_or_writes"] is False
    assert authority["sensors"] is False
    assert authority["torque"] is False
    assert authority["motion"] is False
    assert authority["policy_deployment"] is False


def test_t251a_runner_imports_no_robot_interface() -> None:
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"), filename=str(RUNNER))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add("." * node.level + (node.module or ""))
    assert imported.isdisjoint(
        {
            "serial",
            "smbus2",
            "pygame",
            "open_duck_x5.runtime",
            "open_duck_x5.servo_bus",
            "open_duck_x5.sensors",
        }
    )
    source = RUNNER.read_text(encoding="utf-8")
    assert '"t251_rerun": False' in source
    assert '"threshold_changed": False' in source
    assert '"gate5": False' in source


def test_t251a_runner_help_is_isolated_and_no_motion() -> None:
    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    for flag in (
        "--staging-root",
        "--calibrator",
        "--policy",
        "--p30-fit",
        "--reference-table",
        "--output",
        "--raw-output",
    ):
        assert flag in completed.stdout


def test_t251a_summary_and_classifier_are_deterministic() -> None:
    module = load_runner_module()
    summary = module.summary_ns(np.asarray([1_000_000, 2_000_000, 6_000_000]))
    assert summary["samples"] == 3
    assert summary["max_ms"] == 6.0
    assert summary["over_2ms"] == 1
    assert summary["over_3ms"] == 1
    assert summary["over_5ms"] == 1
    arms = {
        "full_host_gc_enabled": {"stage_locomotion": {"p99_ms": 2.1, "max_ms": 8.0}},
        "full_host_gc_disabled": {"stage_locomotion": {"p99_ms": 1.9, "max_ms": 4.0}},
        "graph_only_gc_disabled": {"stage_locomotion": {"p99_ms": 1.5, "max_ms": 3.0}},
    }
    assert module.classify(arms) == {
        "steady": "STEADY_T251_P99_RECOVERABLE_WITH_CURRENT_GRAPH_AND_HOST",
        "tail": "PYTHON_GC_TAIL",
    }


def test_t251a_launcher_restores_governor_and_exposes_no_robot_path() -> None:
    subprocess.run(["bash", "-n", str(LAUNCHER)], check=True)
    completed = subprocess.run(
        ["bash", str(LAUNCHER), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "synthetic-state CPU attribution" in completed.stdout
    assert "no serial" in completed.stdout
    source = LAUNCHER.read_text(encoding="utf-8")
    assert 'staging_root_expected="/home/sunrise/open_duck_x5_preflight/t251a"' in source
    assert "restore_governor" in source
    assert "trap cleanup EXIT" in source
    assert 'taskset -c "$rt_cpu" chrt -f "$rt_priority"' in source
    assert "/dev/tty" not in source
    assert "enable-torque" not in source


def test_t251a_review_attributes_both_failures_without_advancing() -> None:
    assert hashlib.sha256(REVIEW.read_bytes()).hexdigest() == (
        "7f63a03450474464b69a2298d5e3e0266f7877b3773fe0a7a368d64fd9c35959"
    )
    value = json.loads(REVIEW.read_text(encoding="utf-8"))
    assert value["status"] == "PASS_T251A_X5_COMPUTE_ATTRIBUTION_REVIEW"
    assert value["source_result"]["canonical_sha256"] == (
        "8f6e6307bf082a33bc50774a1225a6c40f61259e6726ac604f3ff175293a90ce"
    )
    assert value["tail_attribution"]["status"] == (
        "ATTRIBUTED_LINUX_RT_BANDWIDTH_THROTTLING"
    )
    assert value["steady_attribution"]["status"] == (
        "ATTRIBUTED_PYTHON_HOST_OVERHEAD_WITH_GRAPH_FLOOR_GREEN"
    )
    assert value["decision"] == {
        "next": "EARN_DEFAULT_OFF_BIT_EXACT_HOST_OPTIMIZATION_AND_PACED_CPU_SCREEN",
        "threshold_change": False,
        "t251_pass_claim": False,
        "blind_t251_rerun": False,
        "policy_training_earned": False,
        "production_integration_earned": False,
        "gate5_earned": False,
    }
