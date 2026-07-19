from __future__ import annotations

import json
from pathlib import Path

import pytest

from open_duck_x5.configuration_support import (
    AUTOMATIC_METHOD,
    ENVELOPE_SCHEMA_VERSION,
    PROFILE_SCHEMA_VERSION,
    ConfigurationSupportError,
    main,
    validate_configuration_support,
)
from open_duck_x5.constants import CONTROL_FREQUENCY_HZ, JOINT_NAMES, SERVO_IDS


def _profile() -> dict[str, object]:
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "source": {
            "method": AUTOMATIC_METHOD,
            "trace_sha256": "a" * 64,
            "manual_measurements_used": False,
            "motion_authorized": True,
            "suspended_or_benched": True,
            "torque_off_confirmed": True,
        },
        "inventory": {
            "required_servo_ids": list(SERVO_IDS),
            "responding_servo_ids": list(SERVO_IDS),
            "imu_present": True,
            "contacts_present": True,
        },
        "sample_contract": {
            "frequency_hz": CONTROL_FREQUENCY_HZ,
            "tick_count": 10_000,
            "complete": True,
            "stale_sample_count": 0,
            "transaction_failure_count": 0,
            "telemetry_drop_count": 0,
        },
        "joint_response": {
            name: {
                "delay_ticks": 2.0,
                "gain_ratio": 0.95,
                "time_constant_s": 0.05,
                "tracking_p95_rad": 0.01,
                "current_p95_a": 0.2,
            }
            for name in JOINT_NAMES
        },
        "body_response": {
            "pitch_rate_p95_rad_s": 0.2,
            "roll_rate_p95_rad_s": 0.2,
            "acceleration_norm_p95_m_s2": 9.81,
        },
    }


def _envelope() -> dict[str, object]:
    joint_bounds = {
        "delay_ticks": [0.0, 4.0],
        "gain_ratio": [0.5, 1.5],
        "time_constant_s": [0.0, 0.2],
        "tracking_p95_rad": [0.0, 0.05],
        "current_p95_a": [0.0, 2.0],
    }
    return {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "policy": {
            "repository": "RobVanProd/open-duck-mini-rdkx5",
            "commit": "d" * 40,
            "onnx_sha256": "b" * 64,
            "contract_id": "winner-v2-115d",
        },
        "preregistration": {
            "commit": "e" * 40,
            "artifact_path": "outputs/analysis/configuration_domain.json",
            "artifact_sha256": "c" * 64,
        },
        "per_unit_physical_measurement_required": False,
        "policy_robustness_gate_passed": True,
        "configuration_domain": {
            "torso_mass_scale": [0.5, 1.5],
            "torso_com_x_m": [-0.05, 0.05],
            "torso_com_y_m": [-0.03, 0.03],
            "torso_com_z_m": [-0.03, 0.03],
            "torso_inertia_scale": {
                "xx": [0.5, 1.5],
                "yy": [0.5, 1.5],
                "zz": [0.5, 1.5],
            },
            "coupled_sample_count": 128,
            "held_out_sample_count": 32,
            "supported_optional_component_configurations": [
                "baseline",
                "optional_torso_parts_removed",
            ],
        },
        "profile_metric_bounds": {
            "joints": {name: dict(joint_bounds) for name in JOINT_NAMES},
            "body": {
                "pitch_rate_p95_rad_s": [0.0, 1.0],
                "roll_rate_p95_rad_s": [0.0, 1.0],
                "acceleration_norm_p95_m_s2": [8.0, 12.0],
            },
        },
    }


def _write(path: Path, value: dict[str, object]) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_automatic_profile_passes_complete_policy_envelope(tmp_path: Path) -> None:
    profile = _write(tmp_path / "profile.json", _profile())
    envelope = _write(tmp_path / "envelope.json", _envelope())

    result = validate_configuration_support(profile_path=profile, envelope_path=envelope)

    assert result["status"] == "PASS_AUTOMATIC_CONFIGURATION_INSIDE_POLICY_ENVELOPE"
    assert result["issues"] == []
    assert len(result["metric_checks"]) == 73
    assert all(check["pass"] for check in result["metric_checks"])
    assert result["profile"]["manual_measurements_used"] is False
    assert result["authority"]["robot_clearance"] is False


def test_out_of_envelope_response_holds_without_measurement_waiver(tmp_path: Path) -> None:
    profile_value = _profile()
    profile_value["joint_response"][JOINT_NAMES[0]]["current_p95_a"] = 2.1
    profile = _write(tmp_path / "profile.json", profile_value)
    envelope = _write(tmp_path / "envelope.json", _envelope())

    result = validate_configuration_support(profile_path=profile, envelope_path=envelope)

    assert result["status"] == "HOLD_AUTOMATIC_CONFIGURATION_OUTSIDE_POLICY_ENVELOPE"
    assert result["issues"] == [
        f"joint_response.{JOINT_NAMES[0]}.current_p95_a.outside_supported_envelope"
    ]


def test_missing_contract_hardware_holds_fail_closed(tmp_path: Path) -> None:
    profile_value = _profile()
    missing_id = SERVO_IDS[-1]
    missing_joint = JOINT_NAMES[-1]
    profile_value["inventory"]["responding_servo_ids"].remove(missing_id)
    del profile_value["joint_response"][missing_joint]
    profile = _write(tmp_path / "profile.json", profile_value)
    envelope = _write(tmp_path / "envelope.json", _envelope())

    result = validate_configuration_support(profile_path=profile, envelope_path=envelope)

    assert result["status"] == "HOLD_AUTOMATIC_CONFIGURATION_OUTSIDE_POLICY_ENVELOPE"
    assert f"inventory.missing_servo_ids={missing_id}" in result["issues"]
    assert f"joint_response.{missing_joint}.missing" in result["issues"]
    assert "metric_population=68/73" in result["issues"]


def test_manual_measurement_profile_is_rejected(tmp_path: Path) -> None:
    profile_value = _profile()
    profile_value["source"]["manual_measurements_used"] = True
    profile = _write(tmp_path / "profile.json", profile_value)
    envelope = _write(tmp_path / "envelope.json", _envelope())

    with pytest.raises(ConfigurationSupportError, match="manual physical measurements"):
        validate_configuration_support(profile_path=profile, envelope_path=envelope)


def test_static_physical_parameter_field_is_rejected(tmp_path: Path) -> None:
    profile_value = _profile()
    profile_value["torso_com_x_m"] = 0.001
    profile = _write(tmp_path / "profile.json", profile_value)
    envelope = _write(tmp_path / "envelope.json", _envelope())

    with pytest.raises(ConfigurationSupportError, match="profile keys differ"):
        validate_configuration_support(profile_path=profile, envelope_path=envelope)


def test_policy_domain_must_cover_prior_fifty_mm_x_sweep(tmp_path: Path) -> None:
    envelope_value = _envelope()
    envelope_value["configuration_domain"]["torso_com_x_m"] = [-0.04, 0.05]
    profile = _write(tmp_path / "profile.json", _profile())
    envelope = _write(tmp_path / "envelope.json", envelope_value)

    with pytest.raises(ConfigurationSupportError, match=r"cover \[-0.05, 0.05\]"):
        validate_configuration_support(profile_path=profile, envelope_path=envelope)


def test_cli_writes_machine_readable_result(tmp_path: Path) -> None:
    profile = _write(tmp_path / "profile.json", _profile())
    envelope = _write(tmp_path / "envelope.json", _envelope())
    output = tmp_path / "result.json"

    assert (
        main(
            [
                "--profile",
                str(profile),
                "--envelope",
                str(envelope),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "PASS_AUTOMATIC_CONFIGURATION_INSIDE_POLICY_ENVELOPE"


def test_cli_cannot_overwrite_profile(tmp_path: Path) -> None:
    profile = _write(tmp_path / "profile.json", _profile())
    envelope = _write(tmp_path / "envelope.json", _envelope())
    original = profile.read_bytes()

    assert (
        main(
            [
                "--profile",
                str(profile),
                "--envelope",
                str(envelope),
                "--output",
                str(profile),
            ]
        )
        == 2
    )
    assert profile.read_bytes() == original


def test_cli_removes_stale_pass_output_when_input_is_invalid(tmp_path: Path) -> None:
    profile_value = _profile()
    profile_value["source"]["manual_measurements_used"] = True
    profile = _write(tmp_path / "profile.json", profile_value)
    envelope = _write(tmp_path / "envelope.json", _envelope())
    output = tmp_path / "result.json"
    output.write_text('{"status":"STALE_PASS"}', encoding="utf-8")

    assert (
        main(
            [
                "--profile",
                str(profile),
                "--envelope",
                str(envelope),
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert not output.exists()
