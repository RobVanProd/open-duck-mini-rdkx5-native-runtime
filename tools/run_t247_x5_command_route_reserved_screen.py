#!/usr/bin/env python3
"""Run the preregistered no-device T247 command-route X5 screen."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
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
from open_duck_x5.winner_v13_state_coherent import CALIBRATION_TICKS  # noqa: E402
from tools import run_t247_x5_context_route_corrected_screen as corrected  # noqa: E402
from tools import run_t247_x5_context_route_reserved_screen as base  # noqa: E402
from tools.run_winner_v14_x5_paced_screen import (  # noqa: E402
    loaded_robot_modules,
    open_descriptors,
    receipt,
    require_inside,
    robot_descriptors,
    sha256,
)

PREREGISTRATION = (
    ROOT
    / "artifacts"
    / "gates"
    / "phase_5_policy"
    / "t247_deployment_x5_command_route_reserved_screen_preregistration_20260801.json"
)
PREREGISTRATION_SHA256 = "cdda6d2a277b70942f253dacbc799acf279bbe24443f187f09602bbf3d38479b"
EXPECTED_ROOT = Path("/home/sunrise/open_duck_x5_preflight/t247-command-route-v1")
EXPECTED_PACKAGE_STATUS = "SEALED_T247_X5_COMMAND_ROUTE_EXECUTION_PACKAGE"
LOCOMOTION_TICKS = 2048
TOTAL_TICKS = CALIBRATION_TICKS + LOCOMOTION_TICKS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--execution-package", type=Path, required=True)
    parser.add_argument("--calibrator", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--router", type=Path, required=True)
    parser.add_argument("--source-variant", type=Path, required=True)
    parser.add_argument("--x000-variant", type=Path, required=True)
    parser.add_argument("--x080-variant", type=Path, required=True)
    parser.add_argument("--command-manifest", type=Path, required=True)
    parser.add_argument("--p30-fit", type=Path, required=True)
    parser.add_argument("--reference-table", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path, required=True)
    return parser.parse_args()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verify_execution_package(path: Path) -> tuple[dict[str, Any], dict[str, bool]]:
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT):
        raise RuntimeError("execution package must be a tracked repository artifact")
    package = json.loads(resolved.read_text(encoding="utf-8"))
    if package["status"] != EXPECTED_PACKAGE_STATUS:
        raise RuntimeError("command-route execution package is not sealed")
    if package["preregistration_file_sha256"] != PREREGISTRATION_SHA256:
        raise RuntimeError("execution package pins the wrong preregistration")
    checks = {
        relative: sha256(ROOT / relative) == expected
        for relative, expected in package["source_sha256"].items()
    }
    if not checks or not all(checks.values()):
        raise RuntimeError(f"execution package source mismatch: {checks}")
    return package, checks


def runtime_preregistration(preregistration: dict[str, Any]) -> dict[str, Any]:
    assets = preregistration["assets"]
    return {
        "unchanged_assets": {
            "calibrator_sha256": assets["calibrator_sha256"],
            "fixed_p30_runtime_observer_fit_sha256": assets["p30_fit_sha256"],
            "projected_reference_table_sha256": assets["reference_table_sha256"],
        }
    }


def _context_evidence(host: Any, router: Any) -> tuple[str, str]:
    context = host.calibration_context
    return (
        base.select_route(router, context),
        hashlib.sha256(context.tobytes()).hexdigest(),
    )


def run_semantic_arm(
    *,
    command: float,
    paths: dict[str, Path],
    candidate_path: Path,
    candidate_sha256: str,
    router: Any,
    preregistration: dict[str, Any],
) -> dict[str, Any]:
    runtime = runtime_preregistration(preregistration)
    source = base.build_host(
        paths,
        paths["source_variant"],
        preregistration["assets"]["source_lower_cond0_sha256"],
        runtime,
    )
    candidate = base.build_host(
        paths,
        candidate_path,
        candidate_sha256,
        runtime,
    )
    sample = base.samples(command)
    offsets = sample["soft_offsets_rad"]
    source.bind_soft_offsets(offsets)
    candidate.bind_soft_offsets(offsets)
    source_actions = np.empty((TOTAL_TICKS, ACTION_DIM), dtype=np.float32)
    candidate_actions = np.empty_like(source_actions)
    maximum_rate_excess = 0.0
    route: str | None = None
    context_sha256: str | None = None
    for tick in range(TOTAL_TICKS):
        base.stage(source, tick, sample)
        base.stage(candidate, tick, sample)
        mismatch = base.mismatch(source, candidate, committed=False)
        if mismatch is not None:
            raise RuntimeError(f"command {command} staged mismatch: {mismatch}")
        np.copyto(source_actions[tick], source.normalized_action_view)
        np.copyto(candidate_actions[tick], candidate.normalized_action_view)
        maximum_rate_excess = max(
            maximum_rate_excess,
            float(np.max(candidate.target_pipeline.graph_rate_excess_rad_s)),
        )
        source.complete_send(write_succeeded=True)
        candidate.complete_send(write_succeeded=True)
        mismatch = base.mismatch(source, candidate, committed=True)
        if mismatch is not None:
            raise RuntimeError(f"command {command} committed mismatch: {mismatch}")
        if tick + 1 == CALIBRATION_TICKS:
            source.confirm_calibration_handoff(True)
            candidate.confirm_calibration_handoff(True)
            source_route, source_context = _context_evidence(source, router)
            candidate_route, candidate_context = _context_evidence(candidate, router)
            if (source_route, source_context) != (candidate_route, candidate_context):
                raise RuntimeError("source and command candidate handoffs differ")
            route, context_sha256 = source_route, source_context
    if not np.array_equal(source_actions, candidate_actions):
        raise RuntimeError(f"command {command} action traces differ")
    return {
        "command_x_m_s": command,
        "calibration_ticks": source.confirmed_calibration_ticks,
        "locomotion_ticks": source.confirmed_locomotion_ticks,
        "handoff_switches": 1,
        "selected_route": route,
        "context_float32_bytes_sha256": context_sha256,
        "source_action_trace_sha256": hashlib.sha256(source_actions.tobytes()).hexdigest(),
        "candidate_action_trace_sha256": hashlib.sha256(candidate_actions.tobytes()).hexdigest(),
        "all_ticks_byte_exact": True,
        "maximum_rate_excess_rad_s": maximum_rate_excess,
        "offsets_immutable_and_identity_bound": (
            not offsets.flags.writeable and candidate.target_pipeline._trusted_offsets is offsets
        ),
        "locomotion_desired_sent_buffer_alias": (
            candidate.target_pipeline.desired_logical_target_rad
            is candidate.target_pipeline.sent_logical_target_rad
        ),
    }


def run_timing_arm(
    *,
    command: float,
    paths: dict[str, Path],
    candidate_path: Path,
    candidate_sha256: str,
    router: Any,
    preregistration: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    host = base.build_host(
        paths,
        candidate_path,
        candidate_sha256,
        runtime_preregistration(preregistration),
    )
    sample = base.samples(command)
    offsets = sample["soft_offsets_rad"]
    host.bind_soft_offsets(offsets)
    stage_ns = np.empty(TOTAL_TICKS, dtype=np.int64)
    release_lateness_ns = np.empty(TOTAL_TICKS, dtype=np.int64)
    actions = np.empty((TOTAL_TICKS, ACTION_DIM), dtype=np.float32)
    maximum_rate_excess = 0.0
    route: str | None = None
    context_sha256: str | None = None
    release_epoch = time.perf_counter_ns()
    for tick in range(TOTAL_TICKS):
        release_lateness_ns[tick] = base.wait_for_release(release_epoch + tick * CONTROL_PERIOD_NS)
        started = time.perf_counter_ns()
        base.stage(host, tick, sample)
        stage_ns[tick] = time.perf_counter_ns() - started
        np.copyto(actions[tick], host.normalized_action_view)
        maximum_rate_excess = max(
            maximum_rate_excess,
            float(np.max(host.target_pipeline.graph_rate_excess_rad_s)),
        )
        host.complete_send(write_succeeded=True)
        if tick + 1 == CALIBRATION_TICKS:
            host.confirm_calibration_handoff(True)
            route, context_sha256 = _context_evidence(host, router)
    locomotion = slice(CALIBRATION_TICKS, None)
    return (
        {
            "command_x_m_s": command,
            "calibration_ticks": host.confirmed_calibration_ticks,
            "locomotion_ticks": host.confirmed_locomotion_ticks,
            "handoff_switches": 1,
            "selected_route": route,
            "context_float32_bytes_sha256": context_sha256,
            "action_trace_sha256": hashlib.sha256(actions.tobytes()).hexdigest(),
            "maximum_rate_excess_rad_s": maximum_rate_excess,
            "stage_locomotion_ms": base.summary_ns(stage_ns[locomotion]),
            "release_lateness_ms": base.summary_ns(release_lateness_ns),
            "offsets_immutable_and_identity_bound": (
                not offsets.flags.writeable and host.target_pipeline._trusted_offsets is offsets
            ),
            "locomotion_desired_sent_buffer_alias": (
                host.target_pipeline.desired_logical_target_rad
                is host.target_pipeline.sent_logical_target_rad
            ),
        },
        {
            "stage_ns": stage_ns,
            "release_lateness_ns": release_lateness_ns,
            "actions": actions,
        },
    )


def _timing_checks(
    arm_id: str,
    timing: dict[str, Any],
    limits: dict[str, float],
) -> dict[str, bool]:
    stage = timing["stage_locomotion_ms"]
    return {
        f"{arm_id}_stage_p99_within_reserve": stage["p99_ms"] <= limits["p99"],
        f"{arm_id}_stage_p99_9_within_reserve": stage["p99_9_ms"] <= limits["p99_9"],
        f"{arm_id}_stage_max_within_reserve": stage["max_ms"] <= limits["max"],
    }


def main() -> int:
    args = parse_args()
    root = args.staging_root.resolve()
    if root != EXPECTED_ROOT:
        raise RuntimeError(f"unpreregistered command-route staging root: {root}")
    output = require_inside(args.output, root, "output")
    raw_output = require_inside(args.raw_output, root, "raw output")
    if output.exists() or raw_output.exists():
        raise FileExistsError("refusing to overwrite command-route X5 evidence")
    if sha256(PREREGISTRATION) != PREREGISTRATION_SHA256:
        raise RuntimeError("command-route X5 preregistration changed")
    preregistration = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    package, source_checks = verify_execution_package(args.execution_package)
    tracked_status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        text=True,
    ).strip()
    if tracked_status:
        raise RuntimeError("command-route X5 screen requires a clean repository")

    paths = {
        "calibrator": require_inside(args.calibrator, root, "calibrator"),
        "policy": require_inside(args.policy, root, "policy"),
        "router": require_inside(args.router, root, "router"),
        "source_variant": require_inside(args.source_variant, root, "source variant"),
        "x000_variant": require_inside(args.x000_variant, root, "x000 variant"),
        "x080_variant": require_inside(args.x080_variant, root, "x080 variant"),
        "command_manifest": require_inside(args.command_manifest, root, "command manifest"),
        "p30_fit": require_inside(args.p30_fit, root, "P30 fit"),
        "reference_table": require_inside(args.reference_table, root, "reference table"),
    }
    assets = preregistration["assets"]
    expected_hashes = {
        "calibrator": assets["calibrator_sha256"],
        "policy": assets["deployment_policy_sha256"],
        "router": assets["context_router_sha256"],
        "source_variant": assets["source_lower_cond0_sha256"],
        "x000_variant": assets["lower_cond0_x000_sha256"],
        "x080_variant": assets["lower_cond0_x080_sha256"],
        "command_manifest": assets["command_variant_manifest_sha256"],
        "p30_fit": assets["p30_fit_sha256"],
        "reference_table": assets["reference_table_sha256"],
    }
    asset_receipts = {name: receipt(path) for name, path in paths.items()}
    asset_checks = {
        name: asset_receipts[name]["sha256"] == expected
        for name, expected in expected_hashes.items()
    }
    if not all(asset_checks.values()):
        raise RuntimeError(f"command-route X5 asset mismatch: {asset_checks}")

    preflight_values, preflight_checks = corrected.platform_preflight(platform.machine().lower())
    if not all(preflight_checks.values()):
        raise RuntimeError(
            "command-route X5 platform preflight failed before graph initialization: "
            f"values={preflight_values} checks={preflight_checks}"
        )
    descriptors_before = robot_descriptors(open_descriptors())
    modules_before = loaded_robot_modules()
    router = base.router_session(paths["router"])

    semantic: dict[str, Any] = {}
    timing: dict[str, Any] = {}
    raw: dict[str, np.ndarray] = {}
    gc_was_enabled = gc.isenabled()
    gc.collect()
    gc.disable()
    try:
        for arm in preregistration["screen"]["arms"]:
            arm_id = arm["id"]
            command = float(arm["command_x_m_s"])
            variant_key = "x000_variant" if command == 0.0 else "x080_variant"
            candidate_path = paths[variant_key]
            candidate_sha256 = expected_hashes[variant_key]
            semantic[arm_id] = run_semantic_arm(
                command=command,
                paths=paths,
                candidate_path=candidate_path,
                candidate_sha256=candidate_sha256,
                router=router,
                preregistration=preregistration,
            )
            timing[arm_id], raw_arm = run_timing_arm(
                command=command,
                paths=paths,
                candidate_path=candidate_path,
                candidate_sha256=candidate_sha256,
                router=router,
                preregistration=preregistration,
            )
            for name, value in raw_arm.items():
                raw[f"{arm_id}_{name}"] = value
    finally:
        if gc_was_enabled:
            gc.enable()
        else:
            gc.disable()
    descriptors_after = robot_descriptors(open_descriptors())
    modules_after = loaded_robot_modules()

    expected_route = preregistration["screen"]["expected_route"]
    expected_context = preregistration["screen"]["expected_context_float32_bytes_sha256"]
    semantic_checks: dict[str, bool] = {}
    timing_semantic_checks: dict[str, bool] = {}
    for arm in preregistration["screen"]["arms"]:
        arm_id = arm["id"]
        semantic_arm = semantic[arm_id]
        timing_arm = timing[arm_id]
        semantic_checks.update(
            {
                f"{arm_id}_semantic_tick_counts": (
                    semantic_arm["calibration_ticks"] == CALIBRATION_TICKS
                    and semantic_arm["locomotion_ticks"] == LOCOMOTION_TICKS
                ),
                f"{arm_id}_semantic_route_context": (
                    semantic_arm["selected_route"] == expected_route
                    and semantic_arm["context_float32_bytes_sha256"] == expected_context
                ),
                f"{arm_id}_semantic_byte_exact": semantic_arm["all_ticks_byte_exact"],
                f"{arm_id}_semantic_zero_rate_excess": semantic_arm["maximum_rate_excess_rad_s"]
                == 0.0,
            }
        )
        timing_semantic_checks.update(
            {
                f"{arm_id}_timing_tick_counts": (
                    timing_arm["calibration_ticks"] == CALIBRATION_TICKS
                    and timing_arm["locomotion_ticks"] == LOCOMOTION_TICKS
                ),
                f"{arm_id}_timing_route_context": (
                    timing_arm["selected_route"] == expected_route
                    and timing_arm["context_float32_bytes_sha256"] == expected_context
                ),
                f"{arm_id}_timing_trace_exact": timing_arm["action_trace_sha256"]
                == semantic_arm["candidate_action_trace_sha256"],
                f"{arm_id}_timing_zero_rate_excess": timing_arm["maximum_rate_excess_rad_s"] == 0.0,
                f"{arm_id}_offset_and_target_identity": (
                    timing_arm["offsets_immutable_and_identity_bound"]
                    and timing_arm["locomotion_desired_sent_buffer_alias"]
                ),
            }
        )
    limits = preregistration["screen"]["reserve_limits_ms"]
    timing_checks: dict[str, bool] = {}
    for arm in preregistration["screen"]["arms"]:
        timing_checks.update(_timing_checks(arm["id"], timing[arm["id"]], limits))
    validity_checks = {
        "execution_package_sources_exact": all(source_checks.values()),
        "tracked_repository_clean": not bool(tracked_status),
        "asset_hashes_exact": all(asset_checks.values()),
        **preflight_checks,
        **semantic_checks,
        **timing_semantic_checks,
        "no_robot_descriptors": not descriptors_before and not descriptors_after,
        "no_robot_modules": not modules_before and not modules_after,
    }
    checks = {**validity_checks, **timing_checks}
    failed = sorted(name for name, passed in checks.items() if not passed)
    valid = all(validity_checks.values())
    timing_pass = all(timing_checks.values())
    if not valid:
        status = "INVALID_T247_X5_COMMAND_ROUTE_RESERVED_SCREEN"
        decision = "INVALID_SCREEN_NO_MECHANISM_DECISION"
    elif timing_pass:
        status = "PASS_T247_X5_COMMAND_ROUTE_RESERVED_SCREEN"
        decision = "EARN_OPT_IN_PRODUCTION_COMMAND_ROUTE_HOST_CONTRACT_AND_GATE5_READINESS_AUDIT"
    else:
        status = "HOLD_T247_X5_COMMAND_ROUTE_RESERVED_SCREEN"
        decision = "CLOSE_COMMAND_ROUTE_SPECIALIZATION_WITHOUT_RETRY"

    result: dict[str, Any] = {
        "schema_version": "open_duck_x5.t247_x5_command_route_reserved_screen_result.v1",
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
        "asset_receipts": asset_receipts,
        "platform_preflight": {
            "values": preflight_values,
            "checks": preflight_checks,
            "passed_before_graph_initialization": True,
        },
        "semantic": semantic,
        "timing": timing,
        "reserve_limits_ms": limits,
        "checks": checks,
        "checks_passed": sum(bool(value) for value in checks.values()),
        "checks_total": len(checks),
        "failed_checks": failed,
        "decision": decision,
        "device_evidence": {
            "robot_descriptors_before": descriptors_before,
            "robot_descriptors_after": descriptors_after,
            "robot_modules_before": modules_before,
            "robot_modules_after": modules_after,
            "serial_gpio_i2c_controller_or_torque_access": False,
        },
        "authority": {
            "selection_weight": 0,
            "retry": False,
            "threshold_changed": False,
            "policy_training": False,
            "policy_deployed": False,
            "production_integration": False,
            "serial_bus": False,
            "sensors": False,
            "torque": False,
            "motion": False,
            "gate5": False,
        },
    }
    result["result_sha256"] = canonical_sha256(result)
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    np.savez(raw_output, **raw)
    result["raw_output"] = receipt(raw_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(result, indent=2))
    return 0 if valid and timing_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
