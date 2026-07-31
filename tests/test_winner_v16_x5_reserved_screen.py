from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

PREREGISTRATION = Path(
    "artifacts/gates/phase_5_policy/"
    "t251a5_x5_target_reserved_screen_preregistration_20260731.json"
)
RUNNER = Path("tools/run_winner_v16_x5_reserved_screen.py")
LAUNCHER = Path("setup/run_winner_v16_x5_reserved_screen.sh")


def test_t251a5_x5_screen_is_exactly_preregistered_and_cannot_deploy() -> None:
    assert hashlib.sha256(PREREGISTRATION.read_bytes()).hexdigest() == (
        "37888047ab8b508463835e024706490dcf6aaceec4352a6801fd44c2de67a8c3"
    )
    value = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    assert value["status"] == "PREREGISTERED_T251A5_X5_TARGET_RESERVED_SCREEN"
    assert value["earned_by"]["status"] == "PASS_T251A5_TARGET_CPU_CONTRACT"
    assert value["earned_by"]["all_2298_ticks_byte_exact"] is True
    assert value["earned_by"]["local_target_median_ratio"] <= 0.75
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


def test_t251a5_x5_runner_is_cpu_only_and_pins_preregistration() -> None:
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
    digest = "37888047ab8b508463835e024706490dcf6aaceec4352a6801fd44c2de67a8c3"
    assert f'PREREGISTRATION_SHA256 = "{digest}"' in source
    assert 'EXPECTED_ROOT = Path("/home/sunrise/open_duck_x5_preflight/t251a5")' in source
    assert '"external_send_implementation": False' in source
    assert '"serial_gpio_i2c_controller_or_torque_access": False' in source
    assert '"policy_deployed": False' in source
    assert '"gate5": False' in source


def test_t251a5_x5_runner_help_has_only_isolated_asset_paths() -> None:
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


def test_t251a5_x5_launcher_restores_governor_and_exposes_no_robot_path() -> None:
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
    assert 'staging_root_expected="/home/sunrise/open_duck_x5_preflight/t251a5"' in source
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
