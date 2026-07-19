from __future__ import annotations

import re
from pathlib import Path

RUNNER = Path("setup/run_winner_v2_cpu_preflight.sh")


def _source() -> str:
    return RUNNER.read_text(encoding="utf-8")


def test_runner_is_locked_before_any_output_or_governor_action() -> None:
    source = _source()
    sentinel = 'expected_policy_envelope_sha256="PENDING_POLICY_ENVELOPE_SHA256"'
    guard = 'if [[ ! "$expected_policy_envelope_sha256" =~ ^[0-9a-f]{64}$ ]]'
    assert sentinel in source
    assert source.index(guard) < source.index("mkdir -p \"$output_dir\"")
    assert source.index(guard) < source.index("performance >\"$governor_path\"")


def test_runner_has_no_servo_device_or_motion_surface() -> None:
    source = _source().lower()
    for forbidden in (
        "/dev/tty",
        "--device",
        "torque-enable",
        "enable_torque",
        "write_positions",
        "fixed-command-x",
        "gate5-authorized",
    ):
        assert forbidden not in source
    assert "--no-servo-access" in source
    assert '"no_servo_access": true' in source


def test_runner_freezes_population_rt_and_threshold_implementation() -> None:
    source = _source()
    assert "readonly ticks_per_command=10000" in source
    assert "readonly rt_cpu=7" in source
    assert "readonly rt_priority=80" in source
    assert "taskset -c \"$rt_cpu\" chrt -f \"$rt_priority\"" in source
    assert "--ticks-per-command \"$ticks_per_command\"" in source
    assert "T2_EQUAL_512000.onnx" in source


def test_runner_pins_complete_source_and_asset_identity() -> None:
    source = _source()
    expected = {
        "expected_source_commit": 40,
        "expected_source_archive_sha256": 64,
        "expected_preflight_module_sha256": 64,
        "expected_config_sha256": 64,
        "expected_handoff_manifest_sha256": 64,
        "expected_selected_onnx_sha256": 64,
    }
    for name, length in expected.items():
        match = re.search(rf'readonly {name}="([0-9a-f]+)"', source)
        assert match is not None
        assert len(match.group(1)) == length


def test_runner_restores_governor_and_preserves_false_authority() -> None:
    source = _source()
    assert "trap cleanup EXIT INT TERM" in source
    assert "governor_before" in source
    assert "governor-after.txt" in source
    assert '"robot_clearance": False' in source
    assert '"gate5": False' in source
    assert '"motion": False' in source
    assert '"torque": False' in source
