from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from jsonschema import Draft202012Validator

from open_duck_x5.constants import ACTION_DIM, CONTRACT_ID, HOME_RAD, JOINT_NAMES, SERVO_IDS
from open_duck_x5.contract_snapshot import main, verify_contract_snapshot
from open_duck_x5.legacy_contract import extract_contract_snapshot


def _legacy_snapshot() -> dict[str, object]:
    gyro = np.array([0.1, -0.2, 0.3])
    acceleration = np.array([1.1, 2.2, 8.8])
    commands = np.array([0.08, -0.02, 0.3, 0.01, -0.02, 0.03, -0.04])
    positions = HOME_RAD + np.linspace(-0.07, 0.06, ACTION_DIM)
    velocities = np.linspace(-1.3, 1.3, ACTION_DIM)
    history = np.stack(
        [
            np.linspace(-0.4, 0.4, ACTION_DIM),
            np.linspace(-0.3, 0.3, ACTION_DIM),
            np.linspace(-0.2, 0.2, ACTION_DIM),
        ]
    ).astype(np.float32)
    previous_sent = HOME_RAD + np.linspace(-0.02, 0.02, ACTION_DIM)
    previous_rate = HOME_RAD + np.linspace(-0.01, 0.01, ACTION_DIM)
    contacts = np.array([1.0, 0.0])
    phase = np.array([0.6, -0.8])
    action = np.linspace(-1.0, 1.0, ACTION_DIM).astype(np.float32)
    offsets = np.linspace(-0.005, 0.005, ACTION_DIM)

    observation = np.concatenate(
        [
            gyro,
            acceleration,
            commands,
            positions - HOME_RAD,
            velocities * 0.05,
            history[0],
            history[1],
            history[2],
            previous_sent,
            contacts,
            phase,
        ]
    ).astype(np.float32)
    unlimited = HOME_RAD + action.astype(np.float64) * 0.25
    max_step = 5.24 / 50.0
    sent = previous_rate + np.clip(unlimited - previous_rate, -max_step, max_step)
    sent[5:9] += commands[3:7]
    physical = sent + offsets

    return {
        "schema_version": "open_duck_x5.contract_snapshot.v1",
        "contract_id": CONTRACT_ID,
        "source": "independent-offline-legacy-oracle",
        "phase_evidence": {
            "observation_phase": phase.tolist(),
            "previous_post_advance_phase": phase.tolist(),
            "current_post_advance_phase": [0.5, -0.8660254037844386],
            "deployed_order_confirmed": True,
        },
        "inputs": {
            "gyro_rad_s": gyro.tolist(),
            "acceleration_m_s2": acceleration.tolist(),
            "commands": commands.tolist(),
            "positions_rad": positions.tolist(),
            "velocities_rad_s": velocities.tolist(),
            "action_history": history.tolist(),
            "previous_motor_target_rad": previous_sent.tolist(),
            "previous_rate_target_rad": previous_rate.tolist(),
            "foot_contacts": contacts.tolist(),
            "phase": phase.tolist(),
            "action": action.tolist(),
            "soft_offsets_rad": offsets.tolist(),
        },
        "legacy_outputs": {
            "observation": observation.tolist(),
            "sent_target_rad": sent.tolist(),
            "physical_target_rad": physical.tolist(),
        },
    }


def test_contract_snapshot_passes_independent_legacy_formula() -> None:
    payload = _legacy_snapshot()
    schema_path = Path(__file__).parents[1] / "schemas" / "contract_snapshot.schema.json"
    Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8"))).validate(
        payload
    )
    report = verify_contract_snapshot(payload)
    assert report["passed"] is True
    assert report["observation"]["mismatch_count"] == 0
    assert report["sent_target"]["mismatch_count"] == 0
    assert report["physical_target"]["mismatch_count"] == 0


def test_contract_snapshot_names_the_exact_mismatched_field(tmp_path: Path) -> None:
    payload = _legacy_snapshot()
    payload["legacy_outputs"]["observation"][99] += 0.25
    report = verify_contract_snapshot(payload)
    assert report["passed"] is False
    mismatch = report["observation"]["mismatches"][0]
    assert mismatch["index"] == 99
    assert mismatch["field"] == "phase.cos"
    assert np.isclose(mismatch["absolute_difference"], 0.25)

    snapshot = tmp_path / "snapshot.json"
    output = tmp_path / "report.json"
    snapshot.write_text(json.dumps(payload), encoding="utf-8")
    assert main([str(snapshot), "--output", str(output)]) == 2
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["passed"] is False
    assert len(written["snapshot_sha256"]) == 64


def test_extracts_same_tick_snapshot_from_preserved_telemetry() -> None:
    expected = _legacy_snapshot()
    inputs = expected["inputs"]
    outputs = expected["legacy_outputs"]
    previous = {
        "schema_version": "sim2real.telemetry.v1",
        "tick": 40,
        "action": {
            "motor_targets_post_rate_limit_rad": inputs["previous_rate_target_rad"],
            "motor_targets_sent_rad": inputs["previous_motor_target_rad"],
        },
        "control": {"imitation_phase": inputs["phase"]},
    }
    current = {
        "schema_version": "sim2real.telemetry.v1",
        "tick": 41,
        "control": {
            "control_freq_hz": 50.0,
            "action_scale": 0.25,
            "max_motor_velocity_rad_s": 5.24,
            "cutoff_frequency_hz": None,
            "imitation_phase": [99.0, 99.0],
        },
        "policy": {
            "input_name": "obs",
            "output_name": "continuous_actions",
            "observation_dim": 101,
            "action_dim": 14,
        },
        "joints": {
            "names": list(JOINT_NAMES),
            "servo_ids": list(SERVO_IDS),
            "offsets_rad": inputs["soft_offsets_rad"],
            "actual_position_rad": inputs["positions_rad"],
            "actual_velocity_rad_s": inputs["velocities_rad_s"],
        },
        "observation": {"raw_vector": outputs["observation"]},
        "action": {
            "onnx_action": inputs["action"],
            "motor_targets_sent_rad": outputs["sent_target_rad"],
        },
    }
    extracted = extract_contract_snapshot(
        previous, current, source="synthetic-legacy-telemetry"
    )
    np.testing.assert_allclose(extracted["inputs"]["phase"], inputs["phase"])
    assert extracted["inputs"]["phase"] != current["control"]["imitation_phase"]
    assert verify_contract_snapshot(extracted)["passed"] is True


def test_rejects_previous_motor_target_that_is_not_the_prior_sent_target() -> None:
    expected = _legacy_snapshot()
    inputs = expected["inputs"]
    outputs = expected["legacy_outputs"]
    previous = {
        "schema_version": "sim2real.telemetry.v1",
        "tick": 10,
        "action": {
            "motor_targets_post_rate_limit_rad": inputs["previous_rate_target_rad"],
            "motor_targets_sent_rad": np.asarray(
                inputs["previous_motor_target_rad"], dtype=np.float64
            ).tolist(),
        },
        "control": {"imitation_phase": inputs["phase"]},
    }
    current = {
        "schema_version": "sim2real.telemetry.v1",
        "tick": 11,
        "control": {
            "control_freq_hz": 50.0,
            "action_scale": 0.25,
            "max_motor_velocity_rad_s": 5.24,
            "cutoff_frequency_hz": None,
            "imitation_phase": [99.0, 99.0],
        },
        "policy": {
            "input_name": "obs",
            "output_name": "continuous_actions",
            "observation_dim": 101,
            "action_dim": 14,
        },
        "joints": {
            "names": list(JOINT_NAMES),
            "servo_ids": list(SERVO_IDS),
            "offsets_rad": inputs["soft_offsets_rad"],
            "actual_position_rad": inputs["positions_rad"],
            "actual_velocity_rad_s": inputs["velocities_rad_s"],
        },
        "observation": {"raw_vector": outputs["observation"]},
        "action": {
            "onnx_action": inputs["action"],
            "motor_targets_sent_rad": outputs["sent_target_rad"],
        },
    }
    previous["action"]["motor_targets_sent_rad"][0] += 0.1

    with np.testing.assert_raises_regex(
        ValueError, "previous-motor-target slice does not match the prior sent target"
    ):
        extract_contract_snapshot(previous, current, source="mismatched-prior-target")
