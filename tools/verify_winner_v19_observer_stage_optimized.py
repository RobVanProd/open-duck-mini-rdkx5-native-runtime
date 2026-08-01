#!/usr/bin/env python3
"""Verify the preregistered T247 observer-stage correction."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from open_duck_x5.constants import ACTION_DIM  # noqa: E402
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
from tools.winner_v19_observer_stage_optimized import (  # noqa: E402
    WinnerV19ObserverStageOptimizedTransaction,
)

PREREGISTRATION = (
    ROOT
    / "artifacts"
    / "gates"
    / "phase_5_policy"
    / "t251a8_observer_stage_correction_preregistration_20260731.json"
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


def observer_arrays(
    predecessor: WinnerV13StateCoherentTransaction,
    corrected: WinnerV13StateCoherentTransaction,
) -> tuple[tuple[str, np.ndarray, np.ndarray], ...]:
    pairs: list[tuple[str, np.ndarray, np.ndarray]] = [
        ("observer_value", predecessor.observer._value, corrected.observer._value),
        (
            "observer_staged_value",
            predecessor.observer._staged_value,
            corrected.observer._staged_value,
        ),
        (
            "observer_staged_target",
            predecessor.observer._staged_target,
            corrected.observer._staged_target,
        ),
    ]
    predecessor_history = predecessor.observer._history
    corrected_history = corrected.observer._history
    pairs.append(("observer_history", predecessor_history, corrected_history))
    return tuple(pairs)


def first_mismatch(
    predecessor: WinnerV13StateCoherentTransaction,
    corrected: WinnerV13StateCoherentTransaction,
) -> dict[str, Any] | None:
    pairs = (
        *exact_pairs(predecessor, corrected),
        *observer_arrays(predecessor, corrected),
    )
    for name, expected, actual in pairs:
        if not np.array_equal(expected, actual):
            return {
                "field": name,
                "maximum_absolute_delta": float(np.max(np.abs(expected - actual))),
            }
    if predecessor.observer.pending != corrected.observer.pending:
        return {"field": "observer_pending", "maximum_absolute_delta": 1.0}
    return None


def build_pair(
    paths: dict[str, Path], preregistration: dict[str, Any]
) -> tuple[
    WinnerV16TargetOptimizedTransaction,
    WinnerV19ObserverStageOptimizedTransaction,
    dict[str, Any],
]:
    predecessor = build_host(
        WinnerV16TargetOptimizedTransaction,
        paths,
        preregistration,
    )
    corrected = build_host(
        WinnerV19ObserverStageOptimizedTransaction,
        paths,
        preregistration,
    )
    sample = samples(0.074)
    predecessor.bind_soft_offsets(sample["soft_offsets_rad"])
    corrected.bind_soft_offsets(sample["soft_offsets_rad"])
    return predecessor, corrected, sample


def prepare_handoff(
    paths: dict[str, Path], preregistration: dict[str, Any]
) -> tuple[
    WinnerV16TargetOptimizedTransaction,
    WinnerV19ObserverStageOptimizedTransaction,
    dict[str, Any],
]:
    predecessor, corrected, sample = build_pair(paths, preregistration)
    for tick in range(CALIBRATION_TICKS):
        stage(predecessor, tick, sample)
        stage(corrected, tick, sample)
        predecessor.complete_send(write_succeeded=True)
        corrected.complete_send(write_succeeded=True)
    predecessor.confirm_calibration_handoff(True)
    corrected.confirm_calibration_handoff(True)
    return predecessor, corrected, sample


def run_semantic_contract(
    paths: dict[str, Path], preregistration: dict[str, Any]
) -> dict[str, Any]:
    predecessor, corrected, sample = build_pair(paths, preregistration)
    total_ticks = CALIBRATION_TICKS + LOCOMOTION_TICKS
    predecessor_actions = np.zeros((total_ticks, ACTION_DIM), dtype=np.float32)
    corrected_actions = np.zeros((total_ticks, ACTION_DIM), dtype=np.float32)
    mismatch: dict[str, Any] | None = None
    handoff_switches = 0
    calibration_used_slow_path = True
    target_identity_bound = False
    for tick in range(total_ticks):
        stage(predecessor, tick, sample)
        stage(corrected, tick, sample)
        if tick < CALIBRATION_TICKS:
            calibration_used_slow_path = calibration_used_slow_path and (
                corrected.observer._trusted_target is None
                and not corrected.observer._trusted_target_staged
            )
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
            target_identity_bound = corrected.observer._trusted_target is (
                corrected.target_pipeline.sent_logical_target_rad
            )
            handoff_switches += 1

    return {
        "calibration_ticks": corrected.confirmed_calibration_ticks,
        "locomotion_ticks": corrected.confirmed_locomotion_ticks,
        "handoff_switches": handoff_switches,
        "calibration_used_predecessor_observer_path": calibration_used_slow_path,
        "post_handoff_target_identity_bound": target_identity_bound,
        "private_staged_buffer_restored_after_commit": corrected.observer._staged_target
        is corrected.observer._private_staged_target,
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


def exception_receipt(call: Any, host: Any) -> dict[str, Any]:
    try:
        call()
    except Exception as exc:
        return {
            "type": type(exc).__name__,
            "message": str(exc),
            "faulted": host.faulted,
            "fault_reason": host.fault_reason,
            "pending": host.pending,
            "observer_pending": host.observer.pending,
        }
    return {
        "type": None,
        "message": None,
        "faulted": host.faulted,
        "fault_reason": host.fault_reason,
        "pending": host.pending,
        "observer_pending": host.observer.pending,
    }


def run_boundary_contract(
    paths: dict[str, Path], preregistration: dict[str, Any]
) -> dict[str, Any]:
    cases: dict[str, Any] = {}

    predecessor, corrected, _ = prepare_handoff(paths, preregistration)
    predecessor_source = predecessor.target_pipeline.sent_logical_target_rad.copy()
    corrected_source = corrected.target_pipeline.sent_logical_target_rad.copy()
    predecessor.observer.stage_confirmed_target(predecessor_source)
    corrected.observer.stage_confirmed_target(corrected_source)
    cases["substituted_source_slow_path"] = {
        "mismatch": first_mismatch(predecessor, corrected),
        "corrected_used_private_buffer": corrected.observer._staged_target
        is corrected.observer._private_staged_target,
    }
    predecessor.observer.discard_staged()
    corrected.observer.discard_staged()

    predecessor_target = predecessor.target_pipeline.sent_logical_target_rad
    corrected_target = corrected.target_pipeline.sent_logical_target_rad
    predecessor.observer.stage_confirmed_target(predecessor_target)
    corrected.observer.stage_confirmed_target(corrected_target)
    expected = exception_receipt(
        lambda: predecessor.observer.stage_confirmed_target(predecessor_target),
        predecessor,
    )
    actual = exception_receipt(
        lambda: corrected.observer.stage_confirmed_target(corrected_target),
        corrected,
    )
    cases["pending"] = {"expected": expected, "actual": actual, "exact": expected == actual}
    predecessor.observer.discard_staged()
    corrected.observer.discard_staged()
    cases["discard"] = {
        "mismatch": first_mismatch(predecessor, corrected),
        "corrected_private_buffer_restored": corrected.observer._staged_target
        is corrected.observer._private_staged_target,
    }

    predecessor, corrected, sample = prepare_handoff(paths, preregistration)
    predecessor.target_pipeline.sent_logical_target_rad[0] = np.nan
    corrected.target_pipeline.sent_logical_target_rad[0] = np.nan
    expected = exception_receipt(
        lambda: predecessor.observer.stage_confirmed_target(
            predecessor.target_pipeline.sent_logical_target_rad
        ),
        predecessor,
    )
    actual = exception_receipt(
        lambda: corrected.observer.stage_confirmed_target(
            corrected.target_pipeline.sent_logical_target_rad
        ),
        corrected,
    )
    cases["nonfinite"] = {"expected": expected, "actual": actual, "exact": expected == actual}

    predecessor, corrected, sample = prepare_handoff(paths, preregistration)
    tick = CALIBRATION_TICKS
    stage(predecessor, tick, sample)
    stage(corrected, tick, sample)
    expected = exception_receipt(
        lambda: predecessor.complete_send(write_succeeded=False), predecessor
    )
    actual = exception_receipt(
        lambda: corrected.complete_send(write_succeeded=False), corrected
    )
    cases["failed_send"] = {
        "expected": expected,
        "actual": actual,
        "exact": expected == actual,
        "corrected_private_buffer_restored": corrected.observer._staged_target
        is corrected.observer._private_staged_target,
    }

    all_exact = (
        cases["substituted_source_slow_path"]["mismatch"] is None
        and cases["substituted_source_slow_path"]["corrected_used_private_buffer"]
        and cases["pending"]["exact"]
        and cases["discard"]["mismatch"] is None
        and cases["discard"]["corrected_private_buffer_restored"]
        and cases["nonfinite"]["exact"]
        and cases["failed_send"]["exact"]
        and cases["failed_send"]["corrected_private_buffer_restored"]
    )
    return {"cases": cases, "all_exact": all_exact}


def run_observer_microbenchmarks(
    paths: dict[str, Path], preregistration: dict[str, Any]
) -> dict[str, Any]:
    predecessor, corrected, _ = prepare_handoff(paths, preregistration)
    predecessor_target = predecessor.target_pipeline.sent_logical_target_rad
    corrected_target = corrected.target_pipeline.sent_logical_target_rad

    for _ in range(1_000):
        predecessor.observer.stage_confirmed_target(predecessor_target)
        predecessor.observer.discard_staged()
        corrected.observer.stage_confirmed_target(corrected_target)
        corrected.observer.discard_staged()

    predecessor_stage_ns = np.empty(MICROBENCHMARK_SAMPLES, dtype=np.int64)
    corrected_stage_ns = np.empty(MICROBENCHMARK_SAMPLES, dtype=np.int64)
    stage_mismatch_tick: int | None = None
    for index in range(MICROBENCHMARK_SAMPLES):
        value = np.float32((index % 101) * 1.0e-5)
        predecessor_target[0] = value
        corrected_target[0] = value
        if index % 2 == 0:
            started = time.perf_counter_ns()
            predecessor.observer.stage_confirmed_target(predecessor_target)
            predecessor_stage_ns[index] = time.perf_counter_ns() - started
            started = time.perf_counter_ns()
            corrected.observer.stage_confirmed_target(corrected_target)
            corrected_stage_ns[index] = time.perf_counter_ns() - started
        else:
            started = time.perf_counter_ns()
            corrected.observer.stage_confirmed_target(corrected_target)
            corrected_stage_ns[index] = time.perf_counter_ns() - started
            started = time.perf_counter_ns()
            predecessor.observer.stage_confirmed_target(predecessor_target)
            predecessor_stage_ns[index] = time.perf_counter_ns() - started
        if not np.array_equal(
            predecessor.observer._staged_target,
            corrected.observer._staged_target,
        ):
            stage_mismatch_tick = index
            break
        predecessor.observer.discard_staged()
        corrected.observer.discard_staged()

    predecessor_stage = summary_ns(predecessor_stage_ns)
    corrected_stage = summary_ns(corrected_stage_ns)
    stage_ratio = float(corrected_stage["p50_ms"] / predecessor_stage["p50_ms"])

    predecessor_total_ns = np.empty(MICROBENCHMARK_SAMPLES, dtype=np.int64)
    corrected_total_ns = np.empty(MICROBENCHMARK_SAMPLES, dtype=np.int64)
    total_mismatch_tick: int | None = None
    for index in range(MICROBENCHMARK_SAMPLES):
        value = np.float32((index % 97) * -1.0e-5)
        predecessor_target[1] = value
        corrected_target[1] = value
        if index % 2 == 0:
            started = time.perf_counter_ns()
            predecessor.observer.stage_confirmed_target(predecessor_target)
            predecessor.observer.commit_staged()
            predecessor_total_ns[index] = time.perf_counter_ns() - started
            started = time.perf_counter_ns()
            corrected.observer.stage_confirmed_target(corrected_target)
            corrected.observer.commit_staged()
            corrected_total_ns[index] = time.perf_counter_ns() - started
        else:
            started = time.perf_counter_ns()
            corrected.observer.stage_confirmed_target(corrected_target)
            corrected.observer.commit_staged()
            corrected_total_ns[index] = time.perf_counter_ns() - started
            started = time.perf_counter_ns()
            predecessor.observer.stage_confirmed_target(predecessor_target)
            predecessor.observer.commit_staged()
            predecessor_total_ns[index] = time.perf_counter_ns() - started
        if not np.array_equal(predecessor.observer._value, corrected.observer._value):
            total_mismatch_tick = index
            break
        if not np.array_equal(predecessor.observer._history, corrected.observer._history):
            total_mismatch_tick = index
            break

    predecessor_total = summary_ns(predecessor_total_ns)
    corrected_total = summary_ns(corrected_total_ns)
    total_ratio = float(corrected_total["p50_ms"] / predecessor_total["p50_ms"])
    return {
        "stage_only": {
            "samples": MICROBENCHMARK_SAMPLES,
            "alternated_order": True,
            "mutated_trusted_target_in_place": True,
            "mismatch_tick": stage_mismatch_tick,
            "predecessor": predecessor_stage,
            "corrected": corrected_stage,
            "corrected_to_predecessor_median_ratio": stage_ratio,
            "required_maximum_median_ratio": 0.75,
            "selection_weight": 1,
        },
        "stage_plus_commit": {
            "samples": MICROBENCHMARK_SAMPLES,
            "alternated_order": True,
            "mismatch_tick": total_mismatch_tick,
            "predecessor": predecessor_total,
            "corrected": corrected_total,
            "corrected_to_predecessor_median_ratio": total_ratio,
            "required_maximum_median_ratio": 1.10,
            "selection_weight": 1,
        },
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
        raise RuntimeError("T251A8 real-asset hash mismatch")

    source_paths = {
        "observer": ROOT / "tools/winner_v14_optimized.py",
        "predecessor_host": ROOT / "tools/winner_v16_target_optimized.py",
        "corrected_host": ROOT / "tools/winner_v19_observer_stage_optimized.py",
        "verifier": Path(__file__),
    }
    source_receipts = {name: receipt(path) for name, path in source_paths.items()}
    pinned_sources_exact = (
        source_receipts["observer"]["sha256"]
        == preregistration["current_sources"]["observer_source_sha256"]
        and source_receipts["predecessor_host"]["sha256"]
        == preregistration["current_sources"]["predecessor_source_sha256"]
    )
    semantic = run_semantic_contract(paths, preregistration)
    boundaries = run_boundary_contract(paths, preregistration)
    benchmark = run_observer_microbenchmarks(paths, preregistration)
    stage_benchmark = benchmark["stage_only"]
    total_benchmark = benchmark["stage_plus_commit"]
    checks = {
        "asset_hashes_exact": asset_hashes_exact,
        "pinned_predecessor_sources_exact": pinned_sources_exact,
        "all_ticks_byte_exact": semantic["mismatch"] is None,
        "exact_tick_counts": semantic["calibration_ticks"] == CALIBRATION_TICKS
        and semantic["locomotion_ticks"] == LOCOMOTION_TICKS,
        "exact_one_handoff": semantic["handoff_switches"] == 1,
        "calibration_slow_path_exact": semantic[
            "calibration_used_predecessor_observer_path"
        ],
        "post_handoff_target_identity_exact": semantic[
            "post_handoff_target_identity_bound"
        ],
        "private_buffer_restored": semantic[
            "private_staged_buffer_restored_after_commit"
        ],
        "action_traces_identical": semantic["predecessor_action_trace_sha256"]
        == semantic["corrected_action_trace_sha256"],
        "zero_rate_excess": semantic["maximum_rate_excess_rad_s"] == 0.0,
        "boundary_contract_exact": boundaries["all_exact"],
        "stage_microbenchmark_outputs_exact": stage_benchmark["mismatch_tick"] is None,
        "stage_microbenchmark_median_improves_at_least_25_percent": stage_benchmark[
            "corrected_to_predecessor_median_ratio"
        ]
        <= stage_benchmark["required_maximum_median_ratio"],
        "stage_plus_commit_outputs_exact": total_benchmark["mismatch_tick"] is None,
        "stage_plus_commit_median_does_not_regress": total_benchmark[
            "corrected_to_predecessor_median_ratio"
        ]
        <= total_benchmark["required_maximum_median_ratio"],
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    result: dict[str, Any] = {
        "schema_version": "open_duck_x5.t251a8_observer_stage_cpu_contract_result.v1",
        "status": (
            "PASS_T251A8_OBSERVER_STAGE_CPU_CONTRACT"
            if not failed
            else "FAIL_T251A8_OBSERVER_STAGE_CPU_CONTRACT"
        ),
        "candidate_id": assets["candidate_id"],
        "deployment_policy_sha256": assets["deployment_policy_sha256"],
        "preregistration": receipt(PREREGISTRATION),
        "source_receipts": source_receipts,
        "asset_receipts": asset_receipts,
        "semantic_contract": semantic,
        "boundary_contract": boundaries,
        "local_observer_microbenchmarks": benchmark,
        "checks": checks,
        "failed_checks": failed,
        "decision": (
            "EARN_T251A8_X5_SCREEN_PREREGISTRATION_ONLY"
            if not failed
            else "CLOSE_T251A8_WITHOUT_X5_EXECUTION"
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
