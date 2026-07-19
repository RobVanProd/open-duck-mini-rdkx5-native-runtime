from __future__ import annotations

from pathlib import Path


def _script() -> str:
    return (Path(__file__).parents[1] / "setup" / "run_gate3_sensor_matrix.sh").read_text(
        encoding="utf-8"
    )


def _arguments() -> str:
    return _script().split("while [[ $# -gt 0 ]]", 1)[1].split("done", 1)[0]


def test_gate3_runner_freezes_complete_no_servo_population() -> None:
    script = _script()
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
