from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

PREREGISTRATION = Path(
    "artifacts/gates/phase_5_policy/t251_x5_no_motion_cpu_preflight_preregistration_20260731.json"
)
RUNNER = Path("tools/run_winner_v13_x5_cpu_preflight.py")
LAUNCHER = Path("setup/run_winner_v13_x5_cpu_preflight.sh")
RESULT = Path(
    "artifacts/gates/phase_5_policy/"
    "t251_x5_no_motion_cpu_preflight_result_20260731.json"
)


def test_t251_preregistration_is_exact_and_no_motion() -> None:
    value = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    assert value["status"] == "PREREGISTERED_T251_X5_NO_MOTION_CPU_PREFLIGHT"
    assert value["earned_by"]["status"] == ("PASS_T250_STATE_COHERENT_RUNTIME_INTEGRATION")
    runner = value["runner_contract"]
    assert runner["provider"] == "CPUExecutionProvider only"
    assert runner["scheduler"] == "SCHED_FIFO"
    assert runner["affinity"] == "exactly one CPU"
    assert runner["warmup_runs_per_graph"] == 10
    assert runner["calibration_ticks"] == 250
    assert runner["home_return_ticks"] == 0
    assert runner["locomotion_ticks"] == 10_000
    gates = value["preflight_gates"]
    assert gates["stage_latency_p99_ms_max"] == 2.0
    assert gates["stage_latency_p99_9_ms_max"] == 3.0
    assert gates["stage_latency_max_ms_max"] == 5.0
    assert value["decision_rule"]["gate5_on_pass"] is False
    assert value["decision_rule"]["robot_motion_on_pass"] is False
    authority = value["authority"]
    assert authority["offline_cpu_execution_on_x5"] is True
    assert authority["serial_bus"] is False
    assert authority["servo_reads_or_writes"] is False
    assert authority["torque"] is False
    assert authority["motion"] is False
    assert authority["policy_deployment"] is False
    assert authority["gate5"] is False


def test_t251_runner_is_exactly_bounded_to_cpu_only_x5_execution() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert "PREREGISTRATION_SHA256" in source
    assert "HOST_SOURCE_SHA256" in source
    assert 'machine not in {"aarch64", "arm64"}' in source
    assert "scheduler == os.SCHED_FIFO" in source
    assert 'governor == "performance"' in source
    assert "== 10_000" in source
    assert '"external_send_implementation": False' in source
    assert '"serial_gpio_i2c_controller_or_torque_access": False' in source
    assert '"gate5": False' in source


def test_t251_runner_imports_no_robot_interface() -> None:
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
        }
    )


def test_t251_runner_help_requires_isolated_staging_and_assets() -> None:
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
    ):
        assert flag in completed.stdout


def test_t251_launcher_restores_governor_and_exposes_no_robot_path() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")
    assert 'staging_root_expected="/home/sunrise/open_duck_x5_preflight/t251"' in source
    assert "readonly rt_cpu=7" in source
    assert "readonly rt_priority=80" in source
    assert "restore_governor" in source
    assert "trap cleanup EXIT" in source
    assert "trap 'exit 130' INT" in source
    assert 'taskset -c "$rt_cpu" chrt -f "$rt_priority"' in source
    assert "--x5-cpu-preflight-authorized" in source
    assert "--no-robot-device-access" in source
    assert "/dev/tty" not in source
    assert "--hardware-authorized" not in source
    assert "--suspended-or-benched" not in source
    assert "enable-torque" not in source


def test_t251_launcher_parses_and_help_is_cpu_only() -> None:
    subprocess.run(["bash", "-n", str(LAUNCHER)], check=True)
    completed = subprocess.run(
        ["bash", str(LAUNCHER), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "synthetic-state CPU/ONNX preflight" in completed.stdout
    assert "no serial" in completed.stdout
    assert "torque" in completed.stdout


def test_t251_result_is_exact_hold_and_does_not_advance_gate5() -> None:
    assert hashlib.sha256(RESULT.read_bytes()).hexdigest() == (
        "db5a038d3a0eee1155740276abef5e14a8044ac106a16b44198532b3f17bc01c"
    )
    value = json.loads(RESULT.read_text(encoding="utf-8"))
    assert value["status"] == "HOLD_T251_X5_NO_MOTION_CPU_PREFLIGHT"
    assert value["decision"] == (
        "HOLD_T250_X5_INTEGRATION_AND_ATTRIBUTE_WITHOUT_CHANGING_THRESHOLDS"
    )
    assert value["result_sha256"] == (
        "3e78002a6b1fb23e38881a0813a153678eaf1f53003ae613cf5a4ef9c5ba875c"
    )
    assert value["failed_checks"] == [
        "stage_latency_max",
        "stage_latency_p99",
        "stage_latency_p99_9",
    ]
    assert sum(value["checks"].values()) == 15
    timing = value["execution"]["stage_latency_compute_only"]
    assert timing["samples"] == 10_250
    assert timing["p99_ms"] == 3.45919992
    assert timing["p99_9_ms"] == 54.64240899400001
    assert timing["max_ms"] == 55.288782
    assert value["authority"]["policy_deployed"] is False
    assert value["authority"]["servo_reads_or_writes"] is False
    assert value["authority"]["torque"] is False
    assert value["authority"]["motion"] is False
    assert value["authority"]["gate5"] is False
