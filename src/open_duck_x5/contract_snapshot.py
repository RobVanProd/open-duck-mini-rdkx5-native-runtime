from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from .constants import ACTION_DIM, CONTRACT_ID, JOINT_NAMES, OBSERVATION_DIM
from .contract import ActionPipeline, ObservationAssembler


class ContractSnapshotError(ValueError):
    pass


COMMAND_NAMES = (
    "x_velocity",
    "y_velocity",
    "yaw_velocity",
    "neck_pitch",
    "head_pitch",
    "head_yaw",
    "head_roll",
)


def observation_field_labels() -> tuple[str, ...]:
    labels = [f"gyro.{axis}" for axis in "xyz"]
    labels.extend(f"acceleration.{axis}" for axis in "xyz")
    labels.extend(f"command.{name}" for name in COMMAND_NAMES)
    labels.extend(f"joint_position_error.{name}" for name in JOINT_NAMES)
    labels.extend(f"joint_velocity_scaled.{name}" for name in JOINT_NAMES)
    for age in (1, 2, 3):
        labels.extend(f"action_minus_{age}.{name}" for name in JOINT_NAMES)
    labels.extend(f"previous_motor_target.{name}" for name in JOINT_NAMES)
    labels.extend(("foot_contact.left", "foot_contact.right"))
    labels.extend(("phase.cos", "phase.sin"))
    if len(labels) != OBSERVATION_DIM:
        raise AssertionError(f"contract labels have length {len(labels)}")
    return tuple(labels)


OBSERVATION_FIELD_LABELS = observation_field_labels()


def _vector(
    container: dict[str, Any],
    key: str,
    length: int,
    *,
    dtype: type[np.float32] | type[np.float64] = np.float64,
) -> np.ndarray:
    try:
        value = np.asarray(container[key], dtype=dtype)
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractSnapshotError(f"{key} must be a numeric vector") from exc
    if value.shape != (length,):
        raise ContractSnapshotError(f"{key} must have shape ({length},), got {value.shape}")
    if not bool(np.isfinite(value).all()):
        raise ContractSnapshotError(f"{key} must contain only finite values")
    return value


def _history(inputs: dict[str, Any]) -> np.ndarray:
    try:
        history = np.asarray(inputs["action_history"], dtype=np.float32)
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractSnapshotError("action_history must be three numeric 14-vectors") from exc
    if history.shape != (3, ACTION_DIM):
        raise ContractSnapshotError(
            f"action_history must have shape (3,{ACTION_DIM}), got {history.shape}"
        )
    if not bool(np.isfinite(history).all()):
        raise ContractSnapshotError("action_history must contain only finite values")
    return history


def _comparison(
    legacy: np.ndarray,
    rebuilt: np.ndarray,
    labels: tuple[str, ...],
    tolerance: float,
) -> dict[str, object]:
    absolute = np.abs(legacy.astype(np.float64) - rebuilt.astype(np.float64))
    indices = np.flatnonzero(absolute > tolerance)
    return {
        "passed": indices.size == 0,
        "max_absolute_difference": float(np.max(absolute)) if absolute.size else 0.0,
        "mismatch_count": int(indices.size),
        "mismatches": [
            {
                "index": int(index),
                "field": labels[int(index)],
                "legacy": float(legacy[index]),
                "rebuilt": float(rebuilt[index]),
                "absolute_difference": float(absolute[index]),
            }
            for index in indices
        ],
    }


def verify_contract_snapshot(
    payload: dict[str, Any], *, tolerance: float = 1e-6
) -> dict[str, object]:
    if tolerance < 0 or not np.isfinite(tolerance):
        raise ContractSnapshotError("tolerance must be finite and nonnegative")
    if payload.get("schema_version") != "open_duck_x5.contract_snapshot.v1":
        raise ContractSnapshotError("unsupported contract snapshot schema_version")
    if payload.get("contract_id") != CONTRACT_ID:
        raise ContractSnapshotError(
            f"snapshot contract_id must be {CONTRACT_ID!r}"
        )
    phase_evidence = payload.get("phase_evidence")
    if not isinstance(phase_evidence, dict) or phase_evidence.get(
        "deployed_order_confirmed"
    ) is not True:
        raise ContractSnapshotError("snapshot must include confirmed deployed phase order")
    inputs = payload.get("inputs")
    legacy = payload.get("legacy_outputs")
    if not isinstance(inputs, dict) or not isinstance(legacy, dict):
        raise ContractSnapshotError("inputs and legacy_outputs must be objects")

    history = _history(inputs)
    input_phase = _vector(inputs, "phase", 2)
    evidence_observation_phase = _vector(
        phase_evidence, "observation_phase", 2
    )
    evidence_previous_phase = _vector(
        phase_evidence, "previous_post_advance_phase", 2
    )
    if not np.allclose(
        input_phase, evidence_observation_phase, atol=tolerance, rtol=0
    ) or not np.allclose(
        input_phase, evidence_previous_phase, atol=tolerance, rtol=0
    ):
        raise ContractSnapshotError(
            "phase evidence must match the phase supplied to the observation"
        )
    assembler = ObservationAssembler()
    np.copyto(assembler.last_action, history[0])
    np.copyto(assembler.action_minus_2, history[1])
    np.copyto(assembler.action_minus_3, history[2])
    previous_motor_target = _vector(
        inputs, "previous_motor_target_rad", ACTION_DIM
    )
    rebuilt_observation = assembler.build(
        gyro_rad_s=_vector(inputs, "gyro_rad_s", 3),
        acceleration_m_s2=_vector(inputs, "acceleration_m_s2", 3),
        commands=_vector(inputs, "commands", 7),
        positions_rad=_vector(inputs, "positions_rad", ACTION_DIM),
        velocities_rad_s=_vector(inputs, "velocities_rad_s", ACTION_DIM),
        previous_motor_target_rad=previous_motor_target,
        foot_contacts=_vector(inputs, "foot_contacts", 2),
        phase=input_phase,
        servo_stale=np.zeros(ACTION_DIM, dtype=np.bool_),
        imu_stale=False,
        contacts_stale=False,
    ).copy()

    pipeline = ActionPipeline()
    pipeline.seed_previous_targets(
        _vector(inputs, "previous_rate_target_rad", ACTION_DIM),
        previous_motor_target,
    )
    rebuilt_physical = pipeline.apply(
        _vector(inputs, "action", ACTION_DIM, dtype=np.float32),
        _vector(inputs, "commands", 7),
        _vector(inputs, "soft_offsets_rad", ACTION_DIM),
    ).copy()
    rebuilt_sent = pipeline.sent_target_rad.copy()

    observation_comparison = _comparison(
        _vector(legacy, "observation", OBSERVATION_DIM, dtype=np.float32),
        rebuilt_observation,
        OBSERVATION_FIELD_LABELS,
        tolerance,
    )
    action_labels = tuple(f"sent_target.{name}" for name in JOINT_NAMES)
    sent_comparison = _comparison(
        _vector(legacy, "sent_target_rad", ACTION_DIM),
        rebuilt_sent,
        action_labels,
        tolerance,
    )
    physical_labels = tuple(f"physical_target.{name}" for name in JOINT_NAMES)
    physical_comparison = _comparison(
        _vector(legacy, "physical_target_rad", ACTION_DIM),
        rebuilt_physical,
        physical_labels,
        tolerance,
    )
    passed = bool(
        observation_comparison["passed"]
        and sent_comparison["passed"]
        and physical_comparison["passed"]
    )
    return {
        "schema_version": "open_duck_x5.contract_report.v1",
        "contract_id": CONTRACT_ID,
        "source": payload.get("source"),
        "phase_evidence": phase_evidence,
        "tolerance": tolerance,
        "passed": passed,
        "observation": observation_comparison,
        "sent_target": sent_comparison,
        "physical_target": physical_comparison,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify a captured legacy 101/14 contract snapshot field by field"
    )
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=1e-6)
    args = parser.parse_args(argv)
    raw = args.snapshot.read_bytes()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        parser.error(f"invalid snapshot JSON: {exc}")
    try:
        report = verify_contract_snapshot(payload, tolerance=args.tolerance)
    except ContractSnapshotError as exc:
        parser.error(str(exc))
    report["snapshot_sha256"] = hashlib.sha256(raw).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    args.output.write_bytes(output)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
