from __future__ import annotations

from pathlib import Path


def _script() -> str:
    return (
        Path(__file__).parents[1] / "setup" / "run_automatic_configuration.sh"
    ).read_text(encoding="utf-8")


def _argument_cases() -> str:
    return _script().split("while [[ $# -gt 0 ]]", 1)[1].split("done", 1)[0]


def test_runner_is_physically_blocked_until_envelope_identity_is_frozen() -> None:
    script = _script()
    assert 'expected_policy_envelope_sha256="PENDING_POLICY_ENVELOPE_SHA256"' in script
    sentinel = script.index("policy_envelope_identity_not_frozen")
    serial_check = script.index('if [[ ! -c "${device}" ]]')
    assert sentinel < serial_check


def test_runner_freezes_source_hardware_and_population() -> None:
    script = _script()
    assert "d43ce270d9c24d075e7baf02efc741d65bb12f47" in script
    assert "ff1c22716430cc15b4c60d340375976959c2a2a5524c68b0e7c1bf6aa473116c" in script
    assert "131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b" in script
    assert "e7518b0df8614c1d399c789fd26aa9888043ebacfccc98ef75a5010a4b8c34be" in script
    assert 'readonly device="/dev/ttyS1"' in script
    assert "--ticks 10000" in script
    assert "--amplitude-rad 0" in script
    assert '"calibration_ticks": 2_814' in script
    assert "--rt-cpu 7" in script
    assert "--rt-priority 80" in script


def test_runner_requires_exact_hardware_and_motion_acknowledgements() -> None:
    cases = _argument_cases()
    for required in (
        "--hardware-authorized)",
        "--suspended-or-benched)",
        "--moving-gate-authorized)",
        "--configuration-calibration-authorized)",
    ):
        assert required in cases
    assert "missing_automatic_configuration_acknowledgements" in _script()


def test_runner_exposes_no_frozen_scope_override() -> None:
    cases = _argument_cases()
    for blocked in (
        "--device)",
        "--baudrate)",
        "--timeout-ms)",
        "--ticks)",
        "--amplitude-rad)",
        "--rt-cpu)",
        "--rt-priority)",
        "--i2c-bus)",
    ):
        assert blocked not in cases
    for allowed in (
        "--source-archive)",
        "--config)",
        "--imu-calibration)",
        "--policy-envelope)",
        "--output-dir)",
    ):
        assert allowed in cases


def test_runner_orders_preflight_before_collection_and_support_decision() -> None:
    script = _script()
    preflight = script.index("run_preflight\n")
    preflight_gate = script.index("halt_stage torque_off_preflight")
    collector = script.index("run_collector\n", preflight_gate)
    collector_gate = script.index("halt_stage automatic_configuration_collection")
    support = script.index("validate_support\n", collector_gate)
    support_gate = script.index("halt_stage automatic_configuration_support")
    assert preflight < preflight_gate < collector < collector_gate < support < support_gate
    assert "open_duck_x5.gate4_validation" in script
    assert "open_duck_x5.configuration_support" in script
    assert '"policy_loaded": False' in script


def test_runner_signals_child_and_restores_governor_on_exit() -> None:
    script = _script()
    assert "trap cleanup EXIT" in script
    assert 'kill -TERM "${active_process_pid}"' in script
    assert "restore_governor" in script
    assert 'performance > "${policy}/scaling_governor"' in script
    assert 'cat "${policy}/scaling_governor" > "${output_dir}/governor-after.txt"' in script
