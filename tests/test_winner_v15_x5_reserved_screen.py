from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

PREREGISTRATION = Path(
    "artifacts/gates/phase_5_policy/"
    "t251a4_x5_graph_host_reserved_screen_preregistration_20260731.json"
)
RUNNER = Path("tools/run_winner_v15_x5_reserved_screen.py")
LAUNCHER = Path("setup/run_winner_v15_x5_reserved_screen.sh")
RESULT = Path(
    "artifacts/gates/phase_5_policy/"
    "t251a4_x5_graph_host_reserved_screen_result_20260731.json"
)
REVIEW = Path(
    "artifacts/gates/phase_5_policy/"
    "t251a4_x5_graph_host_reserved_screen_review_20260731.json"
)


def test_t251a4_x5_screen_is_exactly_preregistered_and_cannot_deploy() -> None:
    digest = hashlib.sha256(PREREGISTRATION.read_bytes()).hexdigest()
    assert digest == "ac4b05540c51cafd669d14d380d2a6c432fbbf5dc093feec2fb1208e0e7710d8"
    value = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    assert value["status"] == "PREREGISTERED_T251A4_X5_GRAPH_HOST_RESERVED_SCREEN"
    assert value["earned_by"]["status"] == "PASS_T251A4_GRAPH_HOST_CPU_CONTRACT"
    assert [arm["id"] for arm in value["arms_in_fixed_order"]] == [
        "separated_semantic_equivalence",
        "single_corrected_reserved_timing",
    ]
    assert value["arms_in_fixed_order"][0]["timing_selection_weight"] == 0
    assert value["arms_in_fixed_order"][1]["timing_selection_weight"] == 1
    assert value["reference_reserve_limits_ms"] == {
        "p99_ms": 1.8,
        "p99_9_ms": 2.5,
        "max_ms": 4.0,
        "provenance": (
            "unchanged T251A2/T251A3 reference-only reserve; no threshold adjustment"
        ),
    }
    assert value["decision_rule"]["rerun"] is False
    assert value["decision_rule"]["threshold_change"] is False
    assert value["decision_rule"]["t251b_executed"] is False
    assert value["decision_rule"]["gate5_earned"] is False
    assert value["authority"]["single_x5_cpu_execution"] is True
    assert value["authority"]["serial_bus"] is False
    assert value["authority"]["torque"] is False
    assert value["authority"]["motion"] is False
    assert value["authority"]["policy_deployment"] is False


def test_t251a4_x5_runner_is_cpu_only_and_pins_preregistration() -> None:
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
    preregistration_digest = (
        "ac4b05540c51cafd669d14d380d2a6c432fbbf5dc093feec2fb1208e0e7710d8"
    )
    assert f'PREREGISTRATION_SHA256 = "{preregistration_digest}"' in source
    assert 'EXPECTED_ROOT = Path("/home/sunrise/open_duck_x5_preflight/t251a4")' in source
    assert '"external_send_implementation": False' in source
    assert '"serial_gpio_i2c_controller_or_torque_access": False' in source
    assert '"policy_deployed": False' in source
    assert '"gate5": False' in source


def test_t251a4_x5_runner_help_has_only_isolated_asset_paths() -> None:
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


def test_t251a4_x5_launcher_restores_governor_and_exposes_no_robot_path() -> None:
    subprocess.run(["bash", "-n", str(LAUNCHER)], check=True)
    completed = subprocess.run(
        ["bash", str(LAUNCHER), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "semantic and single-host" in completed.stdout
    assert "no serial" in completed.stdout
    source = LAUNCHER.read_text(encoding="utf-8")
    assert 'staging_root_expected="/home/sunrise/open_duck_x5_preflight/t251a4"' in source
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


def test_t251a4_x5_result_is_exact_hold_with_only_p99_failed() -> None:
    assert hashlib.sha256(RESULT.read_bytes()).hexdigest() == (
        "556790fcf338003e05787a9a5c9bc1164c537999fe2f5f1fd8b8901dc8cd91e1"
    )
    value = json.loads(RESULT.read_text(encoding="utf-8"))
    assert value["status"] == "HOLD_T251A4_X5_GRAPH_HOST_RESERVED_SCREEN"
    assert value["result_sha256"] == (
        "3fdc034f7bb23c689332e7f5f020191fcae993f06a20f39f33574420638056d3"
    )
    assert value["failed_checks"] == ["stage_p99_within_reserve"]
    assert sum(value["checks"].values()) == 17
    assert value["semantic_passed"] is True
    assert value["reference_reserve_passed"] is False
    semantic = value["semantic_arm"]
    assert semantic["mismatch"] is None
    assert semantic["predecessor_action_trace_sha256"] == semantic[
        "corrected_action_trace_sha256"
    ]
    assert semantic["maximum_rate_excess_rad_s"] == 0.0
    timing = value["timing_arm"]["stage_locomotion"]
    assert timing["p99_ms"] == 2.03906
    assert timing["p99_9_ms"] == 2.4417013490000015
    assert timing["max_ms"] == 2.517046
    assert value["decision"] == "CLOSE_GRAPH_HOST_CORRECTION_WITHOUT_T251B"
    assert value["authority"]["t251b_earned"] is False
    assert value["authority"]["policy_deployed"] is False
    assert value["authority"]["torque"] is False
    assert value["authority"]["motion"] is False
    assert value["authority"]["gate5"] is False


def test_t251a4_review_closes_graph_host_and_selects_only_target_next() -> None:
    assert hashlib.sha256(REVIEW.read_bytes()).hexdigest() == (
        "e856ccce28a051d96b4fd4b2879ff2fec5ce8f6b7b40984418fe336ae79b6b10"
    )
    value = json.loads(REVIEW.read_text(encoding="utf-8"))
    assert value["status"] == (
        "HOLD_T251A4_X5_GRAPH_HOST_RESERVED_SCREEN_REVIEWED"
    )
    assert value["source_result"]["file_sha256"] == (
        "556790fcf338003e05787a9a5c9bc1164c537999fe2f5f1fd8b8901dc8cd91e1"
    )
    assert value["semantic_result"]["all_2298_ticks_byte_exact"] is True
    assert value["measured_effect"]["correction_materially_reduced_host_time"] is True
    assert value["measured_effect"]["correction_clears_frozen_reserve"] is False
    assert value["next_measured_component"]["name"] == "target"
    assert value["decision"]["graph_host_correction"] == "CLOSED_WITHOUT_T251B"
    assert value["decision"]["t251b_earned"] is False
    assert value["authority"]["x5_execution"] is False
    assert value["authority"]["motion"] is False
