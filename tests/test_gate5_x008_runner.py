from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
RUNNER = ROOT / "setup/run_t247_gate5_x008.sh"
PREREGISTRATION = (
    ROOT
    / "artifacts/gates/phase_7_hardware/gate_5_policy"
    / "T247_X008_READINESS_CUED_PREREGISTRATION_20260802.json"
)
X0_REVIEW = (
    ROOT
    / "artifacts/gates/phase_7_hardware/gate_5_policy"
    / "T247_X0_READINESS_CUED_PASS_REVIEWED_20260802.json"
)
READINESS_REVIEW = (
    ROOT
    / "artifacts/gates/phase_7_hardware/gate_5_policy"
    / "T247_STARTUP_READINESS_REVALIDATION_PASS_20260802.json"
)
LAUNCHER_REVIEW = (
    ROOT
    / "artifacts/gates/phase_7_hardware/gate_5_policy"
    / "T247_X008_READINESS_CUED_LAUNCHER_REVIEW_20260802.json"
)


def _script() -> str:
    return RUNNER.read_text(encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_x008_preregistration_is_single_arm_and_unexecuted() -> None:
    value = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))

    assert value["status"] == (
        "PREREGISTERED_NOT_RUN_T247_GATE5_X008_READINESS_CUED"
    )
    assert value["candidate_id"] == "T247_HOME_NEGATIVE_HALF_ADAPTER_FINAL"
    assert value["frozen_candidate"]["fixed_command_x_m_s"] == 0.08
    assert value["frozen_candidate"]["active_ticks"] == 850
    assert value["frozen_runtime"]["startup_readiness_attempts"] == 1
    assert value["frozen_runtime"]["startup_readiness_phase"] == [0.0, 0.0]
    assert value["launcher_contract"]["x008_only"] is True
    assert value["launcher_contract"]["fixed_command_is_not_configurable"] is True
    assert value["launcher_contract"]["reviewed_x0_receipt_required"] is True
    assert value["launcher_contract"]["no_second_command_path"] is True
    assert value["authority"] == {
        "preregistration_only": True,
        "robot_access": False,
        "torque": False,
        "motion": False,
        "gate5_run": False,
        "x008": False,
        "grounded_replay": False,
    }


def test_x008_preregistration_pins_reviewed_x0_receipt() -> None:
    value = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    receipt = json.loads(X0_REVIEW.read_text(encoding="utf-8"))

    assert value["earned_by"]["x0_review_sha256"] == _sha256(X0_REVIEW)
    assert receipt["status"] == "PASS_REVIEWED_T247_GATE5_X0"
    assert receipt["decision"]["x008_preregistration_earned"] is True
    assert receipt["decision"]["x008_run_authorized"] is False
    assert receipt["operator_review"]["result"] == "PASS"
    assert receipt["safety_exit"]["all_14_torque_enable_registers_zero"] is True


def test_x008_runner_pins_preregistration_receipts_and_runtime() -> None:
    script = _script()

    assert _sha256(PREREGISTRATION) in script
    assert _sha256(X0_REVIEW) in script
    assert _sha256(READINESS_REVIEW) in script
    assert 'readonly expected_source_tree="2aba58167a82b47bdd6942da25d4913c098cbfba"' in script
    assert 'readonly expected_schema_tree="55580397a2d01bd6f76417f57a92c4dddee7f642"' in script
    assert 'readonly device="/dev/ttyS1"' in script
    assert 'readonly active_ticks="850"' in script
    assert 'readonly maximum_total_ticks="3850"' in script
    assert 'readonly home_seconds="5"' in script
    assert "x008_preregistration_or_x0_review_mismatch" in script


def test_x008_runner_has_only_one_hardcoded_x008_invocation() -> None:
    script = _script()
    argument_cases = script.split("while [[ $# -gt 0 ]]", 1)[1].split("done", 1)[0]

    assert "--fixed-command-x)" not in argument_cases
    assert "--x0-review)" not in argument_cases
    assert "--fixed-command-x 0.08" in script
    assert script.count("-m open_duck_x5.runtime") == 1
    assert 'summary.get("command", {}).get("fixed_x") == 0.08' in script
    assert '"fixed_command_x_m_s": 0.08' in script
    assert '"second_command_path": False' in script


def test_x008_runner_requires_exact_motion_acknowledgements() -> None:
    script = _script()
    argument_cases = script.split("while [[ $# -gt 0 ]]", 1)[1].split("done", 1)[0]

    assert "--hardware-authorized)" in argument_cases
    assert "--suspended-or-benched)" in argument_cases
    assert "--gate5-moving-authorized)" in argument_cases
    assert "missing_gate5_hardware_acknowledgements" in script
    assert "--gate5-authorized --hardware-authorized --suspended-or-benched" in script


def test_x008_runner_checks_inputs_before_governor_or_serial() -> None:
    script = _script()

    x0_hash = script.index(
        'require_hash "$x0_review" "$expected_x0_review_sha256" "x0_review"'
    )
    last_asset_hash = script.index(
        'require_hash "$command_manifest" "$expected_command_manifest_sha256"'
    )
    device_check = script.index('if [[ ! -c "$device" ]]')
    governor_change = script.index(
        'performance > "$governor_policy/scaling_governor"'
    )
    assert x0_hash < last_asset_hash < device_check < governor_change


def test_x008_runner_requires_readiness_and_all_summary_gates() -> None:
    script = _script()

    assert 'event_counts.get("startup_readiness") == 1' in script
    assert 'readiness.get("status") == "PASS"' in script
    assert 'readiness.get("policy_committed_ticks") == 0' in script
    assert 'readiness.get("phase") == [0.0, 0.0]' in script
    assert 'and all(value is True for value in gates.values())' in script
    assert 'summary.get("active_policy_ticks") == 850' in script
    assert 'summary.get("safety", {}).get("torque_off_confirmed") is True' in script
    assert '"operator_observation_required": True' in script
    assert 'at_most(tick_stats.get("p99"), 21.0)' in script
    assert 'below(bus_stats.get("max"), 5.0)' in script


def test_x008_runner_pins_controller_and_restores_on_exit() -> None:
    script = _script()

    assert "0C:35:26:2A:B8:0B" in script
    assert "0c:35:26:2a:b8:0b" in script
    assert "usb:v045Ep0B13d0515" in script
    assert 'require_controller_state "$output_dir/controller-before.txt"' in script
    assert 'require_controller_state "$output_dir/controller-after.txt"' in script
    assert "trap cleanup EXIT" in script
    assert 'kill -TERM "$active_runtime_pid"' in script
    assert "restore_governor" in script
    assert '"serial_released": serial == "true"' in script


def test_x008_runner_is_valid_bash_and_help_is_non_mutating() -> None:
    subprocess.run(["bash", "-n", str(RUNNER)], cwd=ROOT, check=True)
    result = subprocess.run(
        ["bash", str(RUNNER), "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Runs exactly the frozen suspended T247 x=.08 arm" in result.stdout


def test_x008_launcher_review_pins_exact_runner_receipts_and_command() -> None:
    value = json.loads(LAUNCHER_REVIEW.read_text(encoding="utf-8"))

    assert value["status"] == (
        "READY_FOR_FRESH_EXPLICIT_SUSPENDED_T247_GATE5_X008_AUTHORIZATION"
    )
    assert value["frozen_source"]["launcher_sha256"] == _sha256(RUNNER)
    assert value["frozen_source"]["preregistration_sha256"] == _sha256(
        PREREGISTRATION
    )
    assert value["frozen_source"]["x0_review_sha256"] == _sha256(X0_REVIEW)
    assert value["frozen_source"]["startup_readiness_review_sha256"] == _sha256(
        READINESS_REVIEW
    )
    argv = value["frozen_argv"]
    assert argv.count("setup/run_t247_gate5_x008.sh") == 1
    assert "--fixed-command-x" not in argv
    assert argv[-3:] == [
        "--hardware-authorized",
        "--suspended-or-benched",
        "--gate5-moving-authorized",
    ]
    assert value["run_scope"]["fixed_command_x_m_s"] == 0.08
    assert value["run_scope"]["active_ticks"] == 850
    assert value["run_scope"]["grounded_replay"] is False
    assert value["operator_handshake"]["agent_cue"] == "GO — press A once now."
    assert value["authority"]["current_motion"] is False
