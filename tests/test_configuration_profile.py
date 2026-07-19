from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest

from open_duck_x5.configuration_profile import (
    METADATA_SCHEMA_VERSION,
    TICK_SCHEMA_VERSION,
    ConfigurationProfileError,
    build_automatic_configuration_profile,
)
from open_duck_x5.configuration_profile import (
    main as profile_main,
)
from open_duck_x5.configuration_support import (
    ENVELOPE_SCHEMA_VERSION,
    ConfigurationSupportError,
    validate_configuration_support,
)
from open_duck_x5.configuration_support import (
    main as support_main,
)
from open_duck_x5.constants import CONTROL_FREQUENCY_HZ, HOME_RAD, JOINT_NAMES, SERVO_IDS

STAGE_TICKS = 81
DELAY_TICKS = 2
POLE = 0.8
GAIN = 0.9
CONFIGURATION_PATH = Path(__file__).resolve().parents[1] / "duck_config.example.json"
CONFIGURATION_SHA256 = hashlib.sha256(CONFIGURATION_PATH.read_bytes()).hexdigest()


def _excitation(local_tick: int) -> float:
    return 0.015 * math.sin(2.0 * math.pi * local_tick / 40.0) + 0.005 * math.sin(
        2.0 * math.pi * local_tick / 20.0
    )


def _evidence() -> tuple[dict[str, object], list[dict[str, object]]]:
    stages = [
        {
            "joint_name": name,
            "start_tick": index * STAGE_TICKS,
            "end_tick": (index + 1) * STAGE_TICKS,
        }
        for index, name in enumerate(JOINT_NAMES)
    ]
    metadata: dict[str, object] = {
        "schema_version": METADATA_SCHEMA_VERSION,
        "frequency_hz": CONTROL_FREQUENCY_HZ,
        "tick_count": STAGE_TICKS * len(JOINT_NAMES),
        "max_delay_ticks": 4,
        "minimum_stage_ticks": STAGE_TICKS,
        "minimum_target_span_rad": 0.03,
        "maximum_nonexcited_target_span_rad": 1e-12,
        "maximum_target_velocity_rad_s": 0.21,
        "maximum_home_deviation_rad": 0.03,
        "minimum_current_samples_per_joint": 10,
        "motion_authorized": True,
        "suspended_or_benched": True,
        "torque_off_confirmed": True,
        "telemetry_drop_count": 0,
        "configuration_sha256": CONFIGURATION_SHA256,
        "physical_home_rad": HOME_RAD.tolist(),
        "inventory": {
            "required_servo_ids": list(SERVO_IDS),
            "responding_servo_ids": list(SERVO_IDS),
            "imu_present": True,
            "contacts_present": True,
        },
        "stages": stages,
    }
    rows: list[dict[str, object]] = []
    timestamp_ns = 1_000_000_000
    for joint_index, joint_name in enumerate(JOINT_NAMES):
        inputs = np.asarray([_excitation(tick) for tick in range(STAGE_TICKS)])
        state = 0.0
        for local_tick in range(STAGE_TICKS):
            delayed = inputs[local_tick - DELAY_TICKS] if local_tick >= DELAY_TICKS else 0.0
            state = POLE * state + (1.0 - POLE) * GAIN * float(delayed)
            target = HOME_RAD.copy()
            actual = HOME_RAD.copy()
            target[joint_index] += inputs[local_tick]
            actual[joint_index] += state
            currents: list[float | None] = [None] * len(JOINT_NAMES)
            if local_tick % 5 == 0:
                currents[joint_index] = 0.2 + 0.1 * abs(_excitation(local_tick))
            global_tick = joint_index * STAGE_TICKS + local_tick
            rows.append(
                {
                    "schema_version": TICK_SCHEMA_VERSION,
                    "tick": global_tick,
                    "timestamp_monotonic_ns": timestamp_ns,
                    "stage_joint": joint_name,
                    "target_positions_rad": target.tolist(),
                    "actual_positions_rad": actual.tolist(),
                    "present_current_a": currents,
                    "gyro_rad_s": [
                        0.05 * math.sin(global_tick * 0.03),
                        0.08 * math.cos(global_tick * 0.02),
                        0.0,
                    ],
                    "acceleration_m_s2": [0.0, 0.0, 9.81],
                    "per_servo_status": ["ok"] * len(JOINT_NAMES),
                    "stale": [False] * len(JOINT_NAMES),
                    "imu_stale": False,
                    "contacts_stale": False,
                }
            )
            timestamp_ns += 20_000_000
    return metadata, rows


def _write_evidence(
    tmp_path: Path,
    metadata: dict[str, object],
    rows: list[dict[str, object]],
) -> tuple[Path, Path]:
    metadata_path = tmp_path / "metadata.json"
    trace_path = tmp_path / "trace.jsonl"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    trace_path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    return trace_path, metadata_path


def _support_envelope() -> dict[str, object]:
    bounds = {
        "delay_ticks": [0.0, 4.0],
        "gain_ratio": [0.5, 1.5],
        "time_constant_s": [0.0, 0.2],
        "tracking_p95_rad": [0.0, 0.1],
        "current_p95_a": [0.0, 1.0],
    }
    return {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "policy": {
            "repository": "RobVanProd/open-duck-mini-rdkx5",
            "commit": "d" * 40,
            "onnx_sha256": "e" * 64,
            "contract_id": "winner-v2-115d",
        },
        "preregistration": {
            "commit": "f" * 40,
            "artifact_path": "outputs/analysis/configuration_domain.json",
            "artifact_sha256": "a" * 64,
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
                "optional_parts_removed",
            ],
        },
        "profile_metric_bounds": {
            "joints": {name: dict(bounds) for name in JOINT_NAMES},
            "body": {
                "pitch_rate_p95_rad_s": [0.0, 1.0],
                "roll_rate_p95_rad_s": [0.0, 1.0],
                "acceleration_norm_p95_m_s2": [8.0, 12.0],
            },
        },
    }


def test_trace_is_fitted_into_profile_and_passes_support_validator(tmp_path: Path) -> None:
    metadata, rows = _evidence()
    trace, metadata_path = _write_evidence(tmp_path, metadata, rows)

    profile = build_automatic_configuration_profile(
        trace_path=trace,
        metadata_path=metadata_path,
        configuration_path=CONFIGURATION_PATH,
    )

    assert profile["source"]["manual_measurements_used"] is False
    assert profile["source"]["trace_sha256"] == hashlib.sha256(trace.read_bytes()).hexdigest()
    assert (
        profile["source"]["metadata_sha256"]
        == hashlib.sha256(metadata_path.read_bytes()).hexdigest()
    )
    assert profile["source"]["configuration_sha256"] == CONFIGURATION_SHA256
    assert profile["sample_contract"]["tick_count"] == STAGE_TICKS * 14
    assert set(profile["joint_response"]) == set(JOINT_NAMES)
    for response in profile["joint_response"].values():
        assert response["delay_ticks"] == DELAY_TICKS
        assert response["gain_ratio"] == pytest.approx(GAIN, abs=1e-9)
        assert response["time_constant_s"] == pytest.approx(-0.02 / math.log(POLE), abs=1e-9)

    profile_path = tmp_path / "profile.json"
    envelope_path = tmp_path / "envelope.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    envelope_path.write_text(json.dumps(_support_envelope()), encoding="utf-8")
    decision = validate_configuration_support(
        profile_path=profile_path,
        envelope_path=envelope_path,
        trace_path=trace,
        metadata_path=metadata_path,
        configuration_path=CONFIGURATION_PATH,
    )
    assert decision["status"] == "PASS_AUTOMATIC_CONFIGURATION_INSIDE_POLICY_ENVELOPE"
    assert len(decision["metric_checks"]) == 73
    assert decision["profile"]["raw_evidence_verified"] is True
    assert decision["profile"]["reproduction_max_abs_error"] == 0.0


def test_support_cli_verifies_complete_raw_evidence_chain(tmp_path: Path) -> None:
    metadata, rows = _evidence()
    trace, metadata_path = _write_evidence(tmp_path, metadata, rows)
    profile = build_automatic_configuration_profile(
        trace_path=trace,
        metadata_path=metadata_path,
        configuration_path=CONFIGURATION_PATH,
    )
    profile_path = tmp_path / "profile.json"
    envelope_path = tmp_path / "envelope.json"
    output_path = tmp_path / "result.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    envelope_path.write_text(json.dumps(_support_envelope()), encoding="utf-8")

    assert (
        support_main(
            [
                "--profile",
                str(profile_path),
                "--envelope",
                str(envelope_path),
                "--trace",
                str(trace),
                "--metadata",
                str(metadata_path),
                "--configuration",
                str(CONFIGURATION_PATH),
                "--output",
                str(output_path),
            ]
        )
        == 0
    )
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["status"] == "PASS_AUTOMATIC_CONFIGURATION_INSIDE_POLICY_ENVELOPE"
    assert result["profile"]["raw_evidence_verified"] is True


def test_tampered_profile_cannot_pass_raw_evidence_reproduction(tmp_path: Path) -> None:
    metadata, rows = _evidence()
    trace, metadata_path = _write_evidence(tmp_path, metadata, rows)
    profile = build_automatic_configuration_profile(
        trace_path=trace,
        metadata_path=metadata_path,
        configuration_path=CONFIGURATION_PATH,
    )
    profile["joint_response"][JOINT_NAMES[0]]["gain_ratio"] += 1e-6
    profile_path = tmp_path / "profile.json"
    envelope_path = tmp_path / "envelope.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    envelope_path.write_text(json.dumps(_support_envelope()), encoding="utf-8")

    with pytest.raises(ConfigurationSupportError, match="reproduced profile"):
        validate_configuration_support(
            profile_path=profile_path,
            envelope_path=envelope_path,
            trace_path=trace,
            metadata_path=metadata_path,
            configuration_path=CONFIGURATION_PATH,
        )


def test_metadata_rejects_manual_static_com_field(tmp_path: Path) -> None:
    metadata, rows = _evidence()
    metadata["torso_com_x_m"] = 0.0
    trace, metadata_path = _write_evidence(tmp_path, metadata, rows)

    with pytest.raises(ConfigurationProfileError, match="metadata keys differ"):
        build_automatic_configuration_profile(
            trace_path=trace,
            metadata_path=metadata_path,
            configuration_path=CONFIGURATION_PATH,
        )


def test_metadata_is_bound_to_exact_configuration(tmp_path: Path) -> None:
    metadata, rows = _evidence()
    metadata["configuration_sha256"] = "9" * 64
    trace, metadata_path = _write_evidence(tmp_path, metadata, rows)

    with pytest.raises(ConfigurationProfileError, match="configuration SHA-256"):
        build_automatic_configuration_profile(
            trace_path=trace,
            metadata_path=metadata_path,
            configuration_path=CONFIGURATION_PATH,
        )


def test_trace_tick_gap_is_rejected(tmp_path: Path) -> None:
    metadata, rows = _evidence()
    rows[7]["tick"] = 8
    trace, metadata_path = _write_evidence(tmp_path, metadata, rows)

    with pytest.raises(ConfigurationProfileError, match="tick sequence"):
        build_automatic_configuration_profile(
            trace_path=trace,
            metadata_path=metadata_path,
            configuration_path=CONFIGURATION_PATH,
        )


def test_stale_sensor_trace_is_rejected(tmp_path: Path) -> None:
    metadata, rows = _evidence()
    rows[10]["imu_stale"] = True
    trace, metadata_path = _write_evidence(tmp_path, metadata, rows)

    with pytest.raises(ConfigurationProfileError, match="stale IMU"):
        build_automatic_configuration_profile(
            trace_path=trace,
            metadata_path=metadata_path,
            configuration_path=CONFIGURATION_PATH,
        )


def test_cross_joint_excitation_is_rejected(tmp_path: Path) -> None:
    metadata, rows = _evidence()
    rows[5]["target_positions_rad"][1] += 0.001
    trace, metadata_path = _write_evidence(tmp_path, metadata, rows)

    with pytest.raises(ConfigurationProfileError, match="also excites"):
        build_automatic_configuration_profile(
            trace_path=trace,
            metadata_path=metadata_path,
            configuration_path=CONFIGURATION_PATH,
        )


def test_excessive_target_velocity_is_rejected(tmp_path: Path) -> None:
    metadata, rows = _evidence()
    rows[5]["target_positions_rad"][0] += 0.01
    trace, metadata_path = _write_evidence(tmp_path, metadata, rows)

    with pytest.raises(ConfigurationProfileError, match="maximum target velocity"):
        build_automatic_configuration_profile(
            trace_path=trace,
            metadata_path=metadata_path,
            configuration_path=CONFIGURATION_PATH,
        )


def test_insufficient_automatic_current_samples_is_rejected(tmp_path: Path) -> None:
    metadata, rows = _evidence()
    for row in rows[:STAGE_TICKS]:
        row["present_current_a"] = [None] * len(JOINT_NAMES)
    trace, metadata_path = _write_evidence(tmp_path, metadata, rows)

    with pytest.raises(ConfigurationProfileError, match="current samples"):
        build_automatic_configuration_profile(
            trace_path=trace,
            metadata_path=metadata_path,
            configuration_path=CONFIGURATION_PATH,
        )


def test_cli_writes_profile_and_removes_stale_output_on_failure(tmp_path: Path) -> None:
    metadata, rows = _evidence()
    trace, metadata_path = _write_evidence(tmp_path, metadata, rows)
    output = tmp_path / "profile.json"

    assert (
        profile_main(
            [
                "--trace",
                str(trace),
                "--metadata",
                str(metadata_path),
                "--configuration",
                str(CONFIGURATION_PATH),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert output.exists()

    rows[1]["contacts_stale"] = True
    _write_evidence(tmp_path, metadata, rows)
    assert (
        profile_main(
            [
                "--trace",
                str(trace),
                "--metadata",
                str(metadata_path),
                "--configuration",
                str(CONFIGURATION_PATH),
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert not output.exists()
