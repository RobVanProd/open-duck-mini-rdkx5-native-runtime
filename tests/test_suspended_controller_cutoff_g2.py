from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
RUNNER = ROOT / "setup/run_suspended_controller_b_cutoff_g2.sh"
PREREGISTRATION = (
    ROOT
    / "artifacts/gates/grounded_validation"
    / "SUSPENDED_CONTROLLER_B_CUTOFF_G2_PREREGISTRATION_20260802.json"
)
G1_REVIEW = (
    ROOT
    / "artifacts/gates/grounded_validation"
    / "CONTROLLER_B_STOP_OPERATOR_RETURN_PASS_REVIEWED_20260802.json"
)
LAUNCHER_REVIEW = (
    ROOT
    / "artifacts/gates/grounded_validation"
    / "SUSPENDED_CONTROLLER_B_CUTOFF_G2_LAUNCHER_REVIEW_20260802.json"
)
ATTEMPT1 = (
    ROOT
    / "artifacts/gates/grounded_validation"
    / "SUSPENDED_CONTROLLER_B_CUTOFF_G2_ATTEMPT1_CONTROLLER_SLEEP_20260802.json"
)
REPLACEMENT_PREREGISTRATION = (
    ROOT
    / "artifacts/gates/grounded_validation"
    / "SUSPENDED_CONTROLLER_B_CUTOFF_G2_REPLACEMENT_PREREGISTRATION_20260802.json"
)
REPLACEMENT_RUNNER = (
    ROOT / "setup/run_suspended_controller_b_cutoff_g2_replacement.sh"
)
REPLACEMENT_LAUNCHER_REVIEW = (
    ROOT
    / "artifacts/gates/grounded_validation"
    / "SUSPENDED_CONTROLLER_B_CUTOFF_G2_REPLACEMENT_LAUNCHER_REVIEW_20260802.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _script() -> str:
    return RUNNER.read_text(encoding="utf-8")


def test_g2_preregistration_is_suspended_no_policy_and_not_run() -> None:
    value = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))

    assert value["status"] == (
        "PREREGISTERED_NOT_RUN_SUSPENDED_CONTROLLER_B_CUTOFF_G2"
    )
    assert value["earned_by"]["review_sha256"] == _sha256(G1_REVIEW)
    assert value["scope"]["robot_support"] == "stand/suspended-or-benched"
    assert value["scope"]["policy_loaded"] is False
    assert value["scope"]["commanded_velocity_m_s"] is None
    assert value["scope"]["grounded_motion"] is False
    assert value["scope"]["automatic_follow_on"] is False
    assert [stage["stage"] for stage in value["sequence"]] == [
        "torque_off_preflight",
        "home_entry_and_hold",
        "independent_torque_off_readback",
    ]
    assert value["sequence"][0]["ticks"] == 10_000
    assert value["sequence"][1]["home_entry_seconds"] == 5
    assert value["sequence"][1]["maximum_home_hold_ticks"] == 3_000
    assert value["sequence"][1]["policy_loaded"] is False
    assert value["sequence"][2]["read_order"][-2:] == [14, 13]
    assert value["decision"]["g2_status"] == "NOT_RUN"
    assert value["decision"]["grounded_motion_authorized"] is False


def test_g2_cutoff_threshold_and_operator_protocol_are_frozen() -> None:
    value = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    cutoff = value["acceptance"]["cutoff"]

    assert cutoff["halt_reason_exact"] == (
        "physical controller emergency stop requested"
    )
    assert cutoff["control_exchanges_after_detection"] == 0
    assert cutoff["event_to_torque_disable_complete_at_most_ms"] == 20.0
    assert cutoff["derivation"] == "one frozen 50 Hz control period"
    assert cutoff["probe_exit_status"] == 2
    assert value["operator_protocol"] == {
        "a_button_presses": 0,
        "button": "B",
        "cue": "GO — press B exactly once now; do not press A",
        "press_before_home_ready_cue": "PROHIBITED",
        "presses": 1,
    }
    assert value["stop_rules"]["automatic_retry"] is False
    assert value["stop_rules"]["automatic_grounded_follow_on"] is False


def test_g2_runner_pins_source_preregistration_config_and_g1() -> None:
    script = _script()

    assert _sha256(PREREGISTRATION) in script
    assert _sha256(G1_REVIEW) in script
    assert 'expected_source_commit="479cb4dce37ca85d6f0a4da4bf8322e7e14d4cb4"' in script
    assert 'expected_source_tree="6bb064e1d15c27fb6af7301cf2fe9a6b4d7fb6d4"' in script
    assert 'expected_schema_tree="55580397a2d01bd6f76417f57a92c4dddee7f642"' in script
    assert 'expected_pyproject_blob="4d2b05b958aea152a16c88e094ff25fd78d31b55"' in script
    assert (
        'expected_config_sha256="131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b"'
        in script
    )
    assert 'expected_controller_uniq="0c:35:26:2a:b8:0b"' in script


def test_g2_runner_has_exact_two_probe_stages_and_one_independent_readback() -> None:
    script = _script()

    assert script.count("-m open_duck_x5.probe") == 2
    assert script.count("-m open_duck_x5.torque_off_readback") == 1
    assert "-m open_duck_x5.runtime" not in script
    assert "--policy" not in script
    assert '--ticks "$preflight_ticks"' in script
    assert '--ticks "$cutoff_ticks"' in script
    assert '--enable-torque --moving-gate-authorized' in script
    assert '--amplitude-rad 0' in script
    assert '--emergency-stop-cutoff-audit-output' in script
    assert '--home-ready-output' in script
    assert '"cutoff_limit_ms") == 20.0' in script
    assert '"all_14_torque_enable_registers_zero"' in script
    assert '"grounded_motion_authorized": False' in script
    assert "--grounded" not in script


def test_g2_runner_requires_all_acknowledgements_and_has_no_automatic_follow_on() -> None:
    script = _script()
    argument_cases = script.split("while [[ $# -gt 0 ]]", 1)[1].split("done", 1)[0]

    assert "--hardware-authorized)" in argument_cases
    assert "--suspended-or-benched)" in argument_cases
    assert "--moving-gate-authorized)" in argument_cases
    assert "--controller-cutoff-authorized)" in argument_cases
    assert "missing_g2_hardware_acknowledgements" in script
    assert "refuse_existing_output_dir" in script
    assert '"automatic_follow_on": False' in script
    assert "automatic retry" not in script.lower()


def test_g2_runner_parses_and_help_states_exact_limits() -> None:
    subprocess.run(["bash", "-n", str(RUNNER)], check=True)
    completed = subprocess.run(
        ["bash", str(RUNNER), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "10,000-tick" in completed.stdout
    assert "five seconds" in completed.stdout
    assert "HOME_HOLD_READY" in completed.stdout
    assert "all-14 register-40 torque-off readback" in completed.stdout
    assert "no grounded or policy" in completed.stdout.lower()


def test_g2_launcher_review_pins_exact_not_run_scope() -> None:
    value = json.loads(LAUNCHER_REVIEW.read_text(encoding="utf-8"))

    assert value["status"] == "PASS_OFFLINE_REVIEW_NOT_RUN_G2"
    assert value["preregistration"]["sha256"] == _sha256(PREREGISTRATION)
    assert value["launcher"]["sha256"] == _sha256(RUNNER)
    assert value["launcher"]["timing_probe_invocations"] == 2
    assert value["launcher"]["independent_torque_readback_invocations"] == 1
    assert value["launcher"]["policy_runtime_invocations"] == 0
    assert all(value["offline_checks"].values())
    assert value["result_scope"] == {
        "grounded_motion": False,
        "motion_executed": False,
        "physical_g2_executed": False,
        "policy_loaded": False,
        "torque_enabled": False,
    }
    assert value["decision"]["g2_ready_for_fresh_exact_authorization"] is True
    assert value["decision"]["g2_authorized"] is False
    assert value["decision"]["grounded_motion_authorized"] is False


def test_g2_attempt1_closed_before_torque_for_real_controller_sleep() -> None:
    value = json.loads(ATTEMPT1.read_text(encoding="utf-8"))

    assert value["status"] == (
        "HALTED_BEFORE_TORQUE_ENABLE_CONTROLLER_TRANSPORT_LOSS"
    )
    assert value["preflight"]["ticks_completed"] == 215
    assert value["preflight"]["transactions_failed"] == 0
    assert value["attribution"]["classification"] == (
        "REAL_JOYDEV_TRANSPORT_INTERRUPTION"
    )
    assert value["attribution"]["current_js0_recreated_after_halt"] is True
    assert value["attribution"]["timestamp_bookkeeping_defect"] is False
    assert value["safety_exit"]["moving_stage_entered"] is False
    assert value["safety_exit"]["all_14_torque_enable_registers_zero"] is True
    assert value["decision"]["retry_under_original_preregistration"] is False
    assert value["decision"]["replacement_run_authorized"] is False


def test_g2_replacement_changes_only_operator_keep_awake_protocol() -> None:
    value = json.loads(REPLACEMENT_PREREGISTRATION.read_text(encoding="utf-8"))

    assert value["status"] == (
        "PREREGISTERED_NOT_RUN_SUSPENDED_CONTROLLER_B_CUTOFF_G2_REPLACEMENT"
    )
    assert value["earned_by"]["attempt1_sha256"] == _sha256(ATTEMPT1)
    assert value["frozen_source"]["runtime_change_from_attempt1"] is False
    assert value["frozen_source"]["probe_change_from_attempt1"] is False
    assert value["frozen_source"]["servo_bus_change_from_attempt1"] is False
    protocol = value["operator_keep_awake_protocol"]
    assert protocol["preflight_cue_interval_s"] == 25
    assert protocol["a_button_presses"] == 0
    assert protocol["b_button_before_home_ready"] == "PROHIBITED"
    assert protocol["axis_input_can_command_robot"] is False
    assert value["unchanged_sequence"]["preflight_ticks"] == 10_000
    assert value["unchanged_sequence"]["policy_loaded"] is False
    assert value["unchanged_sequence"][
        "b_event_to_torque_disable_complete_at_most_ms"
    ] == 20.0
    assert value["decision"]["g2"] == "NOT_RUN"
    assert value["decision"]["grounded_motion_authorized"] is False


def test_g2_replacement_wrapper_pins_evidence_and_only_wraps_original() -> None:
    script = REPLACEMENT_RUNNER.read_text(encoding="utf-8")

    assert _sha256(ATTEMPT1) in script
    assert _sha256(REPLACEMENT_PREREGISTRATION) in script
    assert _sha256(RUNNER) in script
    assert 'keep_awake_interval_s="25"' in script
    assert "operator_action=KEEP_AWAKE" in script
    assert script.count("run_suspended_controller_b_cutoff_g2.sh") == 2
    assert "open_duck_x5.probe" not in script
    assert "open_duck_x5.runtime" not in script
    assert "--policy" not in script
    assert "--grounded" not in script
    assert '"automatic_retry": False' in script
    assert '"automatic_follow_on": False' in script


def test_g2_replacement_wrapper_parses_and_help_explains_axis_safety() -> None:
    subprocess.run(["bash", "-n", str(REPLACEMENT_RUNNER)], check=True)
    completed = subprocess.run(
        ["bash", str(REPLACEMENT_RUNNER), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "keep-awake cue every 25 seconds" in completed.stdout
    assert "gently move either stick once" in completed.stdout
    assert "axes cannot command the robot" in completed.stdout
    assert "no policy" in completed.stdout
    assert "no grounded path" in completed.stdout


def test_g2_replacement_launcher_review_is_exact_and_not_run() -> None:
    value = json.loads(REPLACEMENT_LAUNCHER_REVIEW.read_text(encoding="utf-8"))

    assert value["status"] == "PASS_OFFLINE_REVIEW_NOT_RUN_G2_REPLACEMENT"
    assert value["attempt1"]["sha256"] == _sha256(ATTEMPT1)
    assert value["preregistration"]["sha256"] == _sha256(
        REPLACEMENT_PREREGISTRATION
    )
    assert value["launcher"]["sha256"] == _sha256(REPLACEMENT_RUNNER)
    assert value["launcher"]["underlying_launcher_sha256"] == _sha256(RUNNER)
    assert all(value["offline_checks"].values())
    assert value["result_scope"]["replacement_executed"] is False
    assert value["result_scope"]["torque_enabled"] is False
    assert value["decision"]["replacement_ready_for_fresh_exact_authorization"] is True
    assert value["decision"]["replacement_authorized"] is False
    assert value["decision"]["g2"] == "NOT_RUN"
