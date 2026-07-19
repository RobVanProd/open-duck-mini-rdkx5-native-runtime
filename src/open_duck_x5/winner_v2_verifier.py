"""Offline 2,400-tick verifier for the reviewed winner-v2 handoff package."""

from __future__ import annotations

import argparse
import json
import platform
from contextlib import suppress
from importlib import metadata
from pathlib import Path
from typing import Any

import numpy as np

from .constants import ACTION_DIM, CONTROL_PERIOD_NS, HOME_RAD
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
            transaction.stage_tick(**_stage_arguments(pack, tick))
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
                )
            transaction.complete_send(write_succeeded=True)
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

    return {
        "policy": policy_path.name,
        "policy_sha256": sha256_file(policy_path),
        "golden_pack": pack_path.name,
        "golden_pack_sha256": sha256_file(pack_path),
        "command_x": command_x,
        "ticks": transaction.committed_ticks,
        "max_abs_error": metrics,
        "x0_action_and_state_bit_exact_zero": x0_bit_exact,
    }


def verify_handoff(root: Path) -> dict[str, object]:
    root = root.resolve()
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
            recursive_cells.append(_verify_recursive_cell(root, policy_path, pack_path))
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
    x0_exact = all(
        bool(cell["x0_action_and_state_bit_exact_zero"])
        for cell in policy_cells
        if float(cell["command_x"]) == 0.0
    )
    first_policy = root / "policies" / "T2_EQUAL_512000.onnx"
    first_pack = root / "golden" / "T2_EQUAL_512000_x0.000.npz"
    fault_injection = _fault_injection(root, first_policy, first_pack)
    faults_pass = all(fault_injection.values())
    component_passed = (
        total_ticks == EXPECTED_CELLS * EXPECTED_TICKS_PER_CELL
        and semantic_max_error <= TOLERANCE
        and policy_max_error <= TOLERANCE
        and x0_exact
        and faults_pass
    )
    recursive_passed = selected_recursive_max_error <= TOLERANCE
    passed = component_passed and recursive_passed
    if passed:
        status = "PASS_2400_TICK_OFFLINE_RUNTIME_V2_BLOCKED_FOR_COM_AND_CLEARANCE"
    elif component_passed:
        status = "HOLD_RECURSIVE_NUMERIC_CLOSURE_TOLERANCE_REVIEW"
    else:
        status = "FAIL_WINNER_V2_OFFLINE_VERIFICATION"
    return {
        "schema_version": "open_duck_x5.winner_v2_offline_verification.v1",
        "status": status,
        "environment": _environment(),
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
        "x0_action_and_state_bit_exact_zero": x0_exact,
        "fault_injection": fault_injection,
        "authority": {
            "cpu_only": True,
            "robot_access": False,
            "runtime_deployment": False,
            "gate5": False,
            "robot_clearance": False,
        },
        "remaining_blockers": [
            "reviewed tolerance/decision for recursive cross-CPU numeric closure",
            "completed powered-off direct-reaction torso COM packet",
            "policy-side robot_clearance=true decision",
            "reviewed frozen runtime/policy/config asset set",
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the reviewed winner-v2 handoff through all 2,400 CPU ticks"
    )
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = verify_handoff(args.artifact_root)
    except (OSError, RuntimeError, ValueError, WinnerV2ContractError) as exc:
        print(f"winner-v2 verification failed: {exc}")
        return 2
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    print(payload, end="")
    return 0 if str(result["status"]).startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
