from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
ATTEMPT = (
    ROOT
    / "artifacts/gates/phase_7_hardware/gate_5_policy"
    / "T247_X0_ATTEMPT1_HALTED_20260802.json"
)
PREREGISTRATION = (
    ROOT
    / "artifacts/gates/phase_7_hardware/gate_5_policy"
    / "T247_CONTROLLER_ISOLATION_REPAIR_PREREGISTRATION_20260802.json"
)
CONTROLLER_PASS = (
    ROOT
    / "artifacts/gates/phase_7_hardware/gate_5_policy"
    / "T247_CONTROLLER_DIRECT_10000_PASS_20260802.json"
)
TORQUE_OFF_PREREGISTRATION = (
    ROOT
    / "artifacts/gates/phase_7_hardware/gate_5_policy"
    / "T247_CONTROLLER_PRESENT_TORQUE_OFF_PREREGISTRATION_20260802.json"
)
TORQUE_OFF_RUNNER = ROOT / "setup/run_gate5_controller_torque_off_preflight.sh"


def test_attempt1_is_a_pre_policy_halt_with_confirmed_cutoff() -> None:
    value = json.loads(ATTEMPT.read_text(encoding="utf-8"))

    assert value["status"] == "HALT_PRE_POLICY_SOFTWARE_ISOLATION_DEFECT"
    assert value["policy_active_ticks"] == 0
    assert value["policy_behavior_observed"] is False
    assert value["gate5_passed"] is False
    assert value["x008_earned"] is False
    assert value["robot_clearance"] is False
    assert value["halt"]["group_round_trip_ms"] > 90.0
    assert value["halt"]["configured_transaction_timeout_ms"] == 4.0
    assert value["halt"]["per_servo_status"] == "all_reported_ok"
    assert value["safety_exit"]["torque_off_confirmed"] is True
    assert value["safety_exit"]["serial_device_released"] is True
    assert value["safety_exit"]["governor_after"] == "schedutil"


def test_controller_isolation_repair_cannot_advance_without_10k_torque_off() -> None:
    value = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))

    assert value["status"] == "PREREGISTERED_NOT_RUN"
    assert value["policy_weights_unchanged"] is True
    assert value["policy_observation_action_contract_unchanged"] is True
    assert [step["name"] for step in value["ordered_validation"]] == [
        "offline_contract",
        "controller_only",
        "controller_present_torque_off_timing",
    ]
    timing = value["ordered_validation"][2]
    assert timing["ticks"] == 10_000
    assert timing["hardware_scope"].startswith("suspended/benched")
    assert "No motion retry" in value["stop_rule"]
    assert "does not authorize" in value["advance_rule"]


def test_controller_direct_validation_pins_identity_and_no_servo_scope() -> None:
    value = json.loads(CONTROLLER_PASS.read_text(encoding="utf-8"))

    assert value["status"] == "PASS_CONTROLLER_ONLY"
    assert value["hardware_scope"].startswith("controller only")
    assert value["controller"]["bluetooth_identity"] == "0C:35:26:2A:B8:0B"
    assert value["controller"]["sysfs_uniq"] == "0c:35:26:2a:b8:0b"
    assert value["controller"]["mapping_verified"] == {
        "left_x_axis": 0,
        "left_y_axis": 1,
        "right_x_axis": 2,
        "a_button": 0,
        "y_button": 3,
        "left_bumper": 4,
    }
    assert value["result"]["ticks_completed"] == 10_000
    assert value["result"]["a_edges"] == 1
    assert value["result"]["disconnect_tick"] is None
    assert value["result"]["last_error_errno"] is None
    assert value["result"]["device_inode_unchanged"] is True
    assert value["identity_attribution"]["rejected_identity"] == (
        "0C:35:26:3E:55:F6"
    )


def test_controller_present_runner_has_no_torque_or_motion_path() -> None:
    preregistration = json.loads(
        TORQUE_OFF_PREREGISTRATION.read_text(encoding="utf-8")
    )
    runner = TORQUE_OFF_RUNNER.read_text(encoding="utf-8")

    assert preregistration["status"] == "PREREGISTERED_NOT_RUN"
    assert preregistration["scope"]["ticks"] == 10_000
    assert preregistration["scope"]["torque_enable_requested"] is False
    assert preregistration["scope"]["motion"] is False
    assert preregistration["requirements"]["late_accepted_response_markers"] == 0
    assert 'readonly expected_controller_uniq="0c:35:26:2a:b8:0b"' in runner
    assert 'readonly ticks="10000"' in runner
    assert "--controller xbox" in runner
    assert "--amplitude-rad 0" in runner
    assert "--hardware-authorized --suspended-or-benched" in runner
    assert "--enable-torque" not in runner
    assert "--moving-gate-authorized" not in runner
