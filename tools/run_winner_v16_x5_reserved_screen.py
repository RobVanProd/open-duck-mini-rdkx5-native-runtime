#!/usr/bin/env python3
"""Run the preregistered no-device T251A5 X5 semantic/timing screen."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
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
from tools.run_winner_v14_x5_paced_screen import (  # noqa: E402
    build_host,
    exact_state_pairs,
    loaded_robot_modules,
    open_descriptors,
    receipt,
    require_inside,
    robot_descriptors,
    samples,
    sha256,
    stage,
    summary_ns,
)
from tools.winner_v15_graph_host_optimized import (  # noqa: E402
    WinnerV15GraphHostOptimizedTransaction,
)
from tools.winner_v16_target_optimized import (  # noqa: E402
    WinnerV16TargetOptimizedTransaction,
)

PREREGISTRATION = (
    ROOT
    / "artifacts"
    / "gates"
    / "phase_5_policy"
    / "t251a5_x5_target_reserved_screen_preregistration_20260731.json"
)
PREREGISTRATION_SHA256 = "37888047ab8b508463835e024706490dcf6aaceec4352a6801fd44c2de67a8c3"
EXPECTED_ROOT = Path("/home/sunrise/open_duck_x5_preflight/t251a5")


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run T251A5 X5 target semantic and reserved timing screen"
    )
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--calibrator", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--p30-fit", type=Path, required=True)
    parser.add_argument("--reference-table", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path, required=True)
    return parser.parse_args()


def mismatch(
    predecessor: WinnerV13StateCoherentTransaction,
    corrected: WinnerV13StateCoherentTransaction,
    *,
    committed: bool,
) -> dict[str, Any] | None:
    pairs = list(exact_state_pairs(predecessor, corrected, committed=committed))
    pairs.extend(
        (
            ("target_desired", predecessor.target_pipeline.desired_logical_target_rad,
             corrected.target_pipeline.desired_logical_target_rad),
            ("target_sent", predecessor.target_pipeline.sent_logical_target_rad,
             corrected.target_pipeline.sent_logical_target_rad),
            ("target_implied_velocity", predecessor.target_pipeline.implied_velocity_rad_s,
             corrected.target_pipeline.implied_velocity_rad_s),
            ("target_rate_excess", predecessor.target_pipeline.graph_rate_excess_rad_s,
             corrected.target_pipeline.graph_rate_excess_rad_s),
            ("calibrator_previous_action", predecessor._calibrator._previous_action,
             corrected._calibrator._previous_action),
            ("calibrator_hidden", predecessor._calibrator._hidden_in,
             corrected._calibrator._hidden_in),
            ("locomotion_previous_action", predecessor._locomotion._previous_action,
             corrected._locomotion._previous_action),
            ("locomotion_hidden", predecessor._locomotion._hidden_in,
             corrected._locomotion._hidden_in),
        )
    )
    for label, expected, actual in pairs:
        if not np.array_equal(expected, actual):
            return {
                "field": label,
                "maximum_absolute_delta": float(np.max(np.abs(expected - actual))),
            }
    scalar_pairs = (
        ("target_pending", predecessor.target_pipeline._pending,
         corrected.target_pipeline._pending),
        ("target_staged_mode", predecessor.target_pipeline._staged_mode,
         corrected.target_pipeline._staged_mode),
    )
    for label, expected, actual in scalar_pairs:
        if expected != actual:
            return {"field": label, "expected": expected, "actual": actual}
    return None


def wait_for_release(deadline_ns: int) -> int:
    remaining = deadline_ns - time.perf_counter_ns()
    if remaining > 0:
        time.sleep(remaining / 1_000_000_000.0)
    return max(0, time.perf_counter_ns() - deadline_ns)


def run_semantic_arm(
    paths: dict[str, Path], preregistration: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    predecessor = build_host(
        WinnerV15GraphHostOptimizedTransaction,
        paths,
        preregistration,
    )
    corrected = build_host(
        WinnerV16TargetOptimizedTransaction,
        paths,
        preregistration,
    )
    screen = preregistration["screen"]
    total_ticks = CALIBRATION_TICKS + int(screen["locomotion_ticks"])
    predecessor_actions = np.zeros((total_ticks, ACTION_DIM), dtype=np.float32)
    corrected_actions = np.zeros((total_ticks, ACTION_DIM), dtype=np.float32)
    release_lateness_ns = np.zeros(total_ticks, dtype=np.int64)
    sample = samples(float(screen["command_x_m_s"]))
    offsets = sample["soft_offsets_rad"]
    corrected.bind_soft_offsets(offsets)
    first_mismatch: dict[str, Any] | None = None
    maximum_rate_excess = 0.0
    handoff_switches = 0
    release_epoch = time.perf_counter_ns()
    for tick in range(total_ticks):
        release_lateness_ns[tick] = wait_for_release(
            release_epoch + tick * CONTROL_PERIOD_NS
        )
        stage(predecessor, tick, sample)
        stage(corrected, tick, sample)
        np.copyto(predecessor_actions[tick], predecessor.normalized_action_view)
        np.copyto(corrected_actions[tick], corrected.normalized_action_view)
        maximum_rate_excess = max(
            maximum_rate_excess,
            float(np.max(corrected.target_pipeline.graph_rate_excess_rad_s)),
        )
        first_mismatch = mismatch(predecessor, corrected, committed=False)
        if first_mismatch is not None:
            first_mismatch.update({"tick": tick, "boundary": "staged"})
            break
        predecessor.complete_send(write_succeeded=True)
        corrected.complete_send(write_succeeded=True)
        first_mismatch = mismatch(predecessor, corrected, committed=True)
        if first_mismatch is not None:
            first_mismatch.update({"tick": tick, "boundary": "committed"})
            break
        if tick + 1 == CALIBRATION_TICKS:
            predecessor.confirm_calibration_handoff(True)
            corrected.confirm_calibration_handoff(True)
            handoff_switches += 1
            if not np.array_equal(
                predecessor.calibration_context,
                corrected.calibration_context,
            ):
                first_mismatch = {
                    "tick": tick,
                    "boundary": "handoff",
                    "field": "calibration_context",
                }
                break

    arm = {
        "id": "separated_semantic_equivalence",
        "calibration_ticks": corrected.confirmed_calibration_ticks,
        "locomotion_ticks": corrected.confirmed_locomotion_ticks,
        "handoff_switches": handoff_switches,
        "mismatch": first_mismatch,
        "predecessor_action_trace_sha256": hashlib.sha256(
            predecessor_actions.tobytes()
        ).hexdigest(),
        "corrected_action_trace_sha256": hashlib.sha256(
            corrected_actions.tobytes()
        ).hexdigest(),
        "expected_action_trace_sha256": screen["expected_action_trace_sha256"],
        "maximum_rate_excess_rad_s": maximum_rate_excess,
        "offsets_immutable_and_identity_bound": (
            not offsets.flags.writeable
            and corrected.target_pipeline._trusted_offsets is offsets
        ),
        "locomotion_desired_sent_buffer_alias": (
            corrected.target_pipeline.desired_logical_target_rad
            is corrected.target_pipeline.sent_logical_target_rad
        ),
        "release_lateness": summary_ns(release_lateness_ns),
        "selection_weight": 0,
    }
    return arm, {
        "semantic_predecessor_actions": predecessor_actions,
        "semantic_corrected_actions": corrected_actions,
        "semantic_release_lateness_ns": release_lateness_ns,
    }


def run_timing_arm(
    paths: dict[str, Path], preregistration: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    host = build_host(
        WinnerV16TargetOptimizedTransaction,
        paths,
        preregistration,
    )
    screen = preregistration["screen"]
    total_ticks = CALIBRATION_TICKS + int(screen["locomotion_ticks"])
    stage_ns = np.empty(total_ticks, dtype=np.int64)
    commit_ns = np.empty(total_ticks, dtype=np.int64)
    release_lateness_ns = np.empty(total_ticks, dtype=np.int64)
    actions = np.empty((total_ticks, ACTION_DIM), dtype=np.float32)
    sample = samples(float(screen["command_x_m_s"]))
    offsets = sample["soft_offsets_rad"]
    host.bind_soft_offsets(offsets)
    maximum_rate_excess = 0.0
    release_epoch = time.perf_counter_ns()
    for tick in range(total_ticks):
        release_lateness_ns[tick] = wait_for_release(
            release_epoch + tick * CONTROL_PERIOD_NS
        )
        started = time.perf_counter_ns()
        stage(host, tick, sample)
        stage_ns[tick] = time.perf_counter_ns() - started
        np.copyto(actions[tick], host.normalized_action_view)
        maximum_rate_excess = max(
            maximum_rate_excess,
            float(np.max(host.target_pipeline.graph_rate_excess_rad_s)),
        )
        started = time.perf_counter_ns()
        host.complete_send(write_succeeded=True)
        commit_ns[tick] = time.perf_counter_ns() - started
        if tick + 1 == CALIBRATION_TICKS:
            host.confirm_calibration_handoff(True)

    locomotion = slice(CALIBRATION_TICKS, None)
    arm = {
        "id": "single_corrected_reserved_timing",
        "calibration_ticks": host.confirmed_calibration_ticks,
        "locomotion_ticks": host.confirmed_locomotion_ticks,
        "stage_locomotion": summary_ns(stage_ns[locomotion]),
        "commit_all": summary_ns(commit_ns),
        "release_lateness": summary_ns(release_lateness_ns),
        "action_trace_sha256": hashlib.sha256(actions.tobytes()).hexdigest(),
        "expected_action_trace_sha256": screen["expected_action_trace_sha256"],
        "maximum_rate_excess_rad_s": maximum_rate_excess,
        "offsets_immutable_and_identity_bound": (
            not offsets.flags.writeable
            and host.target_pipeline._trusted_offsets is offsets
        ),
        "locomotion_desired_sent_buffer_alias": (
            host.target_pipeline.desired_logical_target_rad
            is host.target_pipeline.sent_logical_target_rad
        ),
    }
    return arm, {
        "timing_stage_ns": stage_ns,
        "timing_commit_ns": commit_ns,
        "timing_release_lateness_ns": release_lateness_ns,
        "timing_actions": actions,
    }


def main() -> int:
    args = parse_args()
    root = args.staging_root.resolve()
    if root != EXPECTED_ROOT:
        raise RuntimeError(f"unpreregistered staging root: {root}")
    output = require_inside(args.output, root, "output")
    raw_output = require_inside(args.raw_output, root, "raw output")
    if output.exists() or raw_output.exists():
        raise FileExistsError("refusing to overwrite T251A5 evidence")
    machine = platform.machine().lower()
    if not sys.platform.startswith("linux") or machine not in {"aarch64", "arm64"}:
        raise RuntimeError("T251A5 requires aarch64 Linux")
    if sha256(PREREGISTRATION) != PREREGISTRATION_SHA256:
        raise RuntimeError("T251A5 preregistration changed")
    preregistration = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))

    source_paths = {
        label.removesuffix("_source"): ROOT / value
        for label, value in preregistration["exact_sources"].items()
        if label.endswith("_source")
    }
    source_checks = {
        name: sha256(path)
        == preregistration["exact_sources"][f"{name}_source_sha256"]
        for name, path in source_paths.items()
    }
    tracked_status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        text=True,
    ).strip()
    if tracked_status or not all(source_checks.values()):
        raise RuntimeError(
            f"T251A5 requires clean exact sources: dirty={bool(tracked_status)} "
            f"checks={source_checks}"
        )

    paths = {
        "calibrator": require_inside(args.calibrator, root, "calibrator"),
        "deployment_policy": require_inside(args.policy, root, "policy"),
        "fixed_p30_runtime_observer_fit": require_inside(
            args.p30_fit, root, "P30 fit"
        ),
        "projected_reference_table": require_inside(
            args.reference_table, root, "reference table"
        ),
    }
    assets = preregistration["unchanged_assets"]
    expected_hashes = {
        "calibrator": assets["calibrator_sha256"],
        "deployment_policy": assets["deployment_policy_sha256"],
        "fixed_p30_runtime_observer_fit": assets[
            "fixed_p30_runtime_observer_fit_sha256"
        ],
        "projected_reference_table": assets["projected_reference_table_sha256"],
    }
    asset_receipts = {name: receipt(path) for name, path in paths.items()}
    asset_checks = {
        name: asset_receipts[name]["sha256"] == digest
        for name, digest in expected_hashes.items()
    }
    if not all(asset_checks.values()):
        raise RuntimeError(f"T251A5 asset mismatch: {asset_checks}")

    scheduler = os.sched_getscheduler(0)
    priority = os.sched_getparam(0).sched_priority
    affinity = sorted(os.sched_getaffinity(0))
    governor = Path(
        f"/sys/devices/system/cpu/cpu{affinity[0]}/cpufreq/scaling_governor"
    ).read_text(encoding="utf-8").strip()
    descriptors_before = robot_descriptors(open_descriptors())
    modules_before = loaded_robot_modules()
    gc_was_enabled = gc.isenabled()
    gc.collect()
    gc.disable()
    try:
        semantic, semantic_raw = run_semantic_arm(paths, preregistration)
        timing, timing_raw = run_timing_arm(paths, preregistration)
    finally:
        if gc_was_enabled:
            gc.enable()
        else:
            gc.disable()
    descriptors_after = robot_descriptors(open_descriptors())
    modules_after = loaded_robot_modules()
    limits = preregistration["reference_reserve_limits_ms"]
    stage_summary = timing["stage_locomotion"]

    checks = {
        "source_hashes_exact": all(source_checks.values()),
        "asset_hashes_exact": all(asset_checks.values()),
        "sched_fifo": scheduler == os.SCHED_FIFO,
        "priority_80": priority == 80,
        "affinity_cpu7_only": affinity == [7],
        "performance_governor": governor == "performance",
        "semantic_all_ticks_byte_exact": semantic["mismatch"] is None,
        "semantic_exact_tick_counts": semantic["calibration_ticks"]
        == CALIBRATION_TICKS
        and semantic["locomotion_ticks"] == preregistration["screen"][
            "locomotion_ticks"
        ],
        "semantic_exact_one_handoff": semantic["handoff_switches"] == 1,
        "semantic_trace_exact": semantic["predecessor_action_trace_sha256"]
        == semantic["corrected_action_trace_sha256"]
        == semantic["expected_action_trace_sha256"],
        "semantic_offsets_immutable_identity_bound": semantic[
            "offsets_immutable_and_identity_bound"
        ],
        "semantic_locomotion_target_alias": semantic[
            "locomotion_desired_sent_buffer_alias"
        ],
        "timing_exact_tick_counts": timing["calibration_ticks"]
        == CALIBRATION_TICKS
        and timing["locomotion_ticks"] == preregistration["screen"][
            "locomotion_ticks"
        ],
        "timing_trace_exact": timing["action_trace_sha256"]
        == timing["expected_action_trace_sha256"],
        "timing_offsets_immutable_identity_bound": timing[
            "offsets_immutable_and_identity_bound"
        ],
        "timing_locomotion_target_alias": timing[
            "locomotion_desired_sent_buffer_alias"
        ],
        "zero_rate_excess": semantic["maximum_rate_excess_rad_s"] == 0.0
        and timing["maximum_rate_excess_rad_s"] == 0.0,
        "no_robot_descriptors": not descriptors_before and not descriptors_after,
        "no_robot_modules": not modules_before and not modules_after,
        "stage_p99_within_reserve": stage_summary["p99_ms"] <= limits["p99_ms"],
        "stage_p99_9_within_reserve": stage_summary["p99_9_ms"]
        <= limits["p99_9_ms"],
        "stage_max_within_reserve": stage_summary["max_ms"] <= limits["max_ms"],
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    reserve_passed = all(
        checks[name]
        for name in (
            "stage_p99_within_reserve",
            "stage_p99_9_within_reserve",
            "stage_max_within_reserve",
        )
    )
    semantic_passed = all(
        checks[name]
        for name in (
            "semantic_all_ticks_byte_exact",
            "semantic_exact_tick_counts",
            "semantic_exact_one_handoff",
            "semantic_trace_exact",
            "semantic_offsets_immutable_identity_bound",
            "semantic_locomotion_target_alias",
            "zero_rate_excess",
        )
    )
    status = (
        "PASS_T251A5_X5_TARGET_RESERVED_SCREEN"
        if not failed
        else "HOLD_T251A5_X5_TARGET_RESERVED_SCREEN"
    )
    decision = (
        "EARN_T251B_PREREGISTRATION_ONLY"
        if not failed
        else "CLOSE_TARGET_CORRECTION_WITHOUT_T251B"
    )
    result: dict[str, Any] = {
        "schema_version": "open_duck_x5.t251a5_x5_target_reserved_screen_result.v1",
        "status": status,
        "date": preregistration["date"],
        "preregistration": receipt(PREREGISTRATION),
        "git": {
            "commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "tracked_clean": not bool(tracked_status),
        },
        "source_receipts": {
            name: receipt(path) for name, path in source_paths.items()
        },
        "asset_receipts": asset_receipts,
        "platform": {
            "machine": machine,
            "scheduler": scheduler,
            "priority": priority,
            "affinity": affinity,
            "governor": governor,
            "gc_disabled_during_arms": True,
        },
        "semantic_arm": semantic,
        "timing_arm": timing,
        "reference_reserve_limits_ms": limits,
        "semantic_passed": semantic_passed,
        "reference_reserve_passed": reserve_passed,
        "checks": checks,
        "failed_checks": failed,
        "decision": decision,
        "device_evidence": {
            "robot_descriptors_before": descriptors_before,
            "robot_descriptors_after": descriptors_after,
            "robot_modules_before": modules_before,
            "robot_modules_after": modules_after,
            "external_send_implementation": False,
            "serial_gpio_i2c_controller_or_torque_access": False,
        },
        "raw_output": {"path": str(raw_output), "sha256": None},
        "authority": {
            "t251b_earned": not failed,
            "t251b_executed": False,
            "threshold_changed": False,
            "policy_training": False,
            "production_integration": False,
            "policy_deployed": False,
            "serial_bus": False,
            "sensors": False,
            "torque": False,
            "motion": False,
            "gate5": False,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(raw_output, **semantic_raw, **timing_raw)
    result["raw_output"]["sha256"] = sha256(raw_output)
    result["result_sha256"] = canonical_sha256(result)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
