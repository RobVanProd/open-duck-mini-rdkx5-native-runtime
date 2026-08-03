#!/usr/bin/env python3
"""Verify the preregistered T247 transaction-residual correction."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from open_duck_x5.constants import ACTION_DIM, CONTROL_PERIOD_NS  # noqa: E402
from open_duck_x5.winner_v13_state_coherent import (  # noqa: E402
    CALIBRATION_TICKS,
    WinnerV13StateCoherentTransaction,
)
from tools.run_winner_v14_x5_paced_screen import samples, stage  # noqa: E402
from tools.verify_winner_v15_graph_host_optimized import (  # noqa: E402
    build_host,
    canonical_sha256,
    exact_pairs,
    receipt,
    summary_ns,
)
from tools.winner_v16_target_optimized import (  # noqa: E402
    WinnerV16TargetOptimizedTransaction,
)
from tools.winner_v18_transaction_optimized import (  # noqa: E402
    WinnerV18TransactionOptimizedTransaction,
)

PREREGISTRATION = (
    ROOT
    / "artifacts"
    / "gates"
    / "phase_5_policy"
    / "t251a7_transaction_residual_correction_preregistration_20260731.json"
)
LOCOMOTION_TICKS = 2_048
MICROBENCHMARK_SAMPLES = 20_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibrator", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--p30-fit", type=Path, required=True)
    parser.add_argument("--reference-table", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def bind_inputs(
    host: WinnerV18TransactionOptimizedTransaction,
    sample: dict[str, Any],
) -> None:
    host.bind_tick_inputs(
        gyro_rad_s=sample["gyro_rad_s"],
        acceleration_m_s2=sample["acceleration_m_s2"],
        commands=sample["commands"],
        positions_rad=sample["positions_rad"],
        velocities_rad_s=sample["velocities_rad_s"],
        foot_contacts=sample["foot_contacts"],
        servo_stale=sample["servo_stale"],
        soft_offsets_rad=sample["soft_offsets_rad"],
    )


def stage_bound(
    host: WinnerV18TransactionOptimizedTransaction,
    tick: object,
    sample: dict[str, Any],
    *,
    servo_tick: object | None = None,
    imu_tick: object | None = None,
    contacts_tick: object | None = None,
) -> np.ndarray:
    selected_servo_tick = tick if servo_tick is None else servo_tick
    selected_imu_tick = tick if imu_tick is None else imu_tick
    selected_contacts_tick = tick if contacts_tick is None else contacts_tick
    return host.stage_bound_tick(
        tick,  # type: ignore[arg-type]
        selected_servo_tick,  # type: ignore[arg-type]
        selected_imu_tick,  # type: ignore[arg-type]
        selected_contacts_tick,  # type: ignore[arg-type]
        sample["imu_stale"],
        sample["contacts_stale"],
    )


def stage_predecessor(
    host: WinnerV16TargetOptimizedTransaction,
    tick: object,
    sample: dict[str, Any],
    *,
    servo_tick: object | None = None,
    imu_tick: object | None = None,
    contacts_tick: object | None = None,
) -> np.ndarray:
    selected_servo_tick = tick if servo_tick is None else servo_tick
    selected_imu_tick = tick if imu_tick is None else imu_tick
    selected_contacts_tick = tick if contacts_tick is None else contacts_tick
    return host.stage_tick(
        tick_index=tick,  # type: ignore[arg-type]
        logical_period_ns=CONTROL_PERIOD_NS,
        servo_sample_tick_index=selected_servo_tick,  # type: ignore[arg-type]
        imu_sample_tick_index=selected_imu_tick,  # type: ignore[arg-type]
        contacts_sample_tick_index=selected_contacts_tick,  # type: ignore[arg-type]
        **sample,
    )


def first_mismatch(
    predecessor: WinnerV13StateCoherentTransaction,
    corrected: WinnerV13StateCoherentTransaction,
) -> dict[str, Any] | None:
    pairs = list(exact_pairs(predecessor, corrected))
    pairs.extend(
        (
            (
                "desired_target",
                predecessor.target_pipeline.desired_logical_target_rad,
                corrected.target_pipeline.desired_logical_target_rad,
            ),
            (
                "implied_velocity",
                predecessor.target_pipeline.implied_velocity_rad_s,
                corrected.target_pipeline.implied_velocity_rad_s,
            ),
            (
                "rate_excess",
                predecessor.target_pipeline.graph_rate_excess_rad_s,
                corrected.target_pipeline.graph_rate_excess_rad_s,
            ),
            (
                "deferred_action",
                predecessor.assembler._deferred_action,
                corrected.assembler._deferred_action,
            ),
        )
    )
    for name, expected, actual in pairs:
        if not np.array_equal(expected, actual):
            return {
                "field": name,
                "maximum_absolute_delta": float(np.max(np.abs(expected - actual))),
            }
    return None


def run_semantic_contract(
    paths: dict[str, Path], preregistration: dict[str, Any]
) -> dict[str, Any]:
    predecessor = build_host(
        WinnerV16TargetOptimizedTransaction,
        paths,
        preregistration,
    )
    corrected = build_host(
        WinnerV18TransactionOptimizedTransaction,
        paths,
        preregistration,
    )
    sample = samples(0.074)
    offsets = sample["soft_offsets_rad"]
    predecessor.bind_soft_offsets(offsets)
    corrected.bind_soft_offsets(offsets)
    bind_inputs(corrected, sample)
    total_ticks = CALIBRATION_TICKS + LOCOMOTION_TICKS
    predecessor_actions = np.zeros((total_ticks, ACTION_DIM), dtype=np.float32)
    corrected_actions = np.zeros((total_ticks, ACTION_DIM), dtype=np.float32)
    mismatch: dict[str, Any] | None = None
    handoff_switches = 0
    for tick in range(total_ticks):
        stage(predecessor, tick, sample)
        if tick < CALIBRATION_TICKS:
            stage(corrected, tick, sample)
        else:
            stage_bound(corrected, tick, sample)
        np.copyto(predecessor_actions[tick], predecessor.normalized_action_view)
        np.copyto(corrected_actions[tick], corrected.normalized_action_view)
        mismatch = first_mismatch(predecessor, corrected)
        if mismatch is not None:
            mismatch.update({"tick": tick, "boundary": "staged"})
            break
        predecessor.complete_send(write_succeeded=True)
        corrected.complete_send(write_succeeded=True)
        mismatch = first_mismatch(predecessor, corrected)
        if mismatch is not None:
            mismatch.update({"tick": tick, "boundary": "committed"})
            break
        if tick + 1 == CALIBRATION_TICKS:
            predecessor.confirm_calibration_handoff(True)
            corrected.confirm_calibration_handoff(True)
            handoff_switches += 1

    return {
        "calibration_ticks": corrected.confirmed_calibration_ticks,
        "locomotion_ticks": corrected.confirmed_locomotion_ticks,
        "handoff_switches": handoff_switches,
        "bound_live_sources_remain_writeable": all(
            sample[name].flags.writeable
            for name in (
                "gyro_rad_s",
                "acceleration_m_s2",
                "commands",
                "positions_rad",
                "velocities_rad_s",
                "foot_contacts",
                "servo_stale",
            )
        ),
        "bound_offsets_are_immutable": not offsets.flags.writeable,
        "mismatch": mismatch,
        "predecessor_action_trace_sha256": hashlib.sha256(
            predecessor_actions.tobytes()
        ).hexdigest(),
        "corrected_action_trace_sha256": hashlib.sha256(
            corrected_actions.tobytes()
        ).hexdigest(),
        "maximum_rate_excess_rad_s": float(
            np.max(corrected.target_pipeline.graph_rate_excess_rad_s)
        ),
    }


def exception_receipt(
    call: Callable[[], object],
    host: WinnerV13StateCoherentTransaction,
) -> dict[str, Any]:
    try:
        call()
    except Exception as exc:
        return {
            "type": type(exc).__name__,
            "message": str(exc),
            "faulted": host.faulted,
            "fault_reason": host.fault_reason,
            "pending": host.pending,
        }
    return {
        "type": None,
        "message": None,
        "faulted": host.faulted,
        "fault_reason": host.fault_reason,
        "pending": host.pending,
    }


def prepared_pair(
    paths: dict[str, Path],
    preregistration: dict[str, Any],
    *,
    handoff: bool,
) -> tuple[
    WinnerV16TargetOptimizedTransaction,
    WinnerV18TransactionOptimizedTransaction,
    dict[str, Any],
]:
    predecessor = build_host(
        WinnerV16TargetOptimizedTransaction,
        paths,
        preregistration,
    )
    corrected = build_host(
        WinnerV18TransactionOptimizedTransaction,
        paths,
        preregistration,
    )
    sample = samples(0.074)
    predecessor.bind_soft_offsets(sample["soft_offsets_rad"])
    corrected.bind_soft_offsets(sample["soft_offsets_rad"])
    bind_inputs(corrected, sample)
    for tick in range(CALIBRATION_TICKS):
        stage(predecessor, tick, sample)
        stage(corrected, tick, sample)
        predecessor.complete_send(write_succeeded=True)
        corrected.complete_send(write_succeeded=True)
    if handoff:
        predecessor.confirm_calibration_handoff(True)
        corrected.confirm_calibration_handoff(True)
    return predecessor, corrected, sample


def compare_calls(
    predecessor: WinnerV16TargetOptimizedTransaction,
    corrected: WinnerV18TransactionOptimizedTransaction,
    predecessor_call: Callable[[], object],
    corrected_call: Callable[[], object],
) -> dict[str, Any]:
    expected = exception_receipt(predecessor_call, predecessor)
    actual = exception_receipt(corrected_call, corrected)
    return {"expected": expected, "actual": actual, "exact": expected == actual}


def run_fallback_contract(
    paths: dict[str, Path], preregistration: dict[str, Any]
) -> dict[str, Any]:
    predecessor, corrected, sample = prepared_pair(
        paths,
        preregistration,
        handoff=False,
    )
    tick = CALIBRATION_TICKS
    cases: dict[str, Any] = {}
    cases["handoff_required"] = compare_calls(
        predecessor,
        corrected,
        lambda: stage_predecessor(predecessor, tick, sample),
        lambda: stage_bound(corrected, tick, sample),
    )
    predecessor.confirm_calibration_handoff(True)
    corrected.confirm_calibration_handoff(True)

    cases["tick_type"] = compare_calls(
        predecessor,
        corrected,
        lambda: stage_predecessor(predecessor, "250", sample),
        lambda: stage_bound(corrected, "250", sample),
    )
    cases["non_contiguous"] = compare_calls(
        predecessor,
        corrected,
        lambda: stage_predecessor(predecessor, tick + 1, sample),
        lambda: stage_bound(corrected, tick + 1, sample),
    )
    cases["mixed_epochs"] = compare_calls(
        predecessor,
        corrected,
        lambda: stage_predecessor(
            predecessor,
            tick,
            sample,
            servo_tick=tick - 1,
        ),
        lambda: stage_bound(
            corrected,
            tick,
            sample,
            servo_tick=tick - 1,
        ),
    )
    predecessor._enabled = False
    corrected._enabled = False
    cases["inactive"] = compare_calls(
        predecessor,
        corrected,
        lambda: stage_predecessor(predecessor, tick, sample),
        lambda: stage_bound(corrected, tick, sample),
    )
    predecessor._enabled = True
    corrected._enabled = True
    predecessor._faulted = True
    corrected._faulted = True
    predecessor._fault_reason = "injected prior fault"
    corrected._fault_reason = "injected prior fault"
    cases["faulted"] = compare_calls(
        predecessor,
        corrected,
        lambda: stage_predecessor(predecessor, tick, sample),
        lambda: stage_bound(corrected, tick, sample),
    )
    predecessor._faulted = False
    corrected._faulted = False
    predecessor._fault_reason = None
    corrected._fault_reason = None
    stage_predecessor(predecessor, tick, sample)
    stage_bound(corrected, tick, sample)
    cases["pending"] = compare_calls(
        predecessor,
        corrected,
        lambda: stage_predecessor(predecessor, tick, sample),
        lambda: stage_bound(corrected, tick, sample),
    )
    predecessor.discard_staged()
    corrected.discard_staged()
    return {
        "cases": cases,
        "all_exact": all(value["exact"] for value in cases.values()),
        "post_discard_mismatch": first_mismatch(predecessor, corrected),
    }


def run_fault_case(
    paths: dict[str, Path],
    preregistration: dict[str, Any],
    case: str,
) -> dict[str, Any]:
    predecessor, corrected, sample = prepared_pair(
        paths,
        preregistration,
        handoff=True,
    )
    tick = CALIBRATION_TICKS
    if case == "stale":
        sample["servo_stale"][0] = True
    elif case == "nonfinite":
        sample["commands"][0] = np.nan
    elif case == "graph":
        def fail_graph(_observation: np.ndarray) -> np.ndarray:
            raise RuntimeError("injected graph failure")

        predecessor._locomotion.stage = fail_graph  # type: ignore[method-assign]
        corrected._locomotion.stage = fail_graph  # type: ignore[method-assign]
    elif case == "target":
        def fail_target(
            _action: np.ndarray,
            _offsets: np.ndarray,
            *,
            mode: str,
        ) -> np.ndarray:
            raise RuntimeError(f"injected target failure in {mode}")

        predecessor.target_pipeline.stage = fail_target  # type: ignore[method-assign]
        corrected.target_pipeline.stage = fail_target  # type: ignore[method-assign]
    elif case == "observer":
        def fail_observer(_target: np.ndarray) -> None:
            raise RuntimeError("injected observer failure")

        predecessor.observer.stage_confirmed_target = fail_observer  # type: ignore[method-assign]
        corrected.observer.stage_confirmed_target = fail_observer  # type: ignore[method-assign]
    elif case == "send":
        stage_predecessor(predecessor, tick, sample)
        stage_bound(corrected, tick, sample)
        return compare_calls(
            predecessor,
            corrected,
            lambda: predecessor.complete_send(write_succeeded=False),
            lambda: corrected.complete_send(write_succeeded=False),
        )
    else:
        raise ValueError(case)
    return compare_calls(
        predecessor,
        corrected,
        lambda: stage_predecessor(predecessor, tick, sample),
        lambda: stage_bound(corrected, tick, sample),
    )


def run_fault_contract(
    paths: dict[str, Path], preregistration: dict[str, Any]
) -> dict[str, Any]:
    cases = {
        name: run_fault_case(paths, preregistration, name)
        for name in ("stale", "nonfinite", "graph", "target", "observer", "send")
    }
    return {
        "cases": cases,
        "all_exact": all(value["exact"] for value in cases.values()),
    }


def run_binding_contract(
    paths: dict[str, Path], preregistration: dict[str, Any]
) -> dict[str, Any]:
    host = build_host(
        WinnerV18TransactionOptimizedTransaction,
        paths,
        preregistration,
    )
    sample = samples(0.074)
    untrusted = exception_receipt(lambda: bind_inputs(host, sample), host)
    host.bind_soft_offsets(sample["soft_offsets_rad"])
    original = sample["gyro_rad_s"]
    sample["gyro_rad_s"] = np.zeros(3, dtype=np.float32)
    wrong_dtype = exception_receipt(lambda: bind_inputs(host, sample), host)
    sample["gyro_rad_s"] = original
    bind_inputs(host, sample)
    duplicate = exception_receipt(lambda: bind_inputs(host, sample), host)
    return {
        "untrusted_offset_rejected": untrusted["type"] is not None,
        "wrong_dtype_rejected": wrong_dtype["type"] is not None,
        "duplicate_binding_rejected": duplicate["type"] is not None,
        "live_inputs_remain_writeable": all(
            sample[name].flags.writeable
            for name in (
                "gyro_rad_s",
                "acceleration_m_s2",
                "commands",
                "positions_rad",
                "velocities_rad_s",
                "foot_contacts",
                "servo_stale",
            )
        ),
        "offset_identity_exact": host._bound_soft_offsets
        is host.target_pipeline._trusted_offsets,
        "offsets_immutable": not sample["soft_offsets_rad"].flags.writeable,
    }


def patch_transaction_components(
    host: WinnerV13StateCoherentTransaction,
    observation: np.ndarray,
    action: np.ndarray,
    physical_target: np.ndarray,
) -> None:
    def build(**_kwargs: object) -> np.ndarray:
        return observation

    def graph(_observation: np.ndarray) -> np.ndarray:
        return action

    def target(
        _action: np.ndarray,
        _offsets: np.ndarray,
        *,
        mode: str,
    ) -> np.ndarray:
        if mode != "locomotion":
            raise RuntimeError("microbenchmark entered the wrong stage")
        return physical_target

    def observer(_target: np.ndarray) -> None:
        return None

    host.assembler.build = build  # type: ignore[method-assign]
    host._locomotion.stage = graph  # type: ignore[method-assign]
    host.target_pipeline.stage = target  # type: ignore[method-assign]
    host.observer.stage_confirmed_target = observer  # type: ignore[method-assign]


def clear_benchmark_stage(host: WinnerV13StateCoherentTransaction) -> None:
    host._staged_stage = None
    host._staged_tick = None


def run_transaction_microbenchmark(
    paths: dict[str, Path], preregistration: dict[str, Any]
) -> dict[str, Any]:
    predecessor, corrected, sample = prepared_pair(
        paths,
        preregistration,
        handoff=True,
    )
    predecessor_observation = predecessor.observation_view
    corrected_observation = corrected.observation_view
    fixed_action = np.linspace(-0.03, 0.03, ACTION_DIM, dtype=np.float32)
    predecessor_target = np.linspace(-0.2, 0.2, ACTION_DIM, dtype=np.float64)
    corrected_target = predecessor_target.copy()
    patch_transaction_components(
        predecessor,
        predecessor_observation,
        fixed_action,
        predecessor_target,
    )
    patch_transaction_components(
        corrected,
        corrected_observation,
        fixed_action,
        corrected_target,
    )
    tick = CALIBRATION_TICKS
    for _ in range(1_000):
        stage_predecessor(predecessor, tick, sample)
        clear_benchmark_stage(predecessor)
        stage_bound(corrected, tick, sample)
        clear_benchmark_stage(corrected)
    predecessor_ns = np.empty(MICROBENCHMARK_SAMPLES, dtype=np.int64)
    corrected_ns = np.empty(MICROBENCHMARK_SAMPLES, dtype=np.int64)
    mismatch_tick: int | None = None
    for index in range(MICROBENCHMARK_SAMPLES):
        if index % 2 == 0:
            started = time.perf_counter_ns()
            expected = stage_predecessor(predecessor, tick, sample)
            predecessor_ns[index] = time.perf_counter_ns() - started
            clear_benchmark_stage(predecessor)
            started = time.perf_counter_ns()
            actual = stage_bound(corrected, tick, sample)
            corrected_ns[index] = time.perf_counter_ns() - started
            clear_benchmark_stage(corrected)
        else:
            started = time.perf_counter_ns()
            actual = stage_bound(corrected, tick, sample)
            corrected_ns[index] = time.perf_counter_ns() - started
            clear_benchmark_stage(corrected)
            started = time.perf_counter_ns()
            expected = stage_predecessor(predecessor, tick, sample)
            predecessor_ns[index] = time.perf_counter_ns() - started
            clear_benchmark_stage(predecessor)
        if not np.array_equal(expected, actual):
            mismatch_tick = index
            break
    predecessor_summary = summary_ns(predecessor_ns)
    corrected_summary = summary_ns(corrected_ns)
    median_ratio = float(corrected_summary["p50_ms"] / predecessor_summary["p50_ms"])
    return {
        "samples": MICROBENCHMARK_SAMPLES,
        "alternated_order": True,
        "component_methods_replaced_by_identical_preallocated_stubs": True,
        "mismatch_tick": mismatch_tick,
        "predecessor": predecessor_summary,
        "corrected": corrected_summary,
        "corrected_to_predecessor_median_ratio": median_ratio,
        "required_maximum_median_ratio": 0.75,
        "selection_weight": 1,
    }


def main() -> int:
    args = parse_args()
    preregistration = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    paths = {
        "calibrator": args.calibrator.resolve(),
        "policy": args.policy.resolve(),
        "p30_fit": args.p30_fit.resolve(),
        "reference_table": args.reference_table.resolve(),
    }
    assets = preregistration["unchanged_assets"]
    expected_hashes = {
        "calibrator": assets["calibrator_sha256"],
        "policy": assets["deployment_policy_sha256"],
        "p30_fit": assets["fixed_p30_runtime_observer_fit_sha256"],
        "reference_table": assets["projected_reference_table_sha256"],
    }
    asset_receipts = {name: receipt(path) for name, path in paths.items()}
    asset_hashes_exact = all(
        asset_receipts[name]["sha256"] == digest
        for name, digest in expected_hashes.items()
    )
    if not asset_hashes_exact:
        raise RuntimeError("T251A7 real-asset hash mismatch")

    source_paths = {
        "transaction": ROOT / "src/open_duck_x5/winner_v13_state_coherent.py",
        "predecessor_host": ROOT / "tools/winner_v16_target_optimized.py",
        "corrected_host": ROOT / "tools/winner_v18_transaction_optimized.py",
        "verifier": Path(__file__),
    }
    source_receipts = {name: receipt(path) for name, path in source_paths.items()}
    pinned_sources_exact = (
        source_receipts["transaction"]["sha256"]
        == preregistration["current_sources"]["transaction_source_sha256"]
        and source_receipts["predecessor_host"]["sha256"]
        == preregistration["current_sources"]["predecessor_source_sha256"]
    )

    semantic = run_semantic_contract(paths, preregistration)
    binding = run_binding_contract(paths, preregistration)
    fallback = run_fallback_contract(paths, preregistration)
    faults = run_fault_contract(paths, preregistration)
    benchmark = run_transaction_microbenchmark(paths, preregistration)
    checks = {
        "asset_hashes_exact": asset_hashes_exact,
        "pinned_predecessor_sources_exact": pinned_sources_exact,
        "all_ticks_byte_exact": semantic["mismatch"] is None,
        "exact_tick_counts": semantic["calibration_ticks"] == CALIBRATION_TICKS
        and semantic["locomotion_ticks"] == LOCOMOTION_TICKS,
        "exact_one_handoff": semantic["handoff_switches"] == 1,
        "live_sources_remain_writeable": semantic[
            "bound_live_sources_remain_writeable"
        ],
        "offsets_immutable": semantic["bound_offsets_are_immutable"],
        "action_traces_identical": semantic["predecessor_action_trace_sha256"]
        == semantic["corrected_action_trace_sha256"],
        "zero_rate_excess": semantic["maximum_rate_excess_rad_s"] == 0.0,
        "binding_contract_exact": all(binding.values()),
        "fallback_diagnostics_exact": fallback["all_exact"]
        and fallback["post_discard_mismatch"] is None,
        "fault_boundaries_exact": faults["all_exact"],
        "microbenchmark_outputs_exact": benchmark["mismatch_tick"] is None,
        "microbenchmark_median_improves_at_least_25_percent": benchmark[
            "corrected_to_predecessor_median_ratio"
        ]
        <= benchmark["required_maximum_median_ratio"],
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    result: dict[str, Any] = {
        "schema_version": "open_duck_x5.t251a7_transaction_cpu_contract_result.v1",
        "status": (
            "PASS_T251A7_TRANSACTION_CPU_CONTRACT"
            if not failed
            else "FAIL_T251A7_TRANSACTION_CPU_CONTRACT"
        ),
        "candidate_id": assets["candidate_id"],
        "deployment_policy_sha256": assets["deployment_policy_sha256"],
        "preregistration": receipt(PREREGISTRATION),
        "source_receipts": source_receipts,
        "asset_receipts": asset_receipts,
        "semantic_contract": semantic,
        "binding_contract": binding,
        "fallback_contract": fallback,
        "fault_contract": faults,
        "local_transaction_microbenchmark": benchmark,
        "checks": checks,
        "failed_checks": failed,
        "decision": (
            "EARN_T251A7_X5_SCREEN_PREREGISTRATION_ONLY"
            if not failed
            else "CLOSE_T251A7_WITHOUT_X5_EXECUTION"
        ),
        "authority": {
            "x5_execution": False,
            "robot_device_access": False,
            "torque": False,
            "motion": False,
            "policy_deployed": False,
            "t251b_earned": False,
            "gate5": False,
        },
    }
    result["result_sha256"] = canonical_sha256(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
