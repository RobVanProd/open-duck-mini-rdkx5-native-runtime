from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
RUNNER = Path("setup/run_gate3_sensor_matrix.sh")


def _script() -> str:
    return (ROOT / RUNNER).read_text(encoding="utf-8")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(RUNNER), *args],
        cwd=ROOT,
        input="",
        capture_output=True,
        text=True,
        check=False,
    )


def _arguments() -> str:
    return _script().split("while [[ $# -gt 0 ]]", 1)[1].split("done", 1)[0]


def test_gate3_runner_freezes_complete_no_servo_population() -> None:
    script = _script()
    assert "__FROZEN_GATE3_" not in script
    assert "1792d9c6975c328a7349efb5b4baec57852d39b3" in script
    assert "3ab9e7161e04f4faf39acaf03bca3ad4868eab7b16ec94f2861cb10b64866ed0" in script
    assert "131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b" in script
    assert "e7518b0df8614c1d399c789fd26aa9888043ebacfccc98ef75a5010a4b8c34be" in script
    assert "a3552b357dc2d0e6a876c8e8406134ab36fa6e88a7b7f444c9f9d25122a9da08" in script
    assert 'readonly samples="250"' in script
    assert 'readonly frequency_hz="50"' in script
    assert 'readonly sensor_frequency_hz="100"' in script
    assert 'readonly stale_after_ms="40"' in script
    assert 'readonly imu_bus="5"' in script
    assert 'readonly imu_address="0x28"' in script
    assert "servo_bus_accessed" in script
    assert "torque_enabled" in script
    assert "goal_position_writes" in script
    assert "policy_loaded" in script


def test_gate3_runner_requires_exact_interactive_labels_and_guards() -> None:
    script = _script()
    for label in (
        "upright",
        "nose_forward",
        "nose_back",
        "left_tilt",
        "right_tilt",
        "no_contacts",
        "left_contact",
        "right_contact",
        "both_contacts",
    ):
        assert label in script
    assert "interactive_operator_terminal_required" in script
    assert '[[ "${confirmed_label}" != "${label}" ]]' in script
    assert "--operator-confirmed-label" in script
    assert "--hardware-authorized" in script
    assert "--suspended-or-benched" in script
    assert "missing_gate3_hardware_acknowledgements" in script


def test_gate3_runner_validates_calibration_and_every_label_before_advancing() -> None:
    script = _script()
    calibration_validation = script.index("open_duck_x5.imu_calibration_review")
    label_loop = script.index('for label in "${labels[@]}"')
    label_validation = script.index("open_duck_x5.gate3_label_validation")
    final_validation = script.index("open_duck_x5.gate3_validation")
    assert calibration_validation < label_loop < label_validation < final_validation
    assert "HALTED_LABEL_VALIDATION" in script
    assert "DATA_INTEGRITY_ACCEPTED" in script
    assert "gate3_passed=false" in script


def test_gate3_runner_exposes_no_population_or_hardware_override() -> None:
    arguments = _arguments()
    for forbidden in (
        "--samples)",
        "--frequency-hz)",
        "--sensor-frequency-hz)",
        "--stale-after-ms)",
        "--imu-bus)",
        "--imu-address)",
        "--label)",
        "--device)",
        "--policy)",
        "--enable-torque)",
    ):
        assert forbidden not in arguments
    for required in (
        "--source-archive)",
        "--config)",
        "--calibration-dir)",
        "--output-dir)",
    ):
        assert required in arguments


def test_gate3_runner_terminates_active_probe_and_cleans_bounded_temp() -> None:
    script = _script()
    assert "trap cleanup EXIT" in script
    assert 'kill -TERM "${active_probe_pid}"' in script
    assert "/tmp/open-duck-gate3.*" in script
    assert 'rm -rf -- "${work_dir}"' in script


def test_gate3_runner_exits_before_preflight_without_hardware_acknowledgements() -> None:
    result = _run()

    assert result.returncode == 2
    assert "missing_gate3_hardware_acknowledgements" in result.stderr
    assert "frozen_source_archive_missing" not in result.stderr
    assert "i2c_device_missing" not in result.stderr


def test_gate3_runner_exits_before_source_or_device_access_without_tty() -> None:
    result = _run("--hardware-authorized", "--suspended-or-benched")

    assert result.returncode == 2
    assert "interactive_operator_terminal_required" in result.stderr
    assert "frozen_source_archive_missing" not in result.stderr
    assert "i2c_device_missing" not in result.stderr


def test_gate3_runner_help_is_safe_and_unknown_arguments_fail_closed() -> None:
    help_result = _run("--help")
    bad_result = _run("--enable-torque")

    assert help_result.returncode == 0
    assert "Runs exactly nine interactive, no-servo Gate 3 sensor captures" in (
        help_result.stdout
    )
    assert bad_result.returncode == 2
    assert "unknown_argument argument=--enable-torque" in bad_result.stderr
