from __future__ import annotations

from pathlib import Path


def _script() -> str:
    return (Path(__file__).parents[1] / "setup" / "run_gate4_sine_tracking.sh").read_text(
        encoding="utf-8"
    )


def test_gate4_runner_freezes_scope_and_population() -> None:
    script = _script()
    assert "c5f27598b68fa7d69d81d0675f50a06435ecdaf8" in script
    assert "5ee4aa30fb11e411ec7cea797c70ebf5aa53d1278e8c873544825253b193ffc8" in script
    assert 'readonly device="/dev/ttyS1"' in script
    assert 'readonly ticks="10000"' in script
    assert 'readonly home_seconds="5"' in script
    assert 'readonly sine_joint="left_hip_yaw"' in script
    assert 'readonly amplitude_rad="0.03"' in script
    assert "--watchdog-failures 2" in script
    assert "--rt-cpu 7" in script
    assert "--rt-priority 80" in script
    assert "run_probe_stage preflight 0.25 0 0" in script
    assert 'run_probe_stage sine_0_25 0.25 "${amplitude_rad}" 1' in script
    assert 'run_probe_stage sine_0_5 0.5 "${amplitude_rad}" 1' in script
    assert "--enable-torque --moving-gate-authorized" in script


def test_gate4_runner_requires_all_hardware_acknowledgements() -> None:
    script = _script()
    argument_cases = script.split("while [[ $# -gt 0 ]]", 1)[1].split("done", 1)[0]
    assert "--hardware-authorized)" in argument_cases
    assert "--suspended-or-benched)" in argument_cases
    assert "--moving-gate-authorized)" in argument_cases
    assert "missing_gate4_hardware_acknowledgements" in script


def test_gate4_runner_exposes_no_frozen_scope_override() -> None:
    argument_cases = _script().split("while [[ $# -gt 0 ]]", 1)[1].split("done", 1)[0]
    for blocked in (
        "--device)",
        "--ticks)",
        "--home-seconds)",
        "--sine-joint)",
        "--sine-hz)",
        "--amplitude-rad)",
        "--baudrate)",
        "--timeout-ms)",
        "--policy)",
    ):
        assert blocked not in argument_cases
    assert "--source-archive)" in argument_cases
    assert "--config)" in argument_cases
    assert "--output-dir)" in argument_cases


def test_gate4_runner_is_sequential_and_fail_closed() -> None:
    script = _script()
    preflight = script.index("run_probe_stage preflight 0.25 0 0")
    preflight_gate = script.index("halt_stage torque_off_preflight")
    slow = script.index('run_probe_stage sine_0_25 0.25 "${amplitude_rad}" 1')
    slow_gate = script.index("halt_stage sine_0_25\n", slow)
    fast = script.index('run_probe_stage sine_0_5 0.5 "${amplitude_rad}" 1')
    assert preflight < preflight_gate < slow < slow_gate < fast
    assert "open_duck_x5.gate4_validation" in script


def test_gate4_runner_restores_governor_and_signals_probe() -> None:
    script = _script()
    assert "trap cleanup EXIT" in script
    assert "restore_governor" in script
    assert 'kill -TERM "${active_probe_pid}"' in script
    assert 'performance > "${policy}/scaling_governor"' in script
    assert 'cat "${policy}/scaling_governor" > "${output_dir}/governor-after.txt"' in script
