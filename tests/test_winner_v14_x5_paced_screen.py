from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from tools.winner_v14_optimized import WinnerV14X5OptimizedTransaction

PREREGISTRATION = Path(
    "artifacts/gates/phase_5_policy/"
    "t251a2_x5_optimized_paced_screen_preregistration_20260731.json"
)
RUNNER = Path("tools/run_winner_v14_x5_paced_screen.py")
LAUNCHER = Path("setup/run_winner_v14_x5_paced_screen.sh")
RESULT = Path(
    "artifacts/gates/phase_5_policy/"
    "t251a2_x5_optimized_paced_screen_result_20260731.json"
)
REVIEW = Path(
    "artifacts/gates/phase_5_policy/"
    "t251a2_x5_optimized_paced_screen_review_20260731.json"
)


def load_runner_module() -> object:
    import importlib.util

    spec = importlib.util.spec_from_file_location("t251a2_runner", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_t251a2_preregistration_is_exact_screen_only() -> None:
    assert hashlib.sha256(PREREGISTRATION.read_bytes()).hexdigest() == (
        "cd9e71c724087f1ecffa4e4d6f0c462df3780b64a6723d094bcfab60692b1ebc"
    )
    value = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    assert value["status"] == "PREREGISTERED_T251A2_X5_OPTIMIZED_PACED_SCREEN"
    assert value["unchanged_assets"]["candidate_id"] == (
        "T247_HOME_NEGATIVE_HALF_ADAPTER_FINAL"
    )
    assert value["implementation"]["default_enabled"] is False
    assert value["screen"]["calibration_ticks"] == 250
    assert value["screen"]["home_return_ticks"] == 0
    assert value["screen"]["locomotion_ticks"] == 2_048
    assert value["screen"]["release_period_ns"] == 20_000_000
    assert value["timing_screen_ms"] == {
        "p99_max": 1.8,
        "p99_9_max": 2.5,
        "max_max": 4.0,
        "derivation": (
            "fixed engineering reserve below unchanged T251 limits: 0.2 ms at p99, "
            "0.5 ms at p99.9, and 1.0 ms at max"
        ),
    }
    decision = value["decision_rule"]
    assert decision["pass"] == (
        "EARN_ONE_CORRECTED_T251B_10000_TICK_PREREGISTRATION_ONLY"
    )
    assert decision["threshold_change"] is False
    assert decision["policy_training_earned"] is False
    assert decision["production_integration_earned"] is False
    assert decision["gate5_earned"] is False


def test_t251a2_runner_is_no_device_and_requires_exact_t247_assets() -> None:
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
    assert "PREREGISTRATION_SHA256" in source
    assert "EXPECTED_ROOT = Path(\"/home/sunrise/open_duck_x5_preflight/t251a2\")" in source
    assert '"byte_exact_every_tick"' in source
    assert '"external_send_implementation": False' in source
    assert '"serial_gpio_i2c_controller_or_torque_access": False' in source
    assert '"t251_rerun": False' in source
    assert '"policy_deployed": False' in source
    assert '"gate5": False' in source


def test_t251a2_runner_help_and_summary_are_deterministic() -> None:
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
    module = load_runner_module()
    summary = module.summary_ns(np.asarray([1_000_000, 2_000_000, 6_000_000]))
    assert summary["samples"] == 3
    assert summary["p99_ms"] == 5.92
    assert summary["max_ms"] == 6.0


def test_t251a2_launcher_restores_governor_and_exposes_no_robot_path() -> None:
    subprocess.run(["bash", "-n", str(LAUNCHER)], check=True)
    completed = subprocess.run(
        ["bash", str(LAUNCHER), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "synthetic-state optimized paced CPU screen" in completed.stdout
    assert "no serial" in completed.stdout
    source = LAUNCHER.read_text(encoding="utf-8")
    assert 'staging_root_expected="/home/sunrise/open_duck_x5_preflight/t251a2"' in source
    assert "readonly rt_cpu=7" in source
    assert "readonly rt_priority=80" in source
    assert "restore_governor" in source
    assert "trap cleanup EXIT" in source
    assert 'taskset -c "$rt_cpu" chrt -f "$rt_priority"' in source
    assert "--x5-cpu-screen-authorized" in source
    assert "--no-robot-device-access" in source
    assert "/dev/tty" not in source
    assert "--hardware-authorized" not in source
    assert "--suspended-or-benched" not in source
    assert "enable-torque" not in source


def test_winner_v14_optimization_is_default_disabled_and_not_in_production() -> None:
    assert WinnerV14X5OptimizedTransaction.__mro__[1].__name__ == (
        "WinnerV13StateCoherentTransaction"
    )
    production_sources = Path("src/open_duck_x5").glob("*.py")
    for path in production_sources:
        assert "winner_v14_optimized" not in path.read_text(encoding="utf-8")


def test_t251a2_result_is_exact_hold_and_does_not_earn_t251b() -> None:
    assert hashlib.sha256(RESULT.read_bytes()).hexdigest() == (
        "dcc1472d5a98127b5c8434363e14eb1e879af6d63c40a8933e08d0c7ed1f7fc8"
    )
    value = json.loads(RESULT.read_text(encoding="utf-8"))
    assert value["status"] == "HOLD_T251A2_X5_OPTIMIZED_PACED_SCREEN"
    assert value["result_sha256"] == (
        "291daa5f92f49930d9094ac5aaa31db4b6b01a460aebccafbab09044bf9713e5"
    )
    assert value["failed_checks"] == [
        "optimized_p99_9_with_reserve",
        "optimized_p99_with_reserve",
    ]
    assert sum(value["checks"].values()) == 13
    assert value["checks"]["byte_exact_every_tick"] is True
    assert value["execution"]["mismatch"] is None
    assert value["execution"]["locomotion_ticks"] == 2_048
    assert value["execution"]["optimized_stage_locomotion"]["p99_ms"] == 2.17971376
    assert value["authority"]["policy_deployed"] is False
    assert value["authority"]["servo_reads_or_writes"] is False
    assert value["authority"]["motion"] is False
    assert value["authority"]["gate5"] is False


def test_t251a2_review_keeps_thresholds_and_gate5_frozen() -> None:
    assert hashlib.sha256(REVIEW.read_bytes()).hexdigest() == (
        "e73dab1b84a36f39de653ac3e5f26596e440bb1c7a8589690c28f812e85907c9"
    )
    value = json.loads(REVIEW.read_text(encoding="utf-8"))
    assert value["status"] == "HOLD_T251A2_X5_OPTIMIZED_PACED_SCREEN_REVIEWED"
    assert value["source_result"]["canonical_sha256"] == (
        "291daa5f92f49930d9094ac5aaa31db4b6b01a460aebccafbab09044bf9713e5"
    )
    assert value["semantic_result"]["byte_exact_ticks"] == 2_298
    assert value["semantic_result"]["mismatch"] is None
    assert value["decision"]["t251b_earned"] is False
    assert value["decision"]["threshold_change"] is False
    assert value["decision"]["blind_rerun"] is False
    assert value["decision"]["production_integration_earned"] is False
    assert value["decision"]["gate5_earned"] is False
