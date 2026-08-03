#!/usr/bin/env python3
"""Verify the preregistered T251A6 observation-only correction."""

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
from tools.winner_v17_observation_optimized import (  # noqa: E402
    WinnerV17ObservationOptimizedTransaction,
)

PREREGISTRATION = (
    ROOT
    / "artifacts"
    / "gates"
    / "phase_5_policy"
    / "t251a6_observation_correction_preregistration_20260731.json"
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


def bind_observation_sources(
    host: WinnerV17ObservationOptimizedTransaction,
    sample: dict[str, Any],
) -> None:
    host.bind_observation_sources(
        gyro_rad_s=sample["gyro_rad_s"],
        acceleration_m_s2=sample["acceleration_m_s2"],
        commands=sample["commands"],
        positions_rad=sample["positions_rad"],
        velocities_rad_s=sample["velocities_rad_s"],
        foot_contacts=sample["foot_contacts"],
        servo_stale=sample["servo_stale"],
    )


def mismatch(
    predecessor: WinnerV13StateCoherentTransaction,
    corrected: WinnerV13StateCoherentTransaction,
) -> dict[str, Any] | None:
    pairs = list(exact_pairs(predecessor, corrected))
    pairs.extend(
        (
            ("desired_target", predecessor.target_pipeline.desired_logical_target_rad,
             corrected.target_pipeline.desired_logical_target_rad),
            ("implied_velocity", predecessor.target_pipeline.implied_velocity_rad_s,
             corrected.target_pipeline.implied_velocity_rad_s),
            ("rate_excess", predecessor.target_pipeline.graph_rate_excess_rad_s,
             corrected.target_pipeline.graph_rate_excess_rad_s),
            ("last_action", predecessor.assembler.last_action,
             corrected.assembler.last_action),
            ("action_minus_2", predecessor.assembler.action_minus_2,
             corrected.assembler.action_minus_2),
            ("action_minus_3", predecessor.assembler.action_minus_3,
             corrected.assembler.action_minus_3),
            ("deferred_action", predecessor.assembler._deferred_action,
             corrected.assembler._deferred_action),
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
        WinnerV17ObservationOptimizedTransaction,
        paths,
        preregistration,
    )
    sample = samples(0.074)
    offsets = sample["soft_offsets_rad"]
    predecessor.bind_soft_offsets(offsets)
    corrected.bind_soft_offsets(offsets)
    bind_observation_sources(corrected, sample)
    total_ticks = CALIBRATION_TICKS + LOCOMOTION_TICKS
    predecessor_actions = np.zeros((total_ticks, ACTION_DIM), dtype=np.float32)
    corrected_actions = np.zeros((total_ticks, ACTION_DIM), dtype=np.float32)
    first_mismatch: dict[str, Any] | None = None
    handoff_switches = 0
    for tick in range(total_ticks):
        stage(predecessor, tick, sample)
        stage(corrected, tick, sample)
        np.copyto(predecessor_actions[tick], predecessor.normalized_action_view)
        np.copyto(corrected_actions[tick], corrected.normalized_action_view)
        first_mismatch = mismatch(predecessor, corrected)
        if first_mismatch is not None:
            first_mismatch.update({"tick": tick, "boundary": "staged"})
            break
        predecessor.complete_send(write_succeeded=True)
        corrected.complete_send(write_succeeded=True)
        first_mismatch = mismatch(predecessor, corrected)
        if first_mismatch is not None:
            first_mismatch.update({"tick": tick, "boundary": "committed"})
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
        "mismatch": first_mismatch,
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


def assemble(
    host: WinnerV13StateCoherentTransaction,
    sample: dict[str, Any],
) -> np.ndarray:
    return host.assembler.build(
        gyro_rad_s=sample["gyro_rad_s"],
        acceleration_m_s2=sample["acceleration_m_s2"],
        commands=sample["commands"],
        positions_rad=sample["positions_rad"],
        velocities_rad_s=sample["velocities_rad_s"],
        observer_target_rad=host.observer.value_view,
        foot_contacts=sample["foot_contacts"],
        phase=host.phase.value,
        phase_index=host.phase.index,
        servo_stale=sample["servo_stale"],
        imu_stale=False,
        contacts_stale=False,
    )


def run_observation_microbenchmark(
    paths: dict[str, Path], preregistration: dict[str, Any]
) -> dict[str, Any]:
    predecessor = build_host(
        WinnerV16TargetOptimizedTransaction,
        paths,
        preregistration,
    )
    corrected = build_host(
        WinnerV17ObservationOptimizedTransaction,
        paths,
        preregistration,
    )
    sample = samples(0.074)
    corrected.bind_soft_offsets(sample["soft_offsets_rad"])
    bind_observation_sources(corrected, sample)
    action_history = np.linspace(-0.2, 0.2, 4 * ACTION_DIM, dtype=np.float32).reshape(
        4, ACTION_DIM
    )
    for index, name in enumerate(
        ("last_action", "action_minus_2", "action_minus_3", "_deferred_action")
    ):
        np.copyto(getattr(predecessor.assembler, name), action_history[index])
        np.copyto(getattr(corrected.assembler, name), action_history[index])
    assemble(predecessor, sample)
    assemble(corrected, sample)
    predecessor_ns = np.empty(MICROBENCHMARK_SAMPLES, dtype=np.int64)
    corrected_ns = np.empty(MICROBENCHMARK_SAMPLES, dtype=np.int64)
    mismatch_tick: int | None = None
    for tick in range(MICROBENCHMARK_SAMPLES):
        sample["gyro_rad_s"][0] = (tick % 17) * 1.0e-4
        sample["positions_rad"][0] += 1.0e-7
        sample["velocities_rad_s"][1] = (tick % 23) * -1.0e-4
        if tick % 2 == 0:
            started = time.perf_counter_ns()
            expected = assemble(predecessor, sample)
            predecessor_ns[tick] = time.perf_counter_ns() - started
            started = time.perf_counter_ns()
            actual = assemble(corrected, sample)
            corrected_ns[tick] = time.perf_counter_ns() - started
        else:
            started = time.perf_counter_ns()
            actual = assemble(corrected, sample)
            corrected_ns[tick] = time.perf_counter_ns() - started
            started = time.perf_counter_ns()
            expected = assemble(predecessor, sample)
            predecessor_ns[tick] = time.perf_counter_ns() - started
        if not np.array_equal(expected, actual):
            mismatch_tick = tick
            break
    predecessor_summary = summary_ns(predecessor_ns)
    corrected_summary = summary_ns(corrected_ns)
    median_ratio = float(corrected_summary["p50_ms"] / predecessor_summary["p50_ms"])
    return {
        "samples": MICROBENCHMARK_SAMPLES,
        "alternated_order": True,
        "mutated_bound_sources_in_place": True,
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
        raise RuntimeError("T251A6 real-asset hash mismatch")
    semantic = run_semantic_contract(paths, preregistration)
    benchmark = run_observation_microbenchmark(paths, preregistration)
    checks = {
        "asset_hashes_exact": asset_hashes_exact,
        "all_ticks_byte_exact": semantic["mismatch"] is None,
        "exact_tick_counts": semantic["calibration_ticks"] == CALIBRATION_TICKS
        and semantic["locomotion_ticks"] == LOCOMOTION_TICKS,
        "exact_one_handoff": semantic["handoff_switches"] == 1,
        "live_sources_remain_writeable": semantic[
            "bound_live_sources_remain_writeable"
        ],
        "action_traces_identical": semantic["predecessor_action_trace_sha256"]
        == semantic["corrected_action_trace_sha256"],
        "zero_rate_excess": semantic["maximum_rate_excess_rad_s"] == 0.0,
        "microbenchmark_outputs_exact": benchmark["mismatch_tick"] is None,
        "microbenchmark_mutates_live_sources": benchmark[
            "mutated_bound_sources_in_place"
        ],
        "microbenchmark_median_improves_at_least_25_percent": benchmark[
            "corrected_to_predecessor_median_ratio"
        ]
        <= benchmark["required_maximum_median_ratio"],
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    result: dict[str, Any] = {
        "schema_version": "open_duck_x5.t251a6_observation_cpu_contract_result.v1",
        "status": (
            "PASS_T251A6_OBSERVATION_CPU_CONTRACT"
            if not failed
            else "FAIL_T251A6_OBSERVATION_CPU_CONTRACT"
        ),
        "candidate_id": assets["candidate_id"],
        "deployment_policy_sha256": assets["deployment_policy_sha256"],
        "preregistration": receipt(PREREGISTRATION),
        "source_receipts": {
            "transaction": receipt(
                ROOT / "src" / "open_duck_x5" / "winner_v13_state_coherent.py"
            ),
            "predecessor_host": receipt(
                ROOT / "tools" / "winner_v16_target_optimized.py"
            ),
            "corrected_host": receipt(
                ROOT / "tools" / "winner_v17_observation_optimized.py"
            ),
            "verifier": receipt(Path(__file__)),
        },
        "asset_receipts": asset_receipts,
        "semantic_contract": semantic,
        "local_observation_microbenchmark": benchmark,
        "checks": checks,
        "failed_checks": failed,
        "decision": (
            "EARN_T251A6_X5_SCREEN_PREREGISTRATION_ONLY"
            if not failed
            else "CLOSE_T251A6_WITHOUT_X5_EXECUTION"
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
