from __future__ import annotations

from pathlib import Path


def _script() -> str:
    return (
        Path(__file__).parents[1] / "setup" / "run_gate2_home_hold.sh"
    ).read_text(encoding="utf-8")


def test_gate2_runner_freezes_source_config_bus_and_motion_population() -> None:
    script = _script()
    assert "a5b53442012899f89c899f5c2f8f1a110c4448f2" in script
    assert "730d53480de5cf3c64381c75984289994d4edb798e2b09aec31b1f8df7ff67f5" in script
    assert "131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b" in script
    assert 'readonly device="/dev/ttyS1"' in script
    assert 'readonly ticks="10000"' in script
    assert 'readonly home_seconds="5"' in script
    assert "--amplitude-rad 0" in script
    assert "--watchdog-failures 2" in script
    assert "--rt-cpu 7" in script
    assert "--rt-priority 80" in script
    assert "--enable-torque --moving-gate-authorized" in script
    assert "run_probe_stage preflight 0" in script
    assert "run_probe_stage home_hold 1" in script


def test_gate2_runner_requires_all_three_hardware_acknowledgements() -> None:
    script = _script()
    argument_cases = script.split("while [[ $# -gt 0 ]]", 1)[1].split("done", 1)[0]
    assert "--hardware-authorized)" in argument_cases
    assert "--suspended-or-benched)" in argument_cases
    assert "--moving-gate-authorized)" in argument_cases
    assert "missing_gate2_hardware_acknowledgements" in script


def test_gate2_runner_exposes_no_frozen_runtime_override() -> None:
    argument_cases = _script().split("while [[ $# -gt 0 ]]", 1)[1].split("done", 1)[0]
    assert "--device)" not in argument_cases
    assert "--ticks)" not in argument_cases
    assert "--home-seconds)" not in argument_cases
    assert "--baudrate)" not in argument_cases
    assert "--timeout-ms)" not in argument_cases
    assert "--expected-source)" not in argument_cases
    assert "--policy)" not in argument_cases
    assert "--source-archive)" in argument_cases
    assert "--config)" in argument_cases
    assert "--output-dir)" in argument_cases


def test_gate2_runner_preflight_must_pass_before_torque_enable() -> None:
    script = _script()
    preflight_call = script.index("run_probe_stage preflight 0")
    preflight_gate = script.index('if [[ "${preflight_probe_status}" -ne 0')
    home_call = script.index("run_probe_stage home_hold 1")
    assert preflight_call < preflight_gate < home_call
    assert "open_duck_x5.gate2_validation" in script
    assert 'stage_name="preflight"' in script
    assert 'stage_name="home_hold"' in script


def test_gate2_runner_restores_governor_and_signals_active_probe() -> None:
    script = _script()
    assert "trap cleanup EXIT" in script
    assert "restore_governor" in script
    assert 'kill -TERM "${active_probe_pid}"' in script
    assert 'performance > "${policy}/scaling_governor"' in script
    assert 'cat "${policy}/scaling_governor" > "${output_dir}/governor-after.txt"' in script
