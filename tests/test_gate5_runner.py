from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _script() -> str:
    return (
        ROOT / "setup" / "run_t247_gate5_single_arm.sh"
    ).read_text(encoding="utf-8")


def test_gate5_runner_freezes_candidate_bus_and_duration() -> None:
    script = _script()
    assert 'readonly device="/dev/ttyS1"' in script
    assert 'readonly active_ticks="850"' in script
    assert 'readonly maximum_total_ticks="3850"' in script
    assert 'readonly home_seconds="5"' in script
    assert 'readonly controller="xbox"' in script
    assert "--policy-contract t247-command-routed-115" in script
    assert '--max-active-ticks "${active_ticks}"' in script
    assert '--max-ticks "${maximum_total_ticks}"' in script
    assert "--watchdog-failures 3" in script
    assert "--rt-cpu 7" in script
    assert "--rt-priority 80" in script


def test_gate5_runner_pins_all_external_inputs() -> None:
    script = _script()
    for value in (
        "131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b",
        "e7518b0df8614c1d399c789fd26aa9888043ebacfccc98ef75a5010a4b8c34be",
        "dadfb446ea7c720f274a15bc65e9171c2e74d715ccfaf58adbb408b6c1365a54",
        "0f3aebfd9946a6271fdb14adec3d68d556648f270984639d372c973a7d7dc576",
        "5621f7c6782a8346bf25f05ce7f0bc002acbe8e98872cf658f0d44773511b4cd",
        "3b1f406fba5147a3f38ec59fc7f9c8d42dd27fa7eeb54344f447c060eb95b284",
        "a58db8ffc505d2bb64cba7f5618d0e2c65904fc9f9ac37b560a1231e090f5f4f",
        "8102d9cd139584816d807ca635bcca6d37fa6b3c455848e00395b6d565968212",
    ):
        assert value in script
    assert 'value.get("start_paused") is not True' in script
    assert "frozen_source_tree_mismatch" in script


def test_gate5_runner_requires_exact_gate_acknowledgements() -> None:
    script = _script()
    argument_cases = script.split("while [[ $# -gt 0 ]]", 1)[1].split("done", 1)[0]
    assert "--hardware-authorized)" in argument_cases
    assert "--suspended-or-benched)" in argument_cases
    assert "--gate5-moving-authorized)" in argument_cases
    assert "missing_gate5_hardware_acknowledgements" in script
    assert "--gate5-authorized" in script


def test_gate5_runner_has_no_scope_override_or_automatic_second_arm() -> None:
    script = _script()
    argument_cases = script.split("while [[ $# -gt 0 ]]", 1)[1].split("done", 1)[0]
    for blocked in (
        "--device)",
        "--baudrate)",
        "--timeout-ms)",
        "--active-ticks)",
        "--max-ticks)",
        "--home-seconds)",
        "--watchdog-failures)",
        "--controller)",
        "--rt-cpu)",
        "--rt-priority)",
    ):
        assert blocked not in argument_cases
    assert script.count("python3 -m open_duck_x5.runtime") == 1
    assert '"automatic_x008_advance": False' in script


def test_gate5_x008_requires_hash_verified_reviewed_x0() -> None:
    script = _script()
    assert 'if [[ "${fixed_command_x}" == "0.08" ]]' in script
    assert "x008_requires_reviewed_x0_receipt" in script
    assert "PASS_REVIEWED_T247_GATE5_X0" in script
    assert "x0_review_acceptance_not_green" in script
    assert 'require_hash "${x0_review}" "${x0_review_sha256}" "x0_review"' in script


def test_gate5_runner_restores_governor_and_signals_runtime() -> None:
    script = _script()
    assert "trap cleanup EXIT" in script
    assert "restore_governor" in script
    assert 'kill -TERM "${active_runtime_pid}"' in script
    assert 'performance > "${governor_policy}/scaling_governor"' in script
    assert (
        'cat "${governor_policy}/scaling_governor" '
        '> "${output_dir}/governor-after.txt"'
    ) in script
    assert "open_duck_x5.control_summary" in script
    assert "COMPLETE_REVIEW_REQUIRED" in script


def test_gate5_runner_checks_hashes_before_device_or_governor_action() -> None:
    script = _script()
    hash_check = script.index('require_hash "${command_manifest}"')
    device_check = script.index('if [[ ! -c "${device}" ]]')
    governor_change = script.index(
        'performance > "${governor_policy}/scaling_governor"'
    )
    assert hash_check < device_check < governor_change


def test_gate5_command_packet_pins_launcher_and_remains_not_run() -> None:
    runner = ROOT / "setup" / "run_t247_gate5_single_arm.sh"
    packet = json.loads(
        (
            ROOT
            / "artifacts/gates/phase_7_hardware/gate_5_policy"
            / "T247_COMMAND_PACKET_20260801.json"
        ).read_text(encoding="utf-8")
    )
    readiness = json.loads(
        (
            ROOT
            / "artifacts/gates/phase_7_hardware/gate_5_policy"
            / "T247_READINESS_20260801.json"
        ).read_text(encoding="utf-8")
    )

    assert packet["status"] == "SEALED_NOT_RUN_T247_GATE5_X0_COMMAND_PACKET"
    assert packet["source"]["launcher_sha256"] == hashlib.sha256(
        runner.read_bytes()
    ).hexdigest()
    assert packet["source"]["runnable_commit"] == (
        "b864cc2d234eb91d78ed1b46a8717b70e14bbc48"
    )
    assert packet["x0_launcher_argv"].count("--fixed-command-x") == 1
    assert packet["x0_launcher_argv"][-1] == "--gate5-moving-authorized"
    assert packet["x008_packet_status"] == (
        "BLOCKED_UNTIL_X0_REVIEW_AND_SEPARATE_AUTHORIZATION"
    )
    assert readiness["status"] == (
        "READY_FOR_EXPLICIT_SUSPENDED_T247_GATE5_X0_AUTHORIZATION"
    )
    assert readiness["gate5_executed"] is False
    assert readiness["robot_clearance"] is False
