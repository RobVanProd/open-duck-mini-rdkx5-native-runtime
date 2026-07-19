from __future__ import annotations

from pathlib import Path


def _script() -> str:
    return (
        Path(__file__).parents[1] / "setup" / "run_cpu_governor_ab_torque_off.sh"
    ).read_text(encoding="utf-8")


def test_cpu_governor_runner_is_frozen_and_torque_off_only() -> None:
    script = _script()
    assert 'readonly device="/dev/ttyS1"' in script
    assert 'readonly ticks="10000"' in script
    assert "8c73aae2110f10a294e1dcf333c41bfc9d2f3a88" in script
    assert "a90070d00e8f0eca704005aa241c36e7ab4aa782ca7f8af41253d3d4be41de77" in script
    assert "--hardware-authorized" in script
    assert "--suspended-or-benched" in script
    assert "--instrument-transactions" in script
    assert "--enable-torque" not in script
    assert "--moving-gate-authorized" not in script
    assert "--config" not in script
    assert "--policy" not in script
    assert "trap cleanup EXIT" in script
    assert "restore_governor" in script
    assert "performance > \"${policy}/scaling_governor\"" in script


def test_cpu_governor_runner_refuses_variable_device_ticks_and_source() -> None:
    argument_cases = _script().split("while [[ $# -gt 0 ]]", 1)[1].split("done", 1)[0]
    assert "--device)" not in argument_cases
    assert "--ticks)" not in argument_cases
    assert "--expected-source" not in argument_cases
    assert "--source-archive)" in argument_cases
    assert "--output-dir)" in argument_cases
