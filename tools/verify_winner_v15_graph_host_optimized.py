#!/usr/bin/env python3
"""Verify the preregistered T251A4 graph-host correction on real assets."""

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
    GraphAsset,
    P30FitAsset,
    WinnerV13StateCoherentTransaction,
)
from tools.run_winner_v14_x5_paced_screen import (  # noqa: E402
    calibrator_spec,
    locomotion_spec,
    samples,
    stage,
)
from tools.winner_v14_optimized import WinnerV14X5OptimizedTransaction  # noqa: E402
from tools.winner_v15_graph_host_optimized import (  # noqa: E402
    WinnerV15GraphHostOptimizedTransaction,
)

PREREGISTRATION = (
    ROOT
    / "artifacts"
    / "gates"
    / "phase_5_policy"
    / "t251a4_graph_host_correction_preregistration_20260731.json"
)
EXPECTED_ACTION_TRACE_SHA256 = (
    "6af1f952d577ef1f4d67fd7d9896934fe42ddfaf7bd5252d6b3c5342ec820bd3"
)
LOCOMOTION_TICKS = 2_048


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def receipt(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": sha256(resolved),
    }


def summary_ns(values: np.ndarray) -> dict[str, float | int]:
    milliseconds = values.astype(np.float64) / 1_000_000.0
    return {
        "samples": int(milliseconds.size),
        "min_ms": float(np.min(milliseconds)),
        "mean_ms": float(np.mean(milliseconds)),
        "p50_ms": float(np.percentile(milliseconds, 50)),
        "p95_ms": float(np.percentile(milliseconds, 95)),
        "p99_ms": float(np.percentile(milliseconds, 99)),
        "p99_9_ms": float(np.percentile(milliseconds, 99.9)),
        "max_ms": float(np.max(milliseconds)),
        "selection_weight": 0,
    }


def build_host(
    host_type: type[WinnerV13StateCoherentTransaction],
    paths: dict[str, Path],
    preregistration: dict[str, Any],
) -> WinnerV13StateCoherentTransaction:
    assets = preregistration["unchanged_assets"]
    return host_type(
        calibrator=GraphAsset(
            paths["calibrator"],
            calibrator_spec(),
            frozenset({assets["calibrator_sha256"]}),
        ),
        locomotion=GraphAsset(
            paths["policy"],
            locomotion_spec(),
            frozenset({assets["deployment_policy_sha256"]}),
        ),
        p30_fit=P30FitAsset(
            paths["p30_fit"],
            frozenset({assets["fixed_p30_runtime_observer_fit_sha256"]}),
        ),
        reference_table_path=paths["reference_table"],
        enabled=True,
        warmup_runs=3,
    )


def exact_pairs(
    baseline: WinnerV13StateCoherentTransaction,
    corrected: WinnerV13StateCoherentTransaction,
) -> tuple[tuple[str, np.ndarray, np.ndarray], ...]:
    return (
        ("observation", baseline.observation_view, corrected.observation_view),
        ("action", baseline.normalized_action_view, corrected.normalized_action_view),
        ("logical_target", baseline.logical_target_view, corrected.logical_target_view),
        ("physical_target", baseline.physical_target_view, corrected.physical_target_view),
        ("observer", baseline.observer.value_view, corrected.observer.value_view),
        ("assembler_last", baseline.assembler.last_action, corrected.assembler.last_action),
        (
            "assembler_minus_2",
            baseline.assembler.action_minus_2,
            corrected.assembler.action_minus_2,
        ),
        (
            "assembler_minus_3",
            baseline.assembler.action_minus_3,
            corrected.assembler.action_minus_3,
        ),
        (
            "calibrator_previous",
            baseline._calibrator._previous_action,
            corrected._calibrator._previous_action,
        ),
        (
            "calibrator_hidden",
            baseline._calibrator._hidden_in,
            corrected._calibrator._hidden_in,
        ),
        (
            "calibrator_previous_out",
            baseline._calibrator._previous_action_out,
            corrected._calibrator._previous_action_out,
        ),
        (
            "calibrator_hidden_out",
            baseline._calibrator._hidden_out,
            corrected._calibrator._hidden_out,
        ),
        (
            "locomotion_previous",
            baseline._locomotion._previous_action,
            corrected._locomotion._previous_action,
        ),
        (
            "locomotion_hidden",
            baseline._locomotion._hidden_in,
            corrected._locomotion._hidden_in,
        ),
        (
            "locomotion_previous_out",
            baseline._locomotion._previous_action_out,
            corrected._locomotion._previous_action_out,
        ),
        (
            "locomotion_hidden_out",
            baseline._locomotion._hidden_out,
            corrected._locomotion._hidden_out,
        ),
    )


def first_mismatch(
    baseline: WinnerV13StateCoherentTransaction,
    corrected: WinnerV13StateCoherentTransaction,
) -> dict[str, Any] | None:
    for name, expected, actual in exact_pairs(baseline, corrected):
        if not np.array_equal(expected, actual):
            return {
                "field": name,
                "maximum_absolute_delta": float(np.max(np.abs(expected - actual))),
            }
    return None


def run_semantic_contract(
    paths: dict[str, Path], preregistration: dict[str, Any]
) -> dict[str, Any]:
    baseline = build_host(WinnerV14X5OptimizedTransaction, paths, preregistration)
    corrected = build_host(WinnerV15GraphHostOptimizedTransaction, paths, preregistration)
    sample = samples(0.074)
    total_ticks = CALIBRATION_TICKS + LOCOMOTION_TICKS
    baseline_actions = np.empty((total_ticks, ACTION_DIM), dtype=np.float32)
    corrected_actions = np.empty((total_ticks, ACTION_DIM), dtype=np.float32)
    mismatch: dict[str, Any] | None = None
    handoff_switches = 0

    if not np.shares_memory(
        corrected.assembler.observation,
        corrected._calibrator._observation,
    ):
        mismatch = {"boundary": "initial_binding", "field": "calibrator_observation"}

    for tick in range(total_ticks):
        stage(baseline, tick, sample)
        stage(corrected, tick, sample)
        np.copyto(baseline_actions[tick], baseline.normalized_action_view)
        np.copyto(corrected_actions[tick], corrected.normalized_action_view)
        mismatch = mismatch or first_mismatch(baseline, corrected)
        if mismatch is not None:
            mismatch["tick"] = tick
            mismatch["boundary"] = mismatch.get("boundary", "staged")
            break
        baseline.complete_send(write_succeeded=True)
        corrected.complete_send(write_succeeded=True)
        mismatch = first_mismatch(baseline, corrected)
        if mismatch is not None:
            mismatch.update({"tick": tick, "boundary": "committed"})
            break
        if tick + 1 == CALIBRATION_TICKS:
            baseline.confirm_calibration_handoff(True)
            corrected.confirm_calibration_handoff(True)
            handoff_switches += 1
            if not np.shares_memory(
                corrected.assembler.observation,
                corrected._locomotion._observation,
            ) or np.shares_memory(
                corrected.assembler.observation,
                corrected._calibrator._observation,
            ):
                mismatch = {
                    "tick": tick,
                    "boundary": "handoff",
                    "field": "locomotion_observation_binding",
                }
                break

    baseline_hash = hashlib.sha256(baseline_actions.tobytes()).hexdigest()
    corrected_hash = hashlib.sha256(corrected_actions.tobytes()).hexdigest()
    return {
        "calibration_ticks": corrected.confirmed_calibration_ticks,
        "locomotion_ticks": corrected.confirmed_locomotion_ticks,
        "handoff_switches": handoff_switches,
        "mismatch": mismatch,
        "baseline_action_trace_sha256": baseline_hash,
        "corrected_action_trace_sha256": corrected_hash,
        "x5_reference_action_trace_sha256_informational": (
            EXPECTED_ACTION_TRACE_SHA256
        ),
        "maximum_rate_excess_rad_s": float(
            np.max(corrected.target_pipeline.graph_rate_excess_rad_s)
        ),
    }


def run_informational_timing(
    paths: dict[str, Path], preregistration: dict[str, Any]
) -> dict[str, Any]:
    host = build_host(WinnerV15GraphHostOptimizedTransaction, paths, preregistration)
    sample = samples(0.074)
    total_ticks = CALIBRATION_TICKS + LOCOMOTION_TICKS
    stage_ns = np.empty(total_ticks, dtype=np.int64)
    for tick in range(total_ticks):
        started = time.perf_counter_ns()
        stage(host, tick, sample)
        stage_ns[tick] = time.perf_counter_ns() - started
        host.complete_send(write_succeeded=True)
        if tick + 1 == CALIBRATION_TICKS:
            host.confirm_calibration_handoff(True)
    return summary_ns(stage_ns[CALIBRATION_TICKS:])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibrator", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--p30-fit", type=Path, required=True)
    parser.add_argument("--reference-table", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


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
    expected = {
        "calibrator": assets["calibrator_sha256"],
        "policy": assets["deployment_policy_sha256"],
        "p30_fit": assets["fixed_p30_runtime_observer_fit_sha256"],
        "reference_table": assets["projected_reference_table_sha256"],
    }
    asset_receipts = {name: receipt(path) for name, path in paths.items()}
    asset_hashes_exact = all(
        asset_receipts[name]["sha256"] == digest for name, digest in expected.items()
    )
    if not asset_hashes_exact:
        raise RuntimeError("T251A4 real-asset hash mismatch")

    semantic = run_semantic_contract(paths, preregistration)
    checks = {
        "asset_hashes_exact": asset_hashes_exact,
        "all_ticks_byte_exact": semantic["mismatch"] is None,
        "exact_tick_counts": semantic["calibration_ticks"] == CALIBRATION_TICKS
        and semantic["locomotion_ticks"] == LOCOMOTION_TICKS,
        "exact_one_handoff_binding_switch": semantic["handoff_switches"] == 1,
        "baseline_and_corrected_action_traces_identical": semantic[
            "baseline_action_trace_sha256"
        ]
        == semantic["corrected_action_trace_sha256"],
        "zero_rate_excess": semantic["maximum_rate_excess_rad_s"] == 0.0,
    }
    timing = run_informational_timing(paths, preregistration)
    failed = sorted(name for name, passed in checks.items() if not passed)
    result: dict[str, Any] = {
        "schema_version": "open_duck_x5.t251a4_graph_host_cpu_contract_result.v1",
        "status": (
            "PASS_T251A4_GRAPH_HOST_CPU_CONTRACT"
            if not failed
            else "FAIL_T251A4_GRAPH_HOST_CPU_CONTRACT"
        ),
        "candidate_id": assets["candidate_id"],
        "deployment_policy_sha256": assets["deployment_policy_sha256"],
        "preregistration": receipt(PREREGISTRATION),
        "source_receipts": {
            "transaction": receipt(
                ROOT / "src" / "open_duck_x5" / "winner_v13_state_coherent.py"
            ),
            "predecessor_host": receipt(ROOT / "tools" / "winner_v14_optimized.py"),
            "corrected_host": receipt(
                ROOT / "tools" / "winner_v15_graph_host_optimized.py"
            ),
            "verifier": receipt(Path(__file__)),
        },
        "asset_receipts": asset_receipts,
        "semantic_contract": semantic,
        "local_x86_timing_informational_only": timing,
        "checks": checks,
        "failed_checks": failed,
        "decision": (
            "EARN_T251A4_X5_SCREEN_PREREGISTRATION_ONLY"
            if not failed
            else "CLOSE_T251A4_WITHOUT_X5_EXECUTION"
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
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
