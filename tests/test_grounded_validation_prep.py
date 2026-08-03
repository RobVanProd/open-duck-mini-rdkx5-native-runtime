from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
RUNNER = ROOT / "setup/run_grounded_controller_stop_preflight.sh"
PREREGISTRATION = (
    ROOT
    / "artifacts/gates/grounded_validation"
    / "CONTROLLER_B_STOP_NO_SERVO_PREREGISTRATION_20260802.json"
)
X0_REVIEW = (
    ROOT
    / "artifacts/gates/phase_7_hardware/gate_5_policy"
    / "T247_X0_READINESS_CUED_PASS_REVIEWED_20260802.json"
)
X008_REVIEW = (
    ROOT
    / "artifacts/gates/phase_7_hardware/gate_5_policy"
    / "T247_X008_READINESS_CUED_PASS_REVIEWED_20260802.json"
)
HANDOFF = ROOT / "docs/GROUNDED_VALIDATION_HANDOFF.md"
LAUNCHER_REVIEW = (
    ROOT
    / "artifacts/gates/grounded_validation"
    / "CONTROLLER_B_STOP_NO_SERVO_LAUNCHER_REVIEW_20260802.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _script() -> str:
    return RUNNER.read_text(encoding="utf-8")


def test_controller_stop_preregistration_is_no_servo_and_not_run() -> None:
    value = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))

    assert value["status"] == "PREREGISTERED_NOT_RUN_CONTROLLER_B_STOP_NO_SERVO"
    assert value["frozen_run"]["ticks_maximum"] == 3000
    assert value["frozen_run"]["frequency_hz"] == 50.0
    assert value["frozen_run"]["single_probe_invocation"] is True
    assert value["frozen_run"]["automatic_follow_on"] is False
    assert value["acceptance"]["serial_access"] is False
    assert value["acceptance"]["servo_access"] is False
    assert value["acceptance"]["torque_enabled"] is False
    assert value["acceptance"]["policy_loaded"] is False
    assert value["acceptance"]["motion"] is False
    assert value["authority"] == {
        "preregistration_only": True,
        "controller_access": False,
        "robot_access": False,
        "serial_access": False,
        "servo_access": False,
        "torque": False,
        "policy": False,
        "motion": False,
        "suspended_cutoff_test": False,
        "grounded_replay": False,
    }


def test_controller_stop_preregistration_pins_both_reviewed_gate5_arms() -> None:
    value = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))

    assert value["earned_by"]["gate5_x0_review_sha256"] == _sha256(X0_REVIEW)
    assert value["earned_by"]["gate5_x008_review_sha256"] == _sha256(X008_REVIEW)
    assert json.loads(X0_REVIEW.read_text(encoding="utf-8"))["status"] == (
        "PASS_REVIEWED_T247_GATE5_X0"
    )
    assert json.loads(X008_REVIEW.read_text(encoding="utf-8"))["status"] == (
        "PASS_REVIEWED_T247_GATE5_X008"
    )


def test_controller_stop_runner_pins_frozen_inputs_and_known_controller() -> None:
    script = _script()

    assert _sha256(PREREGISTRATION) in script
    assert _sha256(X0_REVIEW) in script
    assert _sha256(X008_REVIEW) in script
    assert 'expected_source_commit="257c84fddd1ed9162498840cd00b4d90c33785a1"' in script
    assert 'expected_source_tree="ce6a77e08fe860500e3ed8f69cec06e7885af1da"' in script
    assert 'expected_schema_tree="55580397a2d01bd6f76417f57a92c4dddee7f642"' in script
    assert 'expected_pyproject_blob="c5599cd5bbe11f7884ff663307712edb7b7b4751"' in script
    assert 'expected_controller_mac="0C:35:26:2A:B8:0B"' in script
    assert 'expected_controller_uniq="0c:35:26:2a:b8:0b"' in script
    assert 'expected_controller_modalias="usb:v045Ep0B13d0515"' in script


def test_controller_stop_runner_has_one_controller_only_probe_invocation() -> None:
    script = _script()
    invocation = "-m open_duck_x5.controller_stop_probe"

    assert script.count(invocation) == 1
    assert "--controller xbox" in script
    assert '--ticks "$ticks"' in script
    assert '--frequency-hz "$frequency_hz"' in script
    assert "open_duck_x5.probe" not in script.replace(invocation, "")
    assert "open_duck_x5.runtime" not in script
    assert "--gate5-authorized" not in script
    assert "--gate5-moving-authorized" not in script
    assert "--enable-torque" not in script
    assert "--moving-gate-authorized" not in script
    assert "--policy" not in script
    assert "/dev/tty" not in script


def test_controller_stop_runner_requires_acknowledgements_and_refuses_reuse() -> None:
    script = _script()
    argument_cases = script.split("while [[ $# -gt 0 ]]", 1)[1].split("done", 1)[0]

    assert "--hardware-authorized)" in argument_cases
    assert "--suspended-or-benched)" in argument_cases
    assert "missing_controller_hardware_acknowledgements" in script
    assert "refuse_existing_output_dir" in script
    assert "tracked_source_worktree_dirty" in script


def test_controller_stop_runner_validates_no_robot_side_effects_and_no_follow_on() -> None:
    script = _script()

    for field in (
        '"serial_access_false"',
        '"servo_access_false"',
        '"torque_enabled_false"',
        '"policy_loaded_false"',
        '"motion_false"',
        '"automatic_follow_on": False',
        '"suspended_cutoff_test_authorized": False',
        '"grounded_motion_authorized": False',
    ):
        assert field in script


def test_controller_stop_launcher_review_pins_exact_nonmoving_launcher() -> None:
    value = json.loads(LAUNCHER_REVIEW.read_text(encoding="utf-8"))

    assert value["status"] == "PASS_OFFLINE_REVIEW_NOT_RUN"
    assert value["preregistration"]["sha256"] == _sha256(PREREGISTRATION)
    assert value["launcher"]["sha256"] == _sha256(RUNNER)
    assert value["launcher"]["probe_invocations"] == 1
    assert all(value["offline_checks"].values())
    assert value["result_scope"]["physical_probe_executed"] is False
    assert value["decision"] == {
        "controller_mapping_probe_ready_for_exact_authorization": True,
        "suspended_cutoff_test_ready": False,
        "grounded_x0_ready": False,
        "grounded_x008_ready": False,
        "automatic_promotion": False,
    }


def test_controller_stop_runner_parses_and_help_is_non_moving() -> None:
    subprocess.run(["bash", "-n", str(RUNNER)], check=True)
    completed = subprocess.run(
        ["bash", str(RUNNER), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Controller-only physical B-button mapping probe" in completed.stdout
    assert "does not open a serial device" in completed.stdout
    assert "This is not a grounded robot run" in completed.stdout


def test_handoff_blocks_grounded_launchers_until_sequential_safety_passes() -> None:
    text = HANDOFF.read_text(encoding="utf-8")

    assert "G1 | Physical Xbox B mapping" in text
    assert "G2 | Suspended, no-policy home-entry B cutoff" in text
    assert "G3 | Grounded x=0 only" in text
    assert "G4 | Grounded x=.08 only" in text
    assert "no launcher exists" in text
    assert "There is no automatic promotion between stages" in text
    assert "must not reuse the\n`--suspended-or-benched` assertion" in text
