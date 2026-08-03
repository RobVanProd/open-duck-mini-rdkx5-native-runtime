from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

VERIFIER = Path("tools/verify_winner_v13_state_coherent.py")
RESULT = Path(
    "artifacts/gates/phase_5_policy/t250_state_coherent_runtime_integration_result_20260731.json"
)


def test_verifier_is_offline_exact_asset_execution() -> None:
    source = VERIFIER.read_text(encoding="utf-8")
    assert "PREREGISTRATION_SHA256" in source
    assert "LOCOMOTION_TICKS = 8" in source
    assert '"exact_250_calibration_ticks"' in source
    assert '"real_graph_chain_bit_exact"' in source
    assert '"independent_p30_observer_exact"' in source
    assert '"cpu_only_no_hardware_execution": True' in source
    assert '"rdkx5_or_robot_access": 0' in source
    assert '"gate5": False' in source
    assert "serial.Serial" not in source
    assert '"smbus2"' in source  # forbidden-import declaration, never an import


def test_verifier_does_not_import_robot_interfaces() -> None:
    tree = ast.parse(VERIFIER.read_text(encoding="utf-8"), filename=str(VERIFIER))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add("." * node.level + (node.module or ""))
    forbidden = {
        "serial",
        "smbus2",
        "pygame",
        "open_duck_x5.runtime",
        "open_duck_x5.servo_bus",
    }
    assert imported.isdisjoint(forbidden)


def test_verifier_help_requires_explicit_assets_and_outputs() -> None:
    completed = subprocess.run(
        [sys.executable, str(VERIFIER), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    for flag in (
        "--calibrator",
        "--policy",
        "--p30-fit",
        "--reference-table",
        "--output",
        "--markdown",
    ):
        assert flag in completed.stdout


def test_frozen_real_asset_result_is_green_and_authority_bounded() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    basis = {key: value for key, value in result.items() if key != "result_sha256"}
    canonical = json.dumps(
        basis,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == result["result_sha256"]
    assert result["status"] == "PASS_T250_STATE_COHERENT_RUNTIME_INTEGRATION"
    assert result["decision"] == "EARN_NO_MOTION_X5_CPU_PREFLIGHT_PREREGISTRATION_ONLY"
    assert result["failed_checks"] == []
    assert len(result["checks"]) == 25
    assert all(result["checks"].values())
    assert result["execution"]["calibration_ticks"] == 250
    assert result["execution"]["home_return_ticks"] == 0
    assert result["execution"]["rdkx5_or_robot_access"] == 0
    assert result["execution"]["hosted_compute_units"] == 0
    assert result["maximum_deltas"] == {
        "calibration_observation_field": 0.0,
        "direct_onnx_action_or_state": 0.0,
        "handoff_context": 0.0,
        "handoff_previous_action": 0.0,
        "independent_observer_rad": 0.0,
        "locomotion_observation_field": 0.0,
        "logical_target_rad": 0.0,
        "measured_rate_excess_rad_s": 0.0,
        "measured_rate_monitor_rad_s": 0.0,
        "physical_target_rad": 0.0,
    }
    assert result["authority"] == {
        "gate5": False,
        "grounded_replay": False,
        "no_motion_x5_cpu_preflight": False,
        "offline_cpu_only": True,
        "policy_binary_staging": False,
        "robot_motion": False,
    }
