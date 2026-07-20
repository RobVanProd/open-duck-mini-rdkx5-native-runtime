"""Offline 2,400-tick verifier for the reviewed winner-v2 handoff package."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from contextlib import suppress
from importlib import metadata
from pathlib import Path
from typing import Any

import numpy as np

from .bus.sts3215 import rad_to_raw_position
from .constants import ACTION_DIM, CONTROL_PERIOD_NS, HOME_RAD, JOINT_NAMES
from .winner_v2 import (
    WINNER_V2_HANDOFF_CORRECTION_COMMIT,
    WINNER_V2_HANDOFF_MANIFEST_SHA256,
    WINNER_V2_POLICY_SELECTION_EVIDENCE_COMMIT,
    WINNER_V2_POLICY_SELECTION_RESULT_SHA256,
    WINNER_V2_SELECTED_POLICY_SHA256,
    P30BridgeObserver,
    ProjectedReferenceTable,
    WinnerV2ActionPipeline,
    WinnerV2ContractError,
    WinnerV2ObservationAssembler,
    WinnerV2OnnxPolicy,
    WinnerV2PhaseClock,
    WinnerV2SendError,
    WinnerV2TickTransaction,
    sha256_file,
)

TOLERANCE = 1.0e-6
EXPECTED_TICKS_PER_CELL = 600
EXPECTED_CELLS = 4
RECURSIVE_PREREGISTRATION_COMMIT = "182459eb4d5eb422a6936b7744f5730d22a9bb27"
RUNTIME_STS3215_SOURCE_SHA256 = (
    "a52b5a1551dce7940aadbd1b6446b91a796d279875d77ee247e4ef1cd43b4aa8"
)
RUNTIME_CONSTANTS_SOURCE_SHA256 = (
    "80ff38cd4a4436b445754051f1de608797f051f1886b142a29bf4f5f8b2f2ca3"
)
SOFT_OFFSET_SNAPSHOT_SHA256 = (
    "298753fb30c658321161df50f668ad7ab25121a1958c4b7bbdb1c543caf06bff"
)
STS_POSITION_COUNTS_PER_REVOLUTION = 4096
STS_POSITION_LSB_RAD = 2.0 * np.pi / STS_POSITION_COUNTS_PER_REVOLUTION
STS_HALF_LSB_RAD = np.pi / STS_POSITION_COUNTS_PER_REVOLUTION
MAX_RAW_GOAL_DIFFERENCE = 1
EXPECTED_SOFT_OFFSETS_RAD = np.asarray(
    [
        0.0844,
        0.0721,
        -0.089,
        0.0371,
        -0.0767,
        0.0245,
        0.0,
        -0.089,
        -0.0399,
        0.0951,
        -0.0476,
        0.066,
        0.0798,
        0.1887,
    ],
    dtype=np.float64,
)
EXPECTED_SOFT_OFFSETS_RAD.setflags(write=False)


def _maximum_error(left: np.ndarray, right: np.ndarray) -> float:
    return float(
        np.max(
            np.abs(
                np.asarray(left, dtype=np.float64)
                - np.asarray(right, dtype=np.float64)
            )
        )
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise WinnerV2ContractError(message)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise WinnerV2ContractError(f"{path.name} root must be an object")
    return value


def _environment() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "numpy": np.__version__,
        "onnxruntime": metadata.version("onnxruntime"),
        "onnx_execution_provider": "CPUExecutionProvider",
    }


def _runtime_identity(runtime_root: Path) -> dict[str, object]:
    runtime_root = runtime_root.resolve()
    sts_path = runtime_root / "src" / "open_duck_x5" / "bus" / "sts3215.py"
    constants_path = runtime_root / "src" / "open_duck_x5" / "constants.py"
    snapshot_path = (
        runtime_root / "artifacts" / "contracts" / "legacy-contract-snapshot.json"
    )
    _require(
        sha256_file(sts_path) == RUNTIME_STS3215_SOURCE_SHA256,
        "runtime STS3215 conversion source identity changed",
    )
    _require(
        sha256_file(constants_path) == RUNTIME_CONSTANTS_SOURCE_SHA256,
        "runtime constants source identity changed",
    )
    _require(
        sha256_file(snapshot_path) == SOFT_OFFSET_SNAPSHOT_SHA256,
        "physical soft-offset snapshot identity changed",
    )
    snapshot = _load_json(snapshot_path)
    inputs = snapshot.get("inputs")
    _require(isinstance(inputs, dict), "contract snapshot inputs are missing")
    offsets = np.asarray(inputs.get("soft_offsets_rad"), dtype=np.float64)
    _require(
        offsets.shape == (ACTION_DIM,)
        and np.array_equal(offsets, EXPECTED_SOFT_OFFSETS_RAD),
        "physical soft offsets differ from the frozen recursive preregistration",
    )
    return {
        "sts3215_source_sha256": RUNTIME_STS3215_SOURCE_SHA256,
        "constants_source_sha256": RUNTIME_CONSTANTS_SOURCE_SHA256,
        "soft_offset_snapshot_sha256": SOFT_OFFSET_SNAPSHOT_SHA256,
        "soft_offsets_rad": offsets.tolist(),
    }


def native_resolution_decision(
    *,
    component_passed: bool,
    recursive_x0_exact: bool,
    target_error_rad: float,
    observer_error_rad: float,
    raw_error_counts: int,
    raw_mismatch_count: int,
    classifications_unchanged: bool,
    raw_range_valid: bool,
) -> tuple[str, bool]:
    passed = bool(
        component_passed
        and recursive_x0_exact
        and target_error_rad <= STS_HALF_LSB_RAD
        and observer_error_rad <= STS_HALF_LSB_RAD
        and raw_error_counts <= MAX_RAW_GOAL_DIFFERENCE
        and classifications_unchanged
        and raw_range_valid
    )
    if passed and raw_mismatch_count == 0:
        return "PASS_RECURSIVE_BIT_EXACT_WIRE_CLOSURE", True
    if passed:
        return "PASS_RECURSIVE_NATIVE_RESOLUTION_CLOSURE", True
    if component_passed:
        return "HOLD_RECURSIVE_NUMERIC_CLOSURE", False
    return "INVALID_RECURSIVE_CROSS_CPU_STUDY", False


def _verify_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / "manifest.json"
    _require(manifest_path.is_file(), "handoff manifest.json is missing")
    manifest_hash = sha256_file(manifest_path)
    _require(
        manifest_hash == WINNER_V2_HANDOFF_MANIFEST_SHA256,
        f"unreviewed winner-v2 manifest SHA-256: {manifest_hash}",
    )
    manifest = _load_json(manifest_path)
    files = manifest.get("files")
    _require(isinstance(files, list) and bool(files), "manifest files list is missing")
    root_resolved = root.resolve()
    checked = 0
    for record in files:
        _require(isinstance(record, dict), "manifest file record must be an object")
        relative = record.get("path")
        _require(isinstance(relative, str) and relative, "manifest path is invalid")
        path = (root / relative).resolve()
        _require(
            path == root_resolved or root_resolved in path.parents,
            f"manifest path escapes artifact root: {relative}",
        )
        _require(path.is_file(), f"manifest file is missing: {relative}")
        _require(
            path.stat().st_size == int(record.get("bytes", -1)),
            f"manifest byte-size mismatch: {relative}",
        )
        actual_hash = sha256_file(path)
        _require(
            actual_hash == record.get("sha256"),
            f"manifest SHA-256 mismatch: {relative}",
        )
        checked += 1
    return {
        "manifest": manifest,
        "manifest_sha256": manifest_hash,
        "files_checked": checked,
    }


def _stage_arguments(pack: Any, tick: int) -> dict[str, object]:
    observation = np.asarray(pack["obs"][tick], dtype=np.float32)
    velocities = np.asarray(observation[27:41], dtype=np.float64) / 0.05
    positions = HOME_RAD + np.asarray(observation[13:27], dtype=np.float64)
    return {
        "tick_index": tick,
        "logical_period_ns": CONTROL_PERIOD_NS,
        "servo_sample_tick_index": tick,
        "imu_sample_tick_index": tick,
        "contacts_sample_tick_index": tick,
        "gyro_rad_s": np.asarray(observation[0:3], dtype=np.float64),
        "acceleration_m_s2": np.asarray(observation[3:6], dtype=np.float64),
        "commands": np.asarray(observation[6:13], dtype=np.float64),
        "positions_rad": positions,
        "velocities_rad_s": velocities,
        "foot_contacts": np.asarray(observation[97:99], dtype=np.float64),
        "servo_stale": np.zeros(ACTION_DIM, dtype=np.bool_),
        "imu_stale": False,
        "contacts_stale": False,
        "soft_offsets_rad": np.zeros(ACTION_DIM, dtype=np.float64),
    }


def _make_transaction(
    root: Path,
    policy_path: Path,
    *,
    allow_audit_policy: bool = False,
) -> WinnerV2TickTransaction:
    return WinnerV2TickTransaction(
        policy=WinnerV2OnnxPolicy(
            policy_path, allow_audit_policy=allow_audit_policy
        ),
        observer=P30BridgeObserver(root / "observer" / "p30_actuator_fit.json"),
        reference=ProjectedReferenceTable(
            root / "reference" / "ground_up_projected_reference_feature_table.npz"
        ),
    )


def _fault_injection(root: Path, policy_path: Path, pack_path: Path) -> dict[str, bool]:
    with np.load(pack_path, allow_pickle=False) as pack:
        transaction = _make_transaction(root, policy_path)
        baseline = {
            "policy": transaction.policy.previous_action_view.copy(),
            "observer": transaction.observer.value_view.copy(),
            "target": transaction.action_pipeline.previous_logical_target_view.copy(),
            "phase": transaction.phase.value.copy(),
            "history": transaction.assembler.last_action.copy(),
        }
        transaction.stage_tick(**_stage_arguments(pack, 0))
        rejected_send = False
        try:
            transaction.complete_send(write_succeeded=False)
        except WinnerV2SendError:
            rejected_send = True
        state_unchanged = bool(
            rejected_send
            and transaction.committed_ticks == 0
            and not transaction.pending
            and np.array_equal(
                transaction.policy.previous_action_view, baseline["policy"]
            )
            and np.array_equal(transaction.observer.value_view, baseline["observer"])
            and np.array_equal(
                transaction.action_pipeline.previous_logical_target_view,
                baseline["target"],
            )
            and np.array_equal(transaction.phase.value, baseline["phase"])
            and np.array_equal(transaction.assembler.last_action, baseline["history"])
        )

        cases: dict[str, dict[str, object]] = {}
        stale = _stage_arguments(pack, 0)
        stale["imu_stale"] = True
        cases["stale_sample"] = stale
        ambiguous = _stage_arguments(pack, 0)
        ambiguous["imu_sample_tick_index"] = -1
        cases["ambiguous_sample_epoch"] = ambiguous
        unsupported = _stage_arguments(pack, 0)
        unsupported["commands"] = np.asarray(
            [0.05, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float64
        )
        cases["unsupported_command"] = unsupported
        nonfinite = _stage_arguments(pack, 0)
        nonfinite["gyro_rad_s"][0] = np.nan
        cases["nonfinite_sensor"] = nonfinite

        rejected: dict[str, bool] = {}
        for label, arguments in cases.items():
            try:
                transaction.stage_tick(**arguments)
            except WinnerV2ContractError:
                rejected[label] = not transaction.pending and transaction.committed_ticks == 0
            else:
                rejected[label] = False
                if transaction.pending:
                    with suppress(WinnerV2SendError):
                        transaction.complete_send(write_succeeded=False)
        return {
            "failed_send_rejected": rejected_send,
            "failed_send_state_unchanged": state_unchanged,
            **rejected,
        }


def _verify_semantic_cell(root: Path, pack_path: Path) -> dict[str, object]:
    reference = ProjectedReferenceTable(
        root / "reference" / "ground_up_projected_reference_feature_table.npz"
    )
    observer = P30BridgeObserver(root / "observer" / "p30_actuator_fit.json")
    assembler = WinnerV2ObservationAssembler(reference)
    phase = WinnerV2PhaseClock()
    action_pipeline = WinnerV2ActionPipeline()
    metrics = {
        "observation": 0.0,
        "target_pre": 0.0,
        "sent_target": 0.0,
        "observer_next": 0.0,
        "applied_target": 0.0,
        "phase_before": 0.0,
        "phase_after": 0.0,
        "previous_action_contract": 0.0,
    }
    previous_action = np.zeros(ACTION_DIM, dtype=np.float32)
    with np.load(pack_path, allow_pickle=False) as pack:
        command_x = float(pack["command_raw"][0, 0])
        for tick in range(EXPECTED_TICKS_PER_CELL):
            arguments = _stage_arguments(pack, tick)
            observation = assembler.build(
                gyro_rad_s=arguments["gyro_rad_s"],
                acceleration_m_s2=arguments["acceleration_m_s2"],
                commands=arguments["commands"],
                positions_rad=arguments["positions_rad"],
                velocities_rad_s=arguments["velocities_rad_s"],
                observer_target_rad=observer.value_view,
                foot_contacts=arguments["foot_contacts"],
                phase=phase.value,
                phase_index=phase.index,
                servo_stale=arguments["servo_stale"],
                imu_stale=False,
                contacts_stale=False,
            )
            metrics["observation"] = max(
                metrics["observation"], _maximum_error(observation, pack["obs"][tick])
            )
            metrics["phase_before"] = max(
                metrics["phase_before"],
                _maximum_error(phase.value, pack["phase_before"][tick]),
            )
            metrics["previous_action_contract"] = max(
                metrics["previous_action_contract"],
                _maximum_error(previous_action, pack["previous_action_in"][tick]),
            )
            action = np.asarray(pack["final_action"][tick], dtype=np.float32)
            action_pipeline.stage(action, np.zeros(ACTION_DIM, dtype=np.float64))
            metrics["target_pre"] = max(
                metrics["target_pre"],
                _maximum_error(
                    action_pipeline.logical_target_rad,
                    pack["target_pre_runtime_rate_limit_rad"][tick],
                ),
            )
            metrics["sent_target"] = max(
                metrics["sent_target"],
                _maximum_error(
                    action_pipeline.logical_target_rad, pack["sent_target_rad"][tick]
                ),
            )
            observer.stage_confirmed_target(action_pipeline.logical_target_rad)
            action_pipeline.commit_staged()
            observer.commit_staged()
            assembler.commit_action(action)
            phase.advance_confirmed()
            np.copyto(previous_action, pack["previous_action_out"][tick])
            metrics["observer_next"] = max(
                metrics["observer_next"],
                _maximum_error(
                    observer.value_view, pack["observer_estimate_next_tick_rad"][tick]
                ),
            )
            metrics["applied_target"] = max(
                metrics["applied_target"],
                _maximum_error(observer.value_view, pack["applied_target_rad"][tick]),
            )
            metrics["phase_after"] = max(
                metrics["phase_after"],
                _maximum_error(phase.value, pack["phase_after"][tick]),
            )
    return {
        "golden_pack": pack_path.name,
        "golden_pack_sha256": sha256_file(pack_path),
        "command_x": command_x,
        "ticks": EXPECTED_TICKS_PER_CELL,
        "max_abs_error": metrics,
    }


def _verify_policy_chain(policy_path: Path, pack_path: Path) -> dict[str, object]:
    policy = WinnerV2OnnxPolicy(
        policy_path,
        allow_audit_policy=policy_path.name == "T2_EQUAL_1024000.onnx",
    )
    metrics = {"action": 0.0, "state_in": 0.0, "state_out": 0.0}
    x0_bit_exact = True
    with np.load(pack_path, allow_pickle=False) as pack:
        command_x = float(pack["command_raw"][0, 0])
        for tick in range(EXPECTED_TICKS_PER_CELL):
            metrics["state_in"] = max(
                metrics["state_in"],
                _maximum_error(
                    policy.previous_action_view, pack["previous_action_in"][tick]
                ),
            )
            action = policy.stage(np.asarray(pack["obs"][tick], dtype=np.float32))
            metrics["action"] = max(
                metrics["action"], _maximum_error(action, pack["final_action"][tick])
            )
            metrics["state_out"] = max(
                metrics["state_out"],
                _maximum_error(
                    policy.staged_state_view, pack["previous_action_out"][tick]
                ),
            )
            if command_x == 0.0:
                x0_bit_exact = bool(
                    x0_bit_exact
                    and np.array_equal(action, np.zeros(ACTION_DIM, dtype=np.float32))
                    and np.array_equal(
                        policy.staged_state_view,
                        np.zeros(ACTION_DIM, dtype=np.float32),
                    )
                )
            policy.commit_staged()
    return {
        "policy": policy_path.name,
        "policy_sha256": sha256_file(policy_path),
        "golden_pack": pack_path.name,
        "command_x": command_x,
        "ticks": EXPECTED_TICKS_PER_CELL,
        "max_abs_error": metrics,
        "x0_action_and_state_bit_exact_zero": x0_bit_exact,
    }


def _verify_recursive_cell(
    root: Path,
    policy_path: Path,
    pack_path: Path,
    soft_offsets_rad: np.ndarray,
) -> dict[str, object]:
    transaction = _make_transaction(
        root,
        policy_path,
        allow_audit_policy=policy_path.name == "T2_EQUAL_1024000.onnx",
    )
    metrics = {
        "observation": 0.0,
        "action": 0.0,
        "state_in": 0.0,
        "state_out": 0.0,
        "target_pre": 0.0,
        "sent_target": 0.0,
        "observer_next": 0.0,
        "applied_target": 0.0,
        "phase_before": 0.0,
        "phase_after": 0.0,
    }
    x0_bit_exact = True
    target_error_by_joint = np.zeros(ACTION_DIM, dtype=np.float64)
    observer_error_by_joint = np.zeros(ACTION_DIM, dtype=np.float64)
    raw_error_by_joint = np.zeros(ACTION_DIM, dtype=np.int64)
    raw_runtime = np.zeros(ACTION_DIM, dtype=np.int64)
    raw_golden = np.zeros(ACTION_DIM, dtype=np.int64)
    raw_mismatch_count = 0
    first_raw_mismatch: dict[str, object] | None = None
    runtime_saturation_any = False
    runtime_rate_excess_any = False
    with np.load(pack_path, allow_pickle=False) as pack:
        _require(pack["obs"].shape == (600, 115), f"invalid obs shape in {pack_path.name}")
        _require(
            pack["final_action"].shape == (600, 14),
            f"invalid action shape in {pack_path.name}",
        )
        _require(
            not bool(np.any(pack["external_5p24_limiter_changed"])),
            f"golden pack records a changed 5.24 limiter: {pack_path.name}",
        )
        golden_saturation_any = bool(np.any(pack["action_saturated"]))
        golden_rate_excess_any = bool(
            np.any(pack["sent_target_rate_excess_rad_s"] > 0.0)
        )
        command_x = float(pack["command_raw"][0, 0])
        for tick in range(EXPECTED_TICKS_PER_CELL):
            _require(
                int(pack["tick"][tick]) == tick,
                f"non-contiguous golden tick in {pack_path.name}",
            )
            _require(
                int(pack["phase_index_before"][tick]) == transaction.phase.index,
                f"phase-index-before mismatch at {pack_path.name}:{tick}",
            )
            metrics["state_in"] = max(
                metrics["state_in"],
                _maximum_error(
                    transaction.policy.previous_action_view,
                    pack["previous_action_in"][tick],
                ),
            )
            metrics["phase_before"] = max(
                metrics["phase_before"],
                _maximum_error(transaction.phase.value, pack["phase_before"][tick]),
            )
            arguments = _stage_arguments(pack, tick)
            arguments["soft_offsets_rad"] = soft_offsets_rad
            transaction.stage_tick(**arguments)
            metrics["observation"] = max(
                metrics["observation"],
                _maximum_error(transaction.observation_view, pack["obs"][tick]),
            )
            metrics["action"] = max(
                metrics["action"],
                _maximum_error(
                    transaction.normalized_action_view, pack["final_action"][tick]
                ),
            )
            metrics["state_out"] = max(
                metrics["state_out"],
                _maximum_error(
                    transaction.policy.staged_state_view,
                    pack["previous_action_out"][tick],
                ),
            )
            metrics["target_pre"] = max(
                metrics["target_pre"],
                _maximum_error(
                    transaction.action_pipeline.logical_target_rad,
                    pack["target_pre_runtime_rate_limit_rad"][tick],
                ),
            )
            metrics["sent_target"] = max(
                metrics["sent_target"],
                _maximum_error(
                    transaction.action_pipeline.logical_target_rad,
                    pack["sent_target_rad"][tick],
                ),
            )
            target_error = np.abs(
                transaction.action_pipeline.logical_target_rad.astype(np.float64)
                - np.asarray(pack["sent_target_rad"][tick], dtype=np.float64)
            )
            np.maximum(target_error_by_joint, target_error, out=target_error_by_joint)
            runtime_saturation_any = bool(
                runtime_saturation_any
                or np.any(np.abs(transaction.normalized_action_view) >= 1.0)
            )
            runtime_rate_excess_any = bool(
                runtime_rate_excess_any
                or np.any(transaction.action_pipeline.graph_rate_excess_rad_s > 0.0)
            )
            golden_physical_target = (
                np.asarray(pack["sent_target_rad"][tick], dtype=np.float64)
                + soft_offsets_rad
            )
            for joint_index in range(ACTION_DIM):
                raw_runtime[joint_index] = rad_to_raw_position(
                    float(transaction.physical_target_view[joint_index])
                )
                raw_golden[joint_index] = rad_to_raw_position(
                    float(golden_physical_target[joint_index])
                )
                difference = abs(
                    int(raw_runtime[joint_index]) - int(raw_golden[joint_index])
                )
                raw_error_by_joint[joint_index] = max(
                    int(raw_error_by_joint[joint_index]), difference
                )
                if difference:
                    raw_mismatch_count += 1
                    if first_raw_mismatch is None:
                        first_raw_mismatch = {
                            "tick": tick,
                            "joint_index": joint_index,
                            "joint_name": JOINT_NAMES[joint_index],
                            "runtime_raw": int(raw_runtime[joint_index]),
                            "golden_raw": int(raw_golden[joint_index]),
                            "absolute_count_difference": difference,
                        }
            if command_x == 0.0:
                x0_bit_exact = bool(
                    x0_bit_exact
                    and np.array_equal(
                        transaction.normalized_action_view,
                        np.zeros(ACTION_DIM, dtype=np.float32),
                    )
                    and np.array_equal(
                        transaction.policy.staged_state_view,
                        np.zeros(ACTION_DIM, dtype=np.float32),
                    )
                    and np.array_equal(
                        transaction.action_pipeline.logical_target_rad,
                        pack["sent_target_rad"][tick],
                    )
                )
            transaction.complete_send(write_succeeded=True)
            observer_error = np.abs(
                transaction.observer.value_view.astype(np.float64)
                - np.asarray(
                    pack["observer_estimate_next_tick_rad"][tick], dtype=np.float64
                )
            )
            np.maximum(
                observer_error_by_joint,
                observer_error,
                out=observer_error_by_joint,
            )
            if command_x == 0.0:
                x0_bit_exact = bool(
                    x0_bit_exact
                    and np.array_equal(
                        transaction.observer.value_view,
                        pack["observer_estimate_next_tick_rad"][tick],
                    )
                )
            metrics["observer_next"] = max(
                metrics["observer_next"],
                _maximum_error(
                    transaction.observer.value_view,
                    pack["observer_estimate_next_tick_rad"][tick],
                ),
            )
            metrics["applied_target"] = max(
                metrics["applied_target"],
                _maximum_error(
                    transaction.observer.value_view,
                    pack["applied_target_rad"][tick],
                ),
            )
            metrics["phase_after"] = max(
                metrics["phase_after"],
                _maximum_error(transaction.phase.value, pack["phase_after"][tick]),
            )
            _require(
                int(pack["phase_index_after"][tick]) == transaction.phase.index,
                f"phase-index-after mismatch at {pack_path.name}:{tick}",
            )

    maximum_target_error_rad = float(target_error_by_joint.max())
    maximum_observer_error_rad = float(observer_error_by_joint.max())
    maximum_raw_error = int(raw_error_by_joint.max())
    classifications = {
        "golden_saturation_any": golden_saturation_any,
        "runtime_saturation_any": runtime_saturation_any,
        "saturation_unchanged": (
            runtime_saturation_any == golden_saturation_any
        ),
        "golden_rate_or_envelope_excess_any": golden_rate_excess_any,
        "runtime_rate_or_envelope_excess_any": runtime_rate_excess_any,
        "rate_and_envelope_unchanged": (
            runtime_rate_excess_any == golden_rate_excess_any
        ),
        "external_5p24_limiter_identity": True,
    }
    return {
        "policy": policy_path.name,
        "policy_sha256": sha256_file(policy_path),
        "golden_pack": pack_path.name,
        "golden_pack_sha256": sha256_file(pack_path),
        "command_x": command_x,
        "ticks": transaction.committed_ticks,
        "max_abs_error": metrics,
        "x0_action_and_state_bit_exact_zero": x0_bit_exact,
        "classifications": classifications,
        "native_resolution": {
            "sts_position_lsb_rad": STS_POSITION_LSB_RAD,
            "sts_half_lsb_rad": STS_HALF_LSB_RAD,
            "maximum_logical_target_error_rad": maximum_target_error_rad,
            "maximum_p30_observer_error_rad": maximum_observer_error_rad,
            "maximum_target_error_sts_counts": (
                maximum_target_error_rad / STS_POSITION_LSB_RAD
            ),
            "maximum_raw_goal_absolute_count_difference": maximum_raw_error,
            "raw_goal_mismatch_count": raw_mismatch_count,
            "first_raw_goal_mismatch": first_raw_mismatch,
            "raw_goal_in_signed_multiturn_range": True,
            "logical_target_error_by_joint_rad": {
                name: float(target_error_by_joint[index])
                for index, name in enumerate(JOINT_NAMES)
            },
            "p30_observer_error_by_joint_rad": {
                name: float(observer_error_by_joint[index])
                for index, name in enumerate(JOINT_NAMES)
            },
            "raw_goal_error_by_joint_counts": {
                name: int(raw_error_by_joint[index])
                for index, name in enumerate(JOINT_NAMES)
            },
        },
    }


def verify_handoff(root: Path, *, runtime_root: Path | None = None) -> dict[str, object]:
    root = root.resolve()
    runtime_identity = _runtime_identity(runtime_root or Path.cwd())
    soft_offsets_rad = np.asarray(
        runtime_identity["soft_offsets_rad"], dtype=np.float64
    )
    manifest_result = _verify_manifest(root)
    policy_contract = _load_json(root / "policy_contract.json")
    observation_map = _load_json(root / "observation_map.json")
    _require(
        policy_contract.get("disposition") == "REQUIRES_REVIEWED_115_RUNTIME_V2",
        "unexpected handoff disposition",
    )
    _require(
        policy_contract.get("schema_version")
        == "winner_v2_rdkx5_native_handoff.v1.1",
        "winner-v2 package must use the corrected v1.1 schema",
    )
    _require(
        policy_contract.get("selected_onnx_sha256")
        == WINNER_V2_SELECTED_POLICY_SHA256
        and policy_contract.get("single_selected_deployment_checkpoint") == 512000,
        "winner-v2 package does not select the reviewed 512000 graph",
    )
    authority = policy_contract.get("authority", {})
    _require(
        isinstance(authority, dict)
        and authority.get("robot_clearance") is False
        and authority.get("gate5") is False,
        "corrected handoff authority must remain false",
    )
    slices = observation_map.get("slices")
    _require(isinstance(slices, list), "observation-map slices are missing")
    history_by_start = {
        item.get("start"): item
        for item in slices
        if isinstance(item, dict) and item.get("start") in (41, 55, 69)
    }
    expected_history = {
        41: (55, "final_action_t_minus_2", "two-tick history"),
        55: (69, "final_action_t_minus_3", "three-tick history"),
        69: (83, "final_action_t_minus_4", "four-tick history"),
    }
    for start, (end, name, delay_filter) in expected_history.items():
        item = history_by_start.get(start, {})
        _require(
            item.get("end_exclusive") == end
            and item.get("name") == name
            and item.get("delay_filter") == delay_filter,
            f"uncorrected action-history metadata at obs[{start}:{end}]",
        )

    selected_path = root / "policies" / "T2_EQUAL_512000.onnx"
    _require(
        sha256_file(selected_path) == WINNER_V2_SELECTED_POLICY_SHA256,
        "selected policy relay does not match the reviewed 512000 graph",
    )

    semantic_cells: list[dict[str, object]] = []
    policy_cells: list[dict[str, object]] = []
    recursive_cells: list[dict[str, object]] = []
    for step in (512000, 1024000):
        policy_path = root / "policies" / f"T2_EQUAL_{step}.onnx"
        for command in (0.0, 0.08):
            pack_path = root / "golden" / f"T2_EQUAL_{step}_x{command:.3f}.npz"
            semantic_cells.append(_verify_semantic_cell(root, pack_path))
            policy_cells.append(_verify_policy_chain(policy_path, pack_path))
            recursive_cells.append(
                _verify_recursive_cell(
                    root,
                    policy_path,
                    pack_path,
                    soft_offsets_rad,
                )
            )
    _require(len(semantic_cells) == EXPECTED_CELLS, "expected four golden cells")
    total_ticks = sum(int(cell["ticks"]) for cell in recursive_cells)
    semantic_max_error = max(
        float(value)
        for cell in semantic_cells
        for value in cell["max_abs_error"].values()
    )
    policy_max_error = max(
        float(value)
        for cell in policy_cells
        for value in cell["max_abs_error"].values()
    )
    recursive_max_error = max(
        float(value)
        for cell in recursive_cells
        for value in cell["max_abs_error"].values()
    )
    selected_recursive_max_error = max(
        float(value)
        for cell in recursive_cells
        if cell["policy_sha256"] == WINNER_V2_SELECTED_POLICY_SHA256
        for value in cell["max_abs_error"].values()
    )
    audit_recursive_max_error = max(
        float(value)
        for cell in recursive_cells
        if cell["policy_sha256"] != WINNER_V2_SELECTED_POLICY_SHA256
        for value in cell["max_abs_error"].values()
    )
    direct_x0_exact = all(
        bool(cell["x0_action_and_state_bit_exact_zero"])
        for cell in policy_cells
        if float(cell["command_x"]) == 0.0
    )
    recursive_x0_exact = all(
        bool(cell["x0_action_and_state_bit_exact_zero"])
        for cell in recursive_cells
        if cell["policy_sha256"] == WINNER_V2_SELECTED_POLICY_SHA256
        and float(cell["command_x"]) == 0.0
    )
    first_policy = root / "policies" / "T2_EQUAL_512000.onnx"
    first_pack = root / "golden" / "T2_EQUAL_512000_x0.000.npz"
    fault_injection = _fault_injection(root, first_policy, first_pack)
    faults_pass = all(fault_injection.values())
    component_passed = (
        total_ticks == EXPECTED_CELLS * EXPECTED_TICKS_PER_CELL
        and semantic_max_error <= TOLERANCE
        and policy_max_error <= TOLERANCE
        and direct_x0_exact
        and faults_pass
    )
    selected_recursive_cells = [
        cell
        for cell in recursive_cells
        if cell["policy_sha256"] == WINNER_V2_SELECTED_POLICY_SHA256
    ]
    selected_target_error_rad = max(
        float(cell["native_resolution"]["maximum_logical_target_error_rad"])
        for cell in selected_recursive_cells
    )
    selected_observer_error_rad = max(
        float(cell["native_resolution"]["maximum_p30_observer_error_rad"])
        for cell in selected_recursive_cells
    )
    selected_raw_error_counts = max(
        int(cell["native_resolution"]["maximum_raw_goal_absolute_count_difference"])
        for cell in selected_recursive_cells
    )
    selected_raw_mismatch_count = sum(
        int(cell["native_resolution"]["raw_goal_mismatch_count"])
        for cell in selected_recursive_cells
    )
    selected_classifications_unchanged = all(
        bool(cell["classifications"]["saturation_unchanged"])
        and bool(cell["classifications"]["rate_and_envelope_unchanged"])
        and bool(cell["classifications"]["external_5p24_limiter_identity"])
        for cell in selected_recursive_cells
    )
    selected_raw_range_valid = all(
        bool(cell["native_resolution"]["raw_goal_in_signed_multiturn_range"])
        for cell in selected_recursive_cells
    )
    status, recursive_passed = native_resolution_decision(
        component_passed=component_passed,
        recursive_x0_exact=recursive_x0_exact,
        target_error_rad=selected_target_error_rad,
        observer_error_rad=selected_observer_error_rad,
        raw_error_counts=selected_raw_error_counts,
        raw_mismatch_count=selected_raw_mismatch_count,
        classifications_unchanged=selected_classifications_unchanged,
        raw_range_valid=selected_raw_range_valid,
    )
    remaining_blockers = [
        "completed powered-off direct-reaction torso COM packet",
        "policy-side robot_clearance=true decision",
        "reviewed frozen runtime/policy/config asset set",
        "X5 CPU-only replay under this same frozen native-resolution metric",
    ]
    if not recursive_passed:
        remaining_blockers.insert(
            0, "selected graph failed the frozen recursive native-resolution gate"
        )
    return {
        "schema_version": "open_duck_x5.winner_v2_offline_verification.v2",
        "status": status,
        "overall_disposition": "BLOCKED_FOR_COM_CLEARANCE_AND_X5_CPU_PREFLIGHT",
        "environment": _environment(),
        "runtime_identity": runtime_identity,
        "artifact_root_name": root.name,
        "manifest_sha256": manifest_result["manifest_sha256"],
        "manifest_files_checked": manifest_result["files_checked"],
        "history_metadata_correction": {
            "commit": WINNER_V2_HANDOFF_CORRECTION_COMMIT,
            "schema_version": policy_contract["schema_version"],
            "passed": True,
        },
        "selected_policy": {
            "checkpoint_step": 512000,
            "sha256": WINNER_V2_SELECTED_POLICY_SHA256,
            "selection_evidence_commit": WINNER_V2_POLICY_SELECTION_EVIDENCE_COMMIT,
            "selection_result_sha256": WINNER_V2_POLICY_SELECTION_RESULT_SHA256,
        },
        "recursive_preregistration": {
            "commit": RECURSIVE_PREREGISTRATION_COMMIT,
            "formal_prior_runtime_outcome_weight": False,
            "direct_same_input_tolerance": TOLERANCE,
            "sts_position_counts_per_revolution": (
                STS_POSITION_COUNTS_PER_REVOLUTION
            ),
            "sts_position_lsb_rad": STS_POSITION_LSB_RAD,
            "sts_half_lsb_rad": STS_HALF_LSB_RAD,
            "raw_goal_max_abs_count_difference": MAX_RAW_GOAL_DIFFERENCE,
        },
        "semantic_cells": semantic_cells,
        "policy_chain_cells": policy_cells,
        "recursive_runtime_cells": recursive_cells,
        "ticks": total_ticks,
        "tolerance": TOLERANCE,
        "semantic_max_abs_error": semantic_max_error,
        "policy_chain_max_abs_error": policy_max_error,
        "recursive_runtime_max_abs_error": recursive_max_error,
        "selected_recursive_runtime_max_abs_error": selected_recursive_max_error,
        "audit_recursive_runtime_max_abs_error": audit_recursive_max_error,
        "component_contract_passed": component_passed,
        "recursive_numeric_closure_passed": recursive_passed,
        "direct_x0_action_and_state_bit_exact_zero": direct_x0_exact,
        "recursive_x0_action_state_target_observer_bit_exact": recursive_x0_exact,
        "native_resolution_gate": {
            "selected_logical_target_max_abs_error_rad": selected_target_error_rad,
            "selected_p30_observer_max_abs_error_rad": selected_observer_error_rad,
            "selected_raw_goal_max_abs_count_difference": (
                selected_raw_error_counts
            ),
            "selected_raw_goal_mismatch_count": selected_raw_mismatch_count,
            "selected_classifications_unchanged": (
                selected_classifications_unchanged
            ),
            "selected_raw_goal_range_valid": selected_raw_range_valid,
            "selected_normalized_action_state_max_abs_error_record_only": (
                selected_recursive_max_error
            ),
            "audit_checkpoint_is_non_gating": True,
        },
        "fault_injection": fault_injection,
        "authority": {
            "cpu_only": True,
            "robot_access": False,
            "runtime_deployment": False,
            "gate5": False,
            "robot_clearance": False,
        },
        "remaining_blockers": remaining_blockers,
    }


def reduce_recursive_result(
    result: dict[str, object], *, full_result_sha256: str
) -> dict[str, object]:
    environment = dict(result["environment"])
    semantic_cells = list(result["semantic_cells"])
    policy_cells = list(result["policy_chain_cells"])
    recursive_cells = list(result["recursive_runtime_cells"])
    _require(
        len(semantic_cells) == len(policy_cells) == len(recursive_cells) == EXPECTED_CELLS,
        "full result does not contain the four aligned cells required for reduction",
    )
    cells: list[dict[str, object]] = []
    for semantic_cell, policy_cell, recursive_cell in zip(
        semantic_cells, policy_cells, recursive_cells, strict=True
    ):
        semantic = dict(semantic_cell)
        policy = dict(policy_cell)
        recursive = dict(recursive_cell)
        semantic_error = dict(semantic["max_abs_error"])
        same_input_error = dict(policy["max_abs_error"])
        recursive_error = dict(recursive["max_abs_error"])
        native = dict(recursive["native_resolution"])
        classifications = dict(recursive["classifications"])
        command_x = float(recursive["command_x"])
        gating = recursive["policy_sha256"] == WINNER_V2_SELECTED_POLICY_SHA256
        x0_required = command_x == 0.0
        gates = {
            "ticks_600_exact": int(recursive["ticks"]) == EXPECTED_TICKS_PER_CELL,
            "teacher_forced_observation_exact_zero": (
                float(semantic_error["observation"]) == 0.0
            ),
            "same_input_action_at_most_1e_6": (
                float(same_input_error["action"]) <= TOLERANCE
            ),
            "same_input_state_at_most_1e_6": max(
                float(same_input_error["state_in"]),
                float(same_input_error["state_out"]),
            )
            <= TOLERANCE,
            "logical_target_within_half_sts_lsb": (
                float(native["maximum_logical_target_error_rad"])
                <= STS_HALF_LSB_RAD
            ),
            "p30_within_half_sts_lsb": (
                float(native["maximum_p30_observer_error_rad"])
                <= STS_HALF_LSB_RAD
            ),
            "raw_goal_within_one_count": (
                int(native["maximum_raw_goal_absolute_count_difference"])
                <= MAX_RAW_GOAL_DIFFERENCE
            ),
            "raw_goal_range_valid": bool(native["raw_goal_in_signed_multiturn_range"]),
            "saturation_classification_unchanged": bool(
                classifications["saturation_unchanged"]
            ),
            "rate_and_envelope_classification_unchanged": bool(
                classifications["rate_and_envelope_unchanged"]
            ),
            "external_5p24_limiter_identity": bool(
                classifications["external_5p24_limiter_identity"]
            ),
            "x0_action_state_target_p30_bit_exact": (
                not x0_required
                or bool(recursive["x0_action_and_state_bit_exact_zero"])
            ),
        }
        cells.append(
            {
                "policy": recursive["policy"],
                "policy_sha256": recursive["policy_sha256"],
                "golden_pack": recursive["golden_pack"],
                "golden_pack_sha256": recursive["golden_pack_sha256"],
                "command_x": command_x,
                "gating": gating,
                "role": "SELECTED_GATING" if gating else "AUDIT_ONLY_NON_GATING",
                "platform": environment["platform"],
                "python": environment["python"],
                "onnxruntime": environment["onnxruntime"],
                "onnx_execution_provider": environment["onnx_execution_provider"],
                "ticks": int(recursive["ticks"]),
                "semantic_gates": gates,
                "all_cell_gates_passed": all(gates.values()),
                "same_input_max_abs_error": same_input_error,
                "semantic_max_abs_error": semantic_error,
                "recursive_max_abs_error": {
                    "normalized_action": recursive_error["action"],
                    "normalized_state_in": recursive_error["state_in"],
                    "normalized_state_out": recursive_error["state_out"],
                    "observation": recursive_error["observation"],
                    "logical_target_rad": recursive_error["sent_target"],
                    "p30_observer_rad": recursive_error["observer_next"],
                },
                "per_joint_max_abs_error": {
                    "logical_target_rad": native[
                        "logical_target_error_by_joint_rad"
                    ],
                    "p30_observer_rad": native[
                        "p30_observer_error_by_joint_rad"
                    ],
                    "raw_goal_counts": native["raw_goal_error_by_joint_counts"],
                },
                "raw_goal_mismatch_count": native["raw_goal_mismatch_count"],
                "raw_goal_max_abs_count_difference": native[
                    "maximum_raw_goal_absolute_count_difference"
                ],
                "first_raw_goal_mismatch": native["first_raw_goal_mismatch"],
                "classifications": classifications,
            }
        )
    return {
        "schema_version": "open_duck_x5.winner_v2_recursive_closure_reduced.v1",
        "status": result["status"],
        "overall_disposition": result["overall_disposition"],
        "formal_full_result_sha256": full_result_sha256,
        "formal_full_result_schema_version": result["schema_version"],
        "recursive_preregistration": result["recursive_preregistration"],
        "decision_inputs": {
            "component_contract_passed": result["component_contract_passed"],
            "recursive_x0_action_state_target_observer_bit_exact": result[
                "recursive_x0_action_state_target_observer_bit_exact"
            ],
            "native_resolution_gate": result["native_resolution_gate"],
        },
        "runtime_identity": result["runtime_identity"],
        "selected_policy": result["selected_policy"],
        "history_metadata_correction": result["history_metadata_correction"],
        "manifest_sha256": result["manifest_sha256"],
        "cells": cells,
        "authority": result["authority"],
        "remaining_blockers": result["remaining_blockers"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the reviewed winner-v2 handoff through all 2,400 CPU ticks"
    )
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--reduced-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = verify_handoff(args.artifact_root, runtime_root=args.runtime_root)
    except (OSError, RuntimeError, ValueError, WinnerV2ContractError) as exc:
        print(f"winner-v2 verification failed: {exc}")
        return 2
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    full_result_sha256 = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    if args.reduced_output is not None:
        reduced = reduce_recursive_result(
            result,
            full_result_sha256=full_result_sha256,
        )
        reduced_payload = json.dumps(reduced, indent=2, sort_keys=True) + "\n"
        args.reduced_output.parent.mkdir(parents=True, exist_ok=True)
        args.reduced_output.write_text(
            reduced_payload,
            encoding="utf-8",
            newline="\n",
        )
    print(payload, end="")
    return 0 if str(result["status"]).startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
