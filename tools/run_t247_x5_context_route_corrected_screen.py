#!/usr/bin/env python3
"""Run the corrected preregistered no-device T247 X5 reserve screen."""

from __future__ import annotations

import argparse
import copy
import gc
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from open_duck_x5.winner_v13_state_coherent import CALIBRATION_TICKS  # noqa: E402
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
    / "t247_deployment_x5_context_route_corrected_screen_preregistration_20260731.json"
)
PREREGISTRATION_SHA256 = (
    "428a71cb16cf57b0bc85c826f700f3dc7102d9616114778551f79830d7ea080f"
)
EXPECTED_ROOT = Path("/home/sunrise/open_duck_x5_preflight/t247-context-route-v2")
EXPECTED_PACKAGE_STATUS = "SEALED_T247_X5_CONTEXT_ROUTE_CORRECTED_EXECUTION_PACKAGE"


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


def verify_execution_package(path: Path) -> tuple[dict[str, Any], dict[str, bool]]:
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT):
        raise RuntimeError("execution package must be a tracked repository artifact")
    package = json.loads(resolved.read_text(encoding="utf-8"))
    if package["status"] != EXPECTED_PACKAGE_STATUS:
        raise RuntimeError("corrected execution package is not sealed")
    if package["preregistration_file_sha256"] != PREREGISTRATION_SHA256:
        raise RuntimeError("execution package pins the wrong corrected preregistration")
    source_checks = {
        relative: sha256(ROOT / relative) == expected
        for relative, expected in package["source_sha256"].items()
    }
    if not source_checks or not all(source_checks.values()):
        raise RuntimeError(f"execution package source mismatch: {source_checks}")
    return package, source_checks


def platform_preflight(machine: str) -> tuple[dict[str, Any], dict[str, bool]]:
    scheduler = os.sched_getscheduler(0)
    priority = os.sched_getparam(0).sched_priority
    affinity = sorted(os.sched_getaffinity(0))
    isolated_text = Path("/sys/devices/system/cpu/isolated").read_text(
        encoding="utf-8"
    ).strip()
    governor = Path(
        "/sys/devices/system/cpu/cpu7/cpufreq/scaling_governor"
    ).read_text(encoding="utf-8").strip()
    values = {
        "machine": machine,
        "scheduler": scheduler,
        "priority": priority,
        "affinity": affinity,
        "isolated_cpus": isolated_text,
        "governor": governor,
    }
    checks = {
        "linux_aarch64": sys.platform.startswith("linux")
        and machine in {"aarch64", "arm64"},
        "sched_fifo": scheduler == os.SCHED_FIFO,
        "priority_80": priority == 80,
        "affinity_cpu7_only": affinity == [7],
        "cpu7_isolated": isolated_text == "7",
        "performance_governor": governor == "performance",
    }
    return values, checks


def runtime_preregistration(preregistration: dict[str, Any]) -> dict[str, Any]:
    runtime = copy.deepcopy(preregistration)
    witness = preregistration["architecture_specific_witness"]
    runtime["screen"]["expected_action_trace_sha256"] = witness[
        "action_trace_sha256"
    ]
    runtime["screen"]["expected_context_float32_bytes_sha256"] = witness[
        "calibration_context_float32_bytes_sha256"
    ]
    runtime["screen"]["expected_route"] = witness["expected_route"]
    return runtime


def main() -> int:
    args = parse_args()
    root = args.staging_root.resolve()
    if root != EXPECTED_ROOT:
        raise RuntimeError(f"unpreregistered corrected staging root: {root}")
    output = require_inside(args.output, root, "output")
    raw_output = require_inside(args.raw_output, root, "raw output")
    variant_root = require_inside(args.variant_root, root, "variant root")
    if output.exists() or raw_output.exists():
        raise FileExistsError("refusing to overwrite corrected T247 evidence")
    if sha256(PREREGISTRATION) != PREREGISTRATION_SHA256:
        raise RuntimeError("corrected T247 X5 preregistration changed")
    preregistration = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    runtime_prereg = runtime_preregistration(preregistration)
    package, source_checks = verify_execution_package(args.execution_package)
    tracked_status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        text=True,
    ).strip()
    if tracked_status:
        raise RuntimeError("corrected T247 X5 screen requires a clean repository")

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
            variant_root / f"policy.{route}.onnx", root, f"{route} variant"
        )
        for route in base.ROUTE_NAMES
    }
    variant_receipts = {route: receipt(path) for route, path in variant_paths.items()}
    variant_checks = {
        route: variant_receipts[route]["sha256"]
        == preregistration["derived_assets"]["routes"][route]
        for route in base.ROUTE_NAMES
    }
    if not all(asset_checks.values()) or not all(variant_checks.values()):
        raise RuntimeError(
            f"corrected T247 asset mismatch: assets={asset_checks} "
            f"variants={variant_checks}"
        )

    # Mandatory cold preflight: no graph session or measured output exists yet.
    machine = platform.machine().lower()
    preflight_values, preflight_checks = platform_preflight(machine)
    if not all(preflight_checks.values()):
        raise RuntimeError(
            "corrected T247 platform preflight failed before graph initialization: "
            f"values={preflight_values} checks={preflight_checks}"
        )

    descriptors_before = robot_descriptors(open_descriptors())
    modules_before = loaded_robot_modules()
    router = base.router_session(paths["router"])
    expected_route = runtime_prereg["screen"]["expected_route"]
    selected_variant = variant_paths[expected_route]
    selected_variant_sha256 = variant_receipts[expected_route]["sha256"]
    gc_was_enabled = gc.isenabled()
    gc.collect()
    gc.disable()
    try:
        semantic, semantic_raw = base.run_semantic_arm(
            paths,
            selected_variant,
            selected_variant_sha256,
            router,
            runtime_prereg,
        )
        timing, timing_raw = base.run_timing_arm(
            paths,
            selected_variant,
            selected_variant_sha256,
            router,
            runtime_prereg,
        )
    finally:
        if gc_was_enabled:
            gc.enable()
        else:
            gc.disable()
    descriptors_after = robot_descriptors(open_descriptors())
    modules_after = loaded_robot_modules()
    screen = runtime_prereg["screen"]
    limits = screen["reference_reserve_limits_ms"]
    stage_summary = timing["stage_locomotion"]

    checks = {
        "execution_package_sources_exact": all(source_checks.values()),
        "tracked_repository_clean": not bool(tracked_status),
        "asset_hashes_exact": all(asset_checks.values()),
        "all_six_variant_hashes_exact": all(variant_checks.values()),
        **preflight_checks,
        "semantic_all_ticks_byte_exact": semantic["mismatch"] is None,
        "semantic_exact_tick_counts": (
            semantic["calibration_ticks"] == CALIBRATION_TICKS
            and semantic["locomotion_ticks"] == screen["locomotion_ticks"]
        ),
        "semantic_exact_one_handoff": semantic["handoff_switches"] == 1,
        "semantic_exact_route_and_context": (
            semantic["selected_route"] == expected_route
            and semantic["context_float32_bytes_sha256"]
            == screen["expected_context_float32_bytes_sha256"]
        ),
        "semantic_trace_exact": semantic["original_action_trace_sha256"]
        == semantic["specialized_action_trace_sha256"]
        == screen["expected_action_trace_sha256"],
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
            timing["selected_route"] == expected_route
            and timing["context_float32_bytes_sha256"]
            == screen["expected_context_float32_bytes_sha256"]
        ),
        "timing_trace_exact": timing["action_trace_sha256"]
        == screen["expected_action_trace_sha256"],
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
    result: dict[str, Any] = {
        "schema_version": "open_duck_x5.t247_x5_context_route_corrected_screen_result.v1",
        "status": (
            "PASS_T247_X5_CONTEXT_ROUTE_CORRECTED_SCREEN"
            if not failed
            else "HOLD_T247_X5_CONTEXT_ROUTE_CORRECTED_SCREEN"
        ),
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
        "platform_preflight": {
            "values": preflight_values,
            "checks": preflight_checks,
            "passed_before_graph_initialization": True,
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
            else "CLOSE_CONTEXT_ROUTE_SPECIALIZATION"
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
    result["result_sha256"] = base.canonical_sha256(result)
    output.write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(result, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
