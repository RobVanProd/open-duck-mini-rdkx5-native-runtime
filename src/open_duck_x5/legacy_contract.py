from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from .constants import ACTION_DIM, CONTRACT_ID, HOME_RAD, JOINT_NAMES, SERVO_IDS
from .contract_snapshot import ContractSnapshotError


def _nested(record: dict[str, Any], *keys: str) -> Any:
    value: Any = record
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            raise ContractSnapshotError(f"legacy telemetry is missing {'.'.join(keys)}")
        value = value[key]
    return value


def _array(value: Any, length: int, label: str) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ContractSnapshotError(f"{label} must be numeric") from exc
    if array.shape != (length,):
        raise ContractSnapshotError(f"{label} must have shape ({length},), got {array.shape}")
    if not bool(np.isfinite(array).all()):
        raise ContractSnapshotError(f"{label} contains non-finite values")
    return array


def extract_contract_snapshot(
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    source: str,
    tolerance: float = 1e-5,
) -> dict[str, object]:
    if previous.get("schema_version") != "sim2real.telemetry.v1" or current.get(
        "schema_version"
    ) != "sim2real.telemetry.v1":
        raise ContractSnapshotError("both records must use sim2real.telemetry.v1")
    previous_tick = int(previous.get("tick", -1))
    current_tick = int(current.get("tick", -1))
    if current_tick != previous_tick + 1:
        raise ContractSnapshotError(
            "contract extraction requires adjacent telemetry ticks; use telemetry_every_n=1"
        )

    policy_input = str(_nested(current, "policy", "input_name"))
    policy_output = str(_nested(current, "policy", "output_name"))
    observation_dim = int(_nested(current, "policy", "observation_dim"))
    action_dim = int(_nested(current, "policy", "action_dim"))
    if (
        policy_input != "obs"
        or policy_output != "continuous_actions"
        or observation_dim != 101
        or action_dim != ACTION_DIM
    ):
        raise ContractSnapshotError(
            "legacy ONNX interface differs: "
            f"input={policy_input}, output={policy_output}, "
            f"observation_dim={observation_dim}, action_dim={action_dim}"
        )

    observation = _array(
        _nested(current, "observation", "raw_vector"), 101, "observation.raw_vector"
    )
    positions = _array(
        _nested(current, "joints", "actual_position_rad"),
        ACTION_DIM,
        "joints.actual_position_rad",
    )
    velocities = _array(
        _nested(current, "joints", "actual_velocity_rad_s"),
        ACTION_DIM,
        "joints.actual_velocity_rad_s",
    )
    names = tuple(_nested(current, "joints", "names"))
    ids = tuple(int(value) for value in _nested(current, "joints", "servo_ids"))
    if names != JOINT_NAMES or ids != SERVO_IDS:
        raise ContractSnapshotError(
            f"legacy joint map differs: names={names!r}, servo_ids={ids!r}"
        )
    if not np.allclose(observation[13:27], positions - HOME_RAD, atol=tolerance, rtol=0):
        raise ContractSnapshotError("observation position slice does not match captured state")
    if not np.allclose(observation[27:41], velocities * 0.05, atol=tolerance, rtol=0):
        raise ContractSnapshotError("observation velocity slice does not match captured state")

    action_scale = float(_nested(current, "control", "action_scale"))
    max_velocity = float(_nested(current, "control", "max_motor_velocity_rad_s"))
    control_frequency = float(_nested(current, "control", "control_freq_hz"))
    cutoff_frequency_raw = _nested(current, "control", "cutoff_frequency_hz")
    # The preserved runtime serializes a disabled optional filter as JSON null.
    # Treat that as the contract's zero/disabled value instead of rejecting an
    # otherwise valid board capture with float(None).
    cutoff_frequency = (
        0.0 if cutoff_frequency_raw is None else float(cutoff_frequency_raw)
    )
    if (
        abs(action_scale - 0.25) > tolerance
        or abs(max_velocity - 5.24) > tolerance
        or abs(control_frequency - 50.0) > tolerance
        or abs(cutoff_frequency) > tolerance
    ):
        raise ContractSnapshotError(
            "legacy action settings differ: "
            f"scale={action_scale}, max_velocity={max_velocity}, "
            f"control_frequency={control_frequency}, cutoff_frequency={cutoff_frequency}"
        )
    action = _array(_nested(current, "action", "onnx_action"), ACTION_DIM, "onnx_action")
    previous_rate = _array(
        _nested(previous, "action", "motor_targets_post_rate_limit_rad"),
        ACTION_DIM,
        "previous motor_targets_post_rate_limit_rad",
    )
    previous_sent = _array(
        _nested(previous, "action", "motor_targets_sent_rad"),
        ACTION_DIM,
        "previous motor_targets_sent_rad",
    )
    if not np.allclose(
        observation[83:97], previous_sent, atol=tolerance, rtol=0
    ):
        raise ContractSnapshotError(
            "observation previous-motor-target slice does not match the prior sent target"
        )
    sent = _array(
        _nested(current, "action", "motor_targets_sent_rad"),
        ACTION_DIM,
        "motor_targets_sent_rad",
    )
    offsets = _array(
        _nested(current, "joints", "offsets_rad"), ACTION_DIM, "joints.offsets_rad"
    )
    previous_post_advance_phase = _array(
        _nested(previous, "control", "imitation_phase"),
        2,
        "previous control.imitation_phase",
    )
    current_post_advance_phase = _array(
        _nested(current, "control", "imitation_phase"),
        2,
        "current control.imitation_phase",
    )
    observation_phase = observation[99:101]
    if not np.allclose(
        observation_phase,
        previous_post_advance_phase,
        atol=tolerance,
        rtol=0,
    ):
        raise ContractSnapshotError(
            "observation phase does not equal the previous tick's post-advance phase"
        )

    return {
        "schema_version": "open_duck_x5.contract_snapshot.v1",
        "contract_id": CONTRACT_ID,
        "source": f"{source}:ticks:{previous_tick},{current_tick}",
        "phase_evidence": {
            "observation_phase": observation_phase.tolist(),
            "previous_post_advance_phase": previous_post_advance_phase.tolist(),
            "current_post_advance_phase": current_post_advance_phase.tolist(),
            "deployed_order_confirmed": True,
        },
        "inputs": {
            "gyro_rad_s": observation[0:3].tolist(),
            "acceleration_m_s2": observation[3:6].tolist(),
            "commands": observation[6:13].tolist(),
            "positions_rad": positions.tolist(),
            "velocities_rad_s": velocities.tolist(),
            "action_history": [
                observation[41:55].tolist(),
                observation[55:69].tolist(),
                observation[69:83].tolist(),
            ],
            "previous_motor_target_rad": observation[83:97].tolist(),
            "previous_rate_target_rad": previous_rate.tolist(),
            "foot_contacts": observation[97:99].tolist(),
            "phase": observation[99:101].tolist(),
            "action": action.tolist(),
            "soft_offsets_rad": offsets.tolist(),
        },
        "legacy_outputs": {
            "observation": observation.tolist(),
            "sent_target_rad": sent.tolist(),
            "physical_target_rad": (sent + offsets).tolist(),
        },
    }


def _load_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ContractSnapshotError(f"invalid JSONL line {line_number}: {exc}") from exc
            if isinstance(record, dict) and record.get("schema_version") == "sim2real.telemetry.v1":
                records.append(record)
    if len(records) < 2:
        raise ContractSnapshotError("legacy telemetry needs at least two policy records")
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract a same-tick 101/14 snapshot from preserved-runtime telemetry"
    )
    parser.add_argument("legacy_jsonl", type=Path)
    parser.add_argument(
        "--tick",
        type=int,
        help="current tick to extract; default first adjacent pair",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=1e-5)
    args = parser.parse_args(argv)
    try:
        records = _load_records(args.legacy_jsonl)
        pair: tuple[dict[str, Any], dict[str, Any]] | None = None
        for previous, current in zip(records, records[1:], strict=False):
            if args.tick is not None and int(current.get("tick", -1)) != args.tick:
                continue
            if int(current.get("tick", -1)) == int(previous.get("tick", -1)) + 1:
                pair = (previous, current)
                break
        if pair is None:
            raise ContractSnapshotError("no requested adjacent telemetry pair was found")
        snapshot = extract_contract_snapshot(
            pair[0],
            pair[1],
            source=str(args.legacy_jsonl),
            tolerance=args.tolerance,
        )
    except ContractSnapshotError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output = (json.dumps(snapshot, indent=2, sort_keys=True) + "\n").encode("utf-8")
    args.output.write_bytes(output)
    print(f"wrote contract snapshot for tick {pair[1]['tick']}: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
