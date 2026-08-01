#!/usr/bin/env python3
"""Run the preregistered no-device T247 context-route X5 reserve screen."""

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
import onnxruntime as ort

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from open_duck_x5.constants import ACTION_DIM, CONTROL_PERIOD_NS  # noqa: E402
from open_duck_x5.winner_v13_state_coherent import (  # noqa: E402
    CALIBRATION_TICKS,
    GraphAsset,
    P30FitAsset,
    WinnerV13StateCoherentTransaction,
)
from tools.run_winner_v14_x5_paced_screen import (  # noqa: E402
    calibrator_spec,
    exact_state_pairs,
    loaded_robot_modules,
    locomotion_spec,
    open_descriptors,
    receipt,
    require_inside,
    robot_descriptors,
    samples,
    sha256,
    stage,
    summary_ns,
)
from tools.winner_v16_target_optimized import (  # noqa: E402
    WinnerV16TargetOptimizedTransaction,
)

PREREGISTRATION = (
    ROOT
    / "artifacts"
    / "gates"
    / "phase_5_policy"
    / "t247_deployment_x5_context_route_reserved_screen_preregistration_20260731.json"
)
PREREGISTRATION_SHA256 = (
    "1fe2b2103967a25ce6ed84d60b620c3021e2daba461d0d9eb230a5299513ac05"
)
EXPECTED_ROOT = Path("/home/sunrise/open_duck_x5_preflight/t247-context-route-v1")
ROUTE_NAMES = (
    "lower-cond0",
    "lower-cond1",
    "positive-cond0",
    "positive-cond1",
    "tail-cond0",
    "tail-cond1",
)
ROUTER_OUTPUTS = (
    "t243_home_negative_tail_condition",
    "t149_negative_condition",
    "t162_positive_condition",
    "conditional_path_negative_condition",
    "t156_positive_condition",
)
GRAPH_WARMUP_RUNS = 3


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--execution-package", type=Path, required=True)
    parser.add_argument("--calibrator", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--router", type=Path, required=True)
    parser.add_argument("--variant-root", type=Path, required=True)
    parser.add_argument("--p30-fit", type=Path, required=True)
    parser.add_argument("--reference-table", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path, required=True)
    return parser.parse_args()


def route_from_predicates(values: list[bool]) -> str:
    if len(values) != len(ROUTER_OUTPUTS):
        raise RuntimeError(f"expected five route predicates, got {len(values)}")
    tail, t149_conditional, t162_positive, t143_conditional, t156_positive = values
    if t149_conditional != t143_conditional:
        raise RuntimeError("original conditional-path predicates disagree")
    if t162_positive != t156_positive:
        raise RuntimeError("original bounded-positive predicates disagree")
    if tail and t162_positive:
        raise RuntimeError("tail and bounded-positive predicates overlap")
    regime = "tail" if tail else "positive" if t162_positive else "lower"
    return f"{regime}-cond{int(t149_conditional)}"


def router_session(path: Path) -> ort.InferenceSession:
    options = ort.SessionOptions()
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    options.add_session_config_entry("session.inter_op.allow_spinning", "0")
    session = ort.InferenceSession(
        str(path),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )
    inputs = [(value.name, tuple(value.shape), value.type) for value in session.get_inputs()]
    outputs = [(value.name, tuple(value.shape), value.type) for value in session.get_outputs()]
    expected_outputs = [(name, (1, 1), "tensor(bool)") for name in ROUTER_OUTPUTS]
    if inputs != [("calibration_context", (1, 64), "tensor(float)")]:
        raise RuntimeError(f"context-router input ABI mismatch: {inputs}")
    if outputs != expected_outputs:
        raise RuntimeError(f"context-router output ABI mismatch: {outputs}")
    return session


def select_route(session: ort.InferenceSession, context: np.ndarray) -> str:
    values = session.run(
        list(ROUTER_OUTPUTS),
        {"calibration_context": context.reshape(1, 64)},
    )
    return route_from_predicates([bool(value.item()) for value in values])


def build_host(
    paths: dict[str, Path],
    policy_path: Path,
    policy_sha256: str,
    preregistration: dict[str, Any],
) -> WinnerV16TargetOptimizedTransaction:
    assets = preregistration["unchanged_assets"]
    return WinnerV16TargetOptimizedTransaction(
        calibrator=GraphAsset(
            paths["calibrator"],
            calibrator_spec(),
            frozenset({assets["calibrator_sha256"]}),
        ),
        locomotion=GraphAsset(
            policy_path,
            locomotion_spec(),
            frozenset({policy_sha256}),
        ),
        p30_fit=P30FitAsset(
            paths["p30_fit"],
            frozenset({assets["fixed_p30_runtime_observer_fit_sha256"]}),
        ),
        reference_table_path=paths["reference_table"],
        enabled=True,
        warmup_runs=GRAPH_WARMUP_RUNS,
    )


def mismatch(
    predecessor: WinnerV13StateCoherentTransaction,
    specialized: WinnerV13StateCoherentTransaction,
    *,
    committed: bool,
) -> dict[str, Any] | None:
    pairs = list(exact_state_pairs(predecessor, specialized, committed=committed))
    pairs.extend(
        (
            (
                "target_desired",
                predecessor.target_pipeline.desired_logical_target_rad,
                specialized.target_pipeline.desired_logical_target_rad,
            ),
            (
                "target_sent",
                predecessor.target_pipeline.sent_logical_target_rad,
                specialized.target_pipeline.sent_logical_target_rad,
            ),
            (
                "target_implied_velocity",
                predecessor.target_pipeline.implied_velocity_rad_s,
                specialized.target_pipeline.implied_velocity_rad_s,
            ),
            (
                "target_rate_excess",
                predecessor.target_pipeline.graph_rate_excess_rad_s,
                specialized.target_pipeline.graph_rate_excess_rad_s,
            ),
            (
                "calibrator_previous_action",
                predecessor._calibrator._previous_action,
                specialized._calibrator._previous_action,
            ),
            (
                "calibrator_hidden",
                predecessor._calibrator._hidden_in,
                specialized._calibrator._hidden_in,
            ),
            (
                "locomotion_previous_action",
                predecessor._locomotion._previous_action,
                specialized._locomotion._previous_action,
            ),
            (
                "locomotion_hidden",
                predecessor._locomotion._hidden_in,
                specialized._locomotion._hidden_in,
            ),
        )
    )
    for label, expected, actual in pairs:
        if not np.array_equal(expected, actual):
            return {
                "field": label,
                "maximum_absolute_delta": float(np.max(np.abs(expected - actual))),
            }
    scalar_pairs = (
        (
            "target_pending",
            predecessor.target_pipeline._pending,
            specialized.target_pipeline._pending,
        ),
        (
            "target_staged_mode",
            predecessor.target_pipeline._staged_mode,
            specialized.target_pipeline._staged_mode,
        ),
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
    paths: dict[str, Path],
    variant_path: Path,
    variant_sha256: str,
    router: ort.InferenceSession,
    preregistration: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    original = build_host(
        paths,
        paths["policy"],
        preregistration["unchanged_assets"]["deployment_policy_sha256"],
        preregistration,
    )
    specialized = build_host(
        paths,
        variant_path,
        variant_sha256,
        preregistration,
    )
    screen = preregistration["screen"]
    total_ticks = CALIBRATION_TICKS + int(screen["locomotion_ticks"])
    original_actions = np.zeros((total_ticks, ACTION_DIM), dtype=np.float32)
    specialized_actions = np.zeros((total_ticks, ACTION_DIM), dtype=np.float32)
    release_lateness_ns = np.zeros(total_ticks, dtype=np.int64)
    sample = samples(float(screen["command_x_m_s"]))
    offsets = sample["soft_offsets_rad"]
    original.bind_soft_offsets(offsets)
    specialized.bind_soft_offsets(offsets)
    first_mismatch: dict[str, Any] | None = None
    maximum_rate_excess = 0.0
    handoff_switches = 0
    selected_route: str | None = None
    context_sha256: str | None = None
    release_epoch = time.perf_counter_ns()
    for tick in range(total_ticks):
        release_lateness_ns[tick] = wait_for_release(
            release_epoch + tick * CONTROL_PERIOD_NS
        )
        stage(original, tick, sample)
        stage(specialized, tick, sample)
        np.copyto(original_actions[tick], original.normalized_action_view)
        np.copyto(specialized_actions[tick], specialized.normalized_action_view)
        maximum_rate_excess = max(
            maximum_rate_excess,
            float(np.max(specialized.target_pipeline.graph_rate_excess_rad_s)),
        )
        first_mismatch = mismatch(original, specialized, committed=False)
        if first_mismatch is not None:
            first_mismatch.update({"tick": tick, "boundary": "staged"})
            break
        original.complete_send(write_succeeded=True)
        specialized.complete_send(write_succeeded=True)
        first_mismatch = mismatch(original, specialized, committed=True)
        if first_mismatch is not None:
            first_mismatch.update({"tick": tick, "boundary": "committed"})
            break
        if tick + 1 == CALIBRATION_TICKS:
            original.confirm_calibration_handoff(True)
            specialized.confirm_calibration_handoff(True)
            handoff_switches += 1
            if not np.array_equal(
                original.calibration_context, specialized.calibration_context
            ):
                first_mismatch = {
                    "tick": tick,
                    "boundary": "handoff",
                    "field": "calibration_context",
                }
                break
            context = original.calibration_context
            context_sha256 = hashlib.sha256(context.tobytes()).hexdigest()
            selected_route = select_route(router, context)

    arm = {
        "id": "paced_original_vs_context_specialized_semantics",
        "calibration_ticks": specialized.confirmed_calibration_ticks,
        "locomotion_ticks": specialized.confirmed_locomotion_ticks,
        "handoff_switches": handoff_switches,
        "selected_route": selected_route,
        "context_float32_bytes_sha256": context_sha256,
        "mismatch": first_mismatch,
        "original_action_trace_sha256": hashlib.sha256(
            original_actions.tobytes()
        ).hexdigest(),
        "specialized_action_trace_sha256": hashlib.sha256(
            specialized_actions.tobytes()
        ).hexdigest(),
        "expected_action_trace_sha256": screen["expected_action_trace_sha256"],
        "maximum_rate_excess_rad_s": maximum_rate_excess,
        "offsets_immutable_and_identity_bound": (
            not offsets.flags.writeable
            and original.target_pipeline._trusted_offsets is offsets
            and specialized.target_pipeline._trusted_offsets is offsets
        ),
        "locomotion_desired_sent_buffer_alias": (
            original.target_pipeline.desired_logical_target_rad
            is original.target_pipeline.sent_logical_target_rad
            and specialized.target_pipeline.desired_logical_target_rad
            is specialized.target_pipeline.sent_logical_target_rad
        ),
        "release_lateness": summary_ns(release_lateness_ns),
        "selection_weight": 0,
    }
    return arm, {
        "semantic_original_actions": original_actions,
        "semantic_specialized_actions": specialized_actions,
        "semantic_release_lateness_ns": release_lateness_ns,
    }


def run_timing_arm(
    paths: dict[str, Path],
    variant_path: Path,
    variant_sha256: str,
    router: ort.InferenceSession,
    preregistration: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    host = build_host(paths, variant_path, variant_sha256, preregistration)
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
    selected_route: str | None = None
    context_sha256: str | None = None
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
            context = host.calibration_context
            context_sha256 = hashlib.sha256(context.tobytes()).hexdigest()
            selected_route = select_route(router, context)

    locomotion = slice(CALIBRATION_TICKS, None)
    arm = {
        "id": "paced_single_context_specialized_reserved_timing",
        "calibration_ticks": host.confirmed_calibration_ticks,
        "locomotion_ticks": host.confirmed_locomotion_ticks,
        "selected_route": selected_route,
        "context_float32_bytes_sha256": context_sha256,
        "stage_locomotion": summary_ns(stage_ns[locomotion]),
        "commit_all": summary_ns(commit_ns),
        "release_lateness": summary_ns(release_lateness_ns),
        "action_trace_sha256": hashlib.sha256(actions.tobytes()).hexdigest(),
        "expected_action_trace_sha256": screen["expected_action_trace_sha256"],
        "maximum_rate_excess_rad_s": maximum_rate_excess,
        "offsets_immutable_and_identity_bound": (
            not offsets.flags.writeable and host.target_pipeline._trusted_offsets is offsets
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


def verify_execution_package(path: Path) -> tuple[dict[str, Any], dict[str, bool]]:
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT):
        raise RuntimeError("execution package must be a tracked repository artifact")
    package = json.loads(resolved.read_text(encoding="utf-8"))
    if package["status"] != "SEALED_T247_X5_CONTEXT_ROUTE_EXECUTION_PACKAGE":
        raise RuntimeError("execution package is not sealed")
    if package["preregistration_file_sha256"] != PREREGISTRATION_SHA256:
        raise RuntimeError("execution package pins the wrong preregistration")
    source_checks = {
        relative: sha256(ROOT / relative) == expected
        for relative, expected in package["source_sha256"].items()
    }
    if not source_checks or not all(source_checks.values()):
        raise RuntimeError(f"execution package source mismatch: {source_checks}")
    return package, source_checks


def main() -> int:
    args = parse_args()
    root = args.staging_root.resolve()
    if root != EXPECTED_ROOT:
        raise RuntimeError(f"unpreregistered staging root: {root}")
    output = require_inside(args.output, root, "output")
    raw_output = require_inside(args.raw_output, root, "raw output")
    variant_root = require_inside(args.variant_root, root, "variant root")
    if output.exists() or raw_output.exists():
        raise FileExistsError("refusing to overwrite T247 context-route evidence")
    machine = platform.machine().lower()
    if not sys.platform.startswith("linux") or machine not in {"aarch64", "arm64"}:
        raise RuntimeError("T247 X5 screen requires aarch64 Linux")
    if sha256(PREREGISTRATION) != PREREGISTRATION_SHA256:
        raise RuntimeError("T247 X5 preregistration changed")
    preregistration = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    package, source_checks = verify_execution_package(args.execution_package)

    tracked_status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        text=True,
    ).strip()
    if tracked_status:
        raise RuntimeError("T247 X5 screen requires a clean tracked repository")

    paths = {
        "calibrator": require_inside(args.calibrator, root, "calibrator"),
        "policy": require_inside(args.policy, root, "policy"),
        "router": require_inside(args.router, root, "router"),
        "p30_fit": require_inside(args.p30_fit, root, "P30 fit"),
        "reference_table": require_inside(
            args.reference_table, root, "reference table"
        ),
    }
    assets = preregistration["unchanged_assets"]
    expected_hashes = {
        "calibrator": assets["calibrator_sha256"],
        "policy": assets["deployment_policy_sha256"],
        "router": preregistration["derived_assets"]["context_router_sha256"],
        "p30_fit": assets["fixed_p30_runtime_observer_fit_sha256"],
        "reference_table": assets["projected_reference_table_sha256"],
    }
    asset_receipts = {name: receipt(path) for name, path in paths.items()}
    asset_checks = {
        name: asset_receipts[name]["sha256"] == expected
        for name, expected in expected_hashes.items()
    }
    variant_paths = {
        route: require_inside(
            variant_root / f"policy.{route}.onnx",
            root,
            f"{route} variant",
        )
        for route in ROUTE_NAMES
    }
    variant_receipts = {route: receipt(path) for route, path in variant_paths.items()}
    variant_checks = {
        route: variant_receipts[route]["sha256"]
        == preregistration["derived_assets"]["routes"][route]
        for route in ROUTE_NAMES
    }
    if not all(asset_checks.values()) or not all(variant_checks.values()):
        raise RuntimeError(
            f"T247 X5 asset mismatch: assets={asset_checks} variants={variant_checks}"
        )

    scheduler = os.sched_getscheduler(0)
    priority = os.sched_getparam(0).sched_priority
    affinity = sorted(os.sched_getaffinity(0))
    governor = Path(
        f"/sys/devices/system/cpu/cpu{affinity[0]}/cpufreq/scaling_governor"
    ).read_text(encoding="utf-8").strip()
    descriptors_before = robot_descriptors(open_descriptors())
    modules_before = loaded_robot_modules()
    router = router_session(paths["router"])
    selected_variant = variant_paths[preregistration["screen"]["expected_route"]]
    selected_variant_sha256 = variant_receipts[
        preregistration["screen"]["expected_route"]
    ]["sha256"]
    gc_was_enabled = gc.isenabled()
    gc.collect()
    gc.disable()
    try:
        semantic, semantic_raw = run_semantic_arm(
            paths,
            selected_variant,
            selected_variant_sha256,
            router,
            preregistration,
        )
        timing, timing_raw = run_timing_arm(
            paths,
            selected_variant,
            selected_variant_sha256,
            router,
            preregistration,
        )
    finally:
        if gc_was_enabled:
            gc.enable()
        else:
            gc.disable()
    descriptors_after = robot_descriptors(open_descriptors())
    modules_after = loaded_robot_modules()
    screen = preregistration["screen"]
    limits = screen["reference_reserve_limits_ms"]
    stage_summary = timing["stage_locomotion"]

    checks = {
        "execution_package_sources_exact": all(source_checks.values()),
        "tracked_repository_clean": not bool(tracked_status),
        "asset_hashes_exact": all(asset_checks.values()),
        "all_six_variant_hashes_exact": all(variant_checks.values()),
        "sched_fifo": scheduler == os.SCHED_FIFO,
        "priority_80": priority == 80,
        "affinity_cpu7_only": affinity == [7],
        "performance_governor": governor == "performance",
        "semantic_all_ticks_byte_exact": semantic["mismatch"] is None,
        "semantic_exact_tick_counts": (
            semantic["calibration_ticks"] == CALIBRATION_TICKS
            and semantic["locomotion_ticks"] == screen["locomotion_ticks"]
        ),
        "semantic_exact_one_handoff": semantic["handoff_switches"] == 1,
        "semantic_exact_route_and_context": (
            semantic["selected_route"] == screen["expected_route"]
            and semantic["context_float32_bytes_sha256"]
            == screen["expected_context_float32_bytes_sha256"]
        ),
        "semantic_trace_exact": semantic["original_action_trace_sha256"]
        == semantic["specialized_action_trace_sha256"]
        == semantic["expected_action_trace_sha256"],
        "semantic_offsets_immutable_identity_bound": semantic[
            "offsets_immutable_and_identity_bound"
        ],
        "semantic_locomotion_target_alias": semantic[
            "locomotion_desired_sent_buffer_alias"
        ],
        "timing_exact_tick_counts": (
            timing["calibration_ticks"] == CALIBRATION_TICKS
            and timing["locomotion_ticks"] == screen["locomotion_ticks"]
        ),
        "timing_exact_route_and_context": (
            timing["selected_route"] == screen["expected_route"]
            and timing["context_float32_bytes_sha256"]
            == screen["expected_context_float32_bytes_sha256"]
        ),
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
        "stage_p99_within_reserve": stage_summary["p99_ms"] <= limits["p99"],
        "stage_p99_9_within_reserve": stage_summary["p99_9_ms"] <= limits["p99_9"],
        "stage_max_within_reserve": stage_summary["max_ms"] <= limits["max"],
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    status = (
        "PASS_T247_X5_CONTEXT_ROUTE_RESERVED_SCREEN"
        if not failed
        else "HOLD_T247_X5_CONTEXT_ROUTE_RESERVED_SCREEN"
    )
    result: dict[str, Any] = {
        "schema_version": "open_duck_x5.t247_x5_context_route_reserved_screen_result.v1",
        "status": status,
        "date": preregistration["date"],
        "preregistration": receipt(PREREGISTRATION),
        "execution_package": receipt(args.execution_package),
        "git": {
            "commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "runner_source_commit": package["runner_source_commit"],
            "tracked_clean": not bool(tracked_status),
        },
        "source_checks": source_checks,
        "asset_receipts": asset_receipts,
        "variant_receipts": variant_receipts,
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
        "checks": checks,
        "checks_passed": sum(bool(value) for value in checks.values()),
        "checks_total": len(checks),
        "failed_checks": failed,
        "decision": (
            "EARN_T247_CONTEXT_ROUTE_PRODUCTION_INTEGRATION_PREREGISTRATION_ONLY"
            if not failed
            else "CLOSE_CONTEXT_ROUTE_SPECIALIZATION_WITHOUT_PRODUCTION_INTEGRATION"
        ),
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
            "production_integration_preregistration_earned": not failed,
            "production_integration_executed": False,
            "threshold_changed": False,
            "policy_training": False,
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
    output.write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(result, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
