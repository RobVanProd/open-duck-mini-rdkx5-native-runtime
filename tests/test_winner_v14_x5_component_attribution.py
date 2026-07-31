from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

PREREGISTRATION = Path(
    "artifacts/gates/phase_5_policy/"
    "t251a3_x5_single_host_component_attribution_preregistration_20260731.json"
)
RUNNER = Path("tools/run_winner_v14_x5_component_attribution.py")
LAUNCHER = Path("setup/run_winner_v14_x5_component_attribution.sh")
RESULT = Path(
    "artifacts/gates/phase_5_policy/"
    "t251a3_x5_single_host_component_attribution_result_20260731.json"
)
REVIEW = Path(
    "artifacts/gates/phase_5_policy/"
    "t251a3_x5_single_host_component_attribution_review_20260731.json"
)


def test_t251a3_preregistration_is_exact_attribution_only() -> None:
    assert hashlib.sha256(PREREGISTRATION.read_bytes()).hexdigest() == (
        "3e2fb876070901eaa9167c5402f6017d5b653702971065df25515469cbbd6b8f"
    )
    value = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    assert value["status"] == (
        "PREREGISTERED_T251A3_X5_SINGLE_HOST_COMPONENT_ATTRIBUTION"
    )
    assert value["earned_by"]["status"] == (
        "HOLD_T251A2_X5_OPTIMIZED_PACED_SCREEN_REVIEWED"
    )
    assert [arm["id"] for arm in value["arms_in_fixed_order"]] == [
        "single_optimized_uninstrumented",
        "single_optimized_component_profile",
    ]
    assert value["arms_in_fixed_order"][0]["locomotion_ticks"] == 2_048
    assert value["arms_in_fixed_order"][1]["locomotion_ticks"] == 512
    assert value["reference_only_limits_ms"]["selection_weight"] == 0
    decision = value["decision_rule"]
    assert decision["t251b_earned"] is False
    assert decision["threshold_change"] is False
    assert decision["policy_training_earned"] is False
    assert decision["production_integration_earned"] is False
    assert decision["gate5_earned"] is False
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    for name, path in value["exact_sources"].items():
        if not name.endswith("_source"):
            continue
        expected = value["exact_sources"][f"{name}_sha256"]
        receipt_name = name.removesuffix("_source")
        assert result["source_receipts"][receipt_name]["sha256"] == expected
        assert Path(path).name == Path(result["source_receipts"][receipt_name]["path"]).name


def test_t251a3_runner_is_cpu_only_and_cannot_advance() -> None:
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
    assert "EXPECTED_ROOT = Path(\"/home/sunrise/open_duck_x5_preflight/t251a3\")" in source
    assert '"reference_reserve_selection_weight": 0' in source
    assert '"t251b_earned": False' in source
    assert '"external_send_implementation": False' in source
    assert '"serial_gpio_i2c_controller_or_torque_access": False' in source
    assert '"policy_deployed": False' in source
    assert '"gate5": False' in source


def test_t251a3_runner_help_requires_isolated_assets_and_outputs() -> None:
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


def test_t251a3_launcher_restores_governor_and_exposes_no_robot_path() -> None:
    subprocess.run(["bash", "-n", str(LAUNCHER)], check=True)
    completed = subprocess.run(
        ["bash", str(LAUNCHER), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "single-host component" in completed.stdout
    assert "no serial" in completed.stdout
    source = LAUNCHER.read_text(encoding="utf-8")
    assert 'staging_root_expected="/home/sunrise/open_duck_x5_preflight/t251a3"' in source
    assert "readonly rt_cpu=7" in source
    assert "readonly rt_priority=80" in source
    assert "restore_governor" in source
    assert "trap cleanup EXIT" in source
    assert 'taskset -c "$rt_cpu" chrt -f "$rt_priority"' in source
    assert "--x5-cpu-attribution-authorized" in source
    assert "--no-robot-device-access" in source
    assert "/dev/tty" not in source
    assert "--hardware-authorized" not in source
    assert "--suspended-or-benched" not in source
    assert "enable-torque" not in source


def test_t251a3_result_is_exact_complete_attribution_without_advancement() -> None:
    assert hashlib.sha256(RESULT.read_bytes()).hexdigest() == (
        "9a1d8abd970dca73622914b11272572747a3c81ecfcd81df73e9abe6456af23a"
    )
    value = json.loads(RESULT.read_text(encoding="utf-8"))
    assert value["status"] == "COMPLETE_T251A3_X5_SINGLE_HOST_COMPONENT_ATTRIBUTION"
    assert value["result_sha256"] == (
        "0b8d7dbbf8669d9dd23ef8bef7e50ee5a7d9a0d66fb4254a9661be89591f73cf"
    )
    assert value["failed_checks"] == []
    assert sum(value["checks"].values()) == 13
    assert value["attribution"]["single_host_clears_reference_reserve"] is False
    assert value["attribution"]["largest_non_onnx_host_component_by_p50"] == (
        "graph_host"
    )
    assert value["decision"] == "CHANGE_ONLY_MEASURED_HOST_COMPONENT:graph_host"
    assert value["authority"]["t251b_earned"] is False
    assert value["authority"]["threshold_changed"] is False
    assert value["authority"]["policy_deployed"] is False
    assert value["authority"]["motion"] is False
    assert value["authority"]["gate5"] is False


def test_t251a3_review_selects_only_graph_host_and_preserves_full_validation() -> None:
    assert hashlib.sha256(REVIEW.read_bytes()).hexdigest() == (
        "cc4e8cf6c1af2cc461c6d6c5f30235b9b068aa32555e3799ab4c8d97510e44f5"
    )
    value = json.loads(REVIEW.read_text(encoding="utf-8"))
    assert value["status"] == "PASS_T251A3_X5_SINGLE_HOST_COMPONENT_ATTRIBUTION_REVIEW"
    assert value["attribution"]["largest_non_onnx_host_component_by_p50"] == (
        "graph_host"
    )
    scope = value["selected_correction_scope"]
    assert scope["name"] == (
        "BOUND_GRAPH_INPUT_AND_SPLIT_CURRENT_ACTION_FROM_NEXT_STATE_VALIDATION"
    )
    assert any("retain the existing full" in item for item in scope["allowed"])
    assert any("removal of any full commit validation" in item for item in scope["forbidden"])
    assert value["decision"]["t251b_earned"] is False
    assert value["decision"]["gate5_earned"] is False
