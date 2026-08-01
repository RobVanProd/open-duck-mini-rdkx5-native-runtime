#!/usr/bin/env python3
"""Run the preregistered no-device T247 X5 thread-CPU attribution."""

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

try:
    import resource
except ImportError:  # pragma: no cover - exercised only by non-POSIX import checks
    resource = None  # type: ignore[assignment]

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
    / "t247_deployment_x5_thread_cpu_attribution_preregistration_20260731.json"
)
PREREGISTRATION_SHA256 = (
    "72d78a7b1332509f9cc9a0eca465cc56a4e9918b83a8e87ba55fb47fc3f9a681"
)
EXPECTED_ROOT = Path(
    "/home/sunrise/open_duck_x5_preflight/t247-thread-cpu-attribution-v1"
)
EXPECTED_PACKAGE_STATUS = "SEALED_T247_X5_THREAD_CPU_ATTRIBUTION_EXECUTION_PACKAGE"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--execution-package", type=Path, required=True)
    parser.add_argument("--calibrator", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--router", type=Path, required=True)
    parser.add_argument("--variant", type=Path, required=True)
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
        raise RuntimeError("thread-CPU attribution execution package is not sealed")
    if package["preregistration_file_sha256"] != PREREGISTRATION_SHA256:
        raise RuntimeError("execution package pins the wrong preregistration")
    source_checks = {
        relative: sha256(ROOT / relative) == expected
        for relative, expected in package["source_sha256"].items()
    }
    if not source_checks or not all(source_checks.values()):
        raise RuntimeError(f"execution package source mismatch: {source_checks}")
    return package, source_checks


def platform_preflight(machine: str) -> tuple[dict[str, Any], dict[str, bool]]:
    values, checks = corrected.platform_preflight(machine)
    clock = time.get_clock_info("thread_time")
    values.update(
        {
            "thread_time_implementation": clock.implementation,
            "thread_time_monotonic": clock.monotonic,
            "thread_time_adjustable": clock.adjustable,
            "thread_time_resolution_ns": int(round(clock.resolution * 1_000_000_000)),
            "rusage_thread": getattr(resource, "RUSAGE_THREAD", None),
        }
    )
    checks.update(
        {
            "thread_time_ns_available": hasattr(time, "thread_time_ns"),
            "thread_time_monotonic": clock.monotonic,
            "thread_time_not_adjustable": not clock.adjustable,
            "rusage_thread_available": resource is not None
            and hasattr(resource, "RUSAGE_THREAD"),
        }
    )
    return values, checks


def _cpu_column_map(path: Path, *, softirq: bool) -> dict[str, int]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or "CPU7" not in lines[0].split():
        raise RuntimeError(f"{path} does not expose a CPU7 column")
    cpu_index = lines[0].split().index("CPU7")
    values: dict[str, int] = {}
    for line in lines[1:]:
        fields = line.split()
        if len(fields) <= cpu_index + 1:
            continue
        label = fields[0].rstrip(":")
        if not softirq and not label.isdigit():
            continue
        try:
            count = int(fields[cpu_index + 1])
        except ValueError:
            continue
        if softirq:
            key = label
        else:
            suffix = " ".join(fields[1 + len(lines[0].split()) :])
            key = f"irq{label}:{suffix}"
        values[key] = count
    return values


def _cpu7_stat() -> dict[str, int]:
    for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if fields and fields[0] == "cpu7":
            labels = (
                "user",
                "nice",
                "system",
                "idle",
                "iowait",
                "irq",
                "softirq",
                "steal",
                "guest",
                "guest_nice",
            )
            return {
                label: int(value)
                for label, value in zip(labels, fields[1:], strict=False)
            }
    raise RuntimeError("/proc/stat does not expose cpu7")


def system_counter_snapshot() -> dict[str, dict[str, int]]:
    return {
        "softirqs": _cpu_column_map(Path("/proc/softirqs"), softirq=True),
        "interrupts": _cpu_column_map(Path("/proc/interrupts"), softirq=False),
        "cpu_stat": _cpu7_stat(),
    }


def counter_delta(
    before: dict[str, dict[str, int]],
    after: dict[str, dict[str, int]],
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for family in sorted(set(before) | set(after)):
        left = before.get(family, {})
        right = after.get(family, {})
        result[family] = {
            key: int(right.get(key, 0) - left.get(key, 0))
            for key in sorted(set(left) | set(right))
            if right.get(key, 0) - left.get(key, 0) != 0
        }
    return result


def classify_attribution(
    stage_wall_ns: np.ndarray,
    stage_thread_cpu_ns: np.ndarray,
    *,
    slow_reference_ms: float,
) -> dict[str, Any]:
    wall = np.asarray(stage_wall_ns, dtype=np.int64)
    thread = np.asarray(stage_thread_cpu_ns, dtype=np.int64)
    if wall.ndim != 1 or thread.shape != wall.shape or wall.size == 0:
        raise ValueError("paired stage timing arrays must be non-empty one-dimensional peers")
    if bool(np.any(wall < 0)) or bool(np.any(thread < 0)):
        raise ValueError("paired stage timing arrays must be non-negative")
    threshold_ns = int(round(slow_reference_ms * 1_000_000.0))
    wall_slow = wall > threshold_ns
    thread_slow = thread > threshold_ns
    wall_slow_count = int(np.count_nonzero(wall_slow))
    thread_slow_count = int(np.count_nonzero(thread_slow))
    overlap_count = int(np.count_nonzero(wall_slow & thread_slow))
    not_thread_slow_fraction = (
        float((wall_slow_count - overlap_count) / wall_slow_count)
        if wall_slow_count
        else None
    )
    overlap_fraction = (
        float(overlap_count / wall_slow_count) if wall_slow_count else None
    )
    wall_summary = base.summary_ns(wall)
    thread_summary = base.summary_ns(thread)
    stolen = np.maximum(wall - thread, 0)
    if wall_slow_count == 0:
        classification = "NO_CURRENT_SLOW_POPULATION"
    elif (
        wall_summary["p99_ms"] > slow_reference_ms
        and thread_summary["p99_ms"] <= slow_reference_ms
        and not_thread_slow_fraction is not None
        and not_thread_slow_fraction >= 0.8
    ):
        classification = "KERNEL_OR_SCHEDULER_DOMINANT"
    elif (
        thread_summary["p99_ms"] > slow_reference_ms
        and overlap_fraction is not None
        and overlap_fraction >= 0.8
    ):
        classification = "SCHEDULED_COMPUTE_DOMINANT"
    else:
        classification = "MIXED"
    return {
        "classification": classification,
        "slow_reference_ms": slow_reference_ms,
        "stage_wall": wall_summary,
        "stage_thread_cpu": thread_summary,
        "stage_stolen": base.summary_ns(stolen),
        "wall_slow_ticks": wall_slow_count,
        "thread_slow_ticks": thread_slow_count,
        "wall_and_thread_slow_ticks": overlap_count,
        "wall_slow_not_thread_slow_fraction": not_thread_slow_fraction,
        "wall_slow_and_thread_slow_fraction": overlap_fraction,
        "thread_cpu_greater_than_wall_ticks": int(np.count_nonzero(thread > wall)),
    }


def run_attribution_arm(
    paths: dict[str, Path],
    variant_sha256: str,
    router: Any,
    preregistration: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    if resource is None or not hasattr(resource, "RUSAGE_THREAD"):
        raise RuntimeError("RUSAGE_THREAD is unavailable")
    host = base.build_host(
        paths,
        paths["variant"],
        variant_sha256,
        preregistration,
    )
    screen = preregistration["screen"]
    total_ticks = CALIBRATION_TICKS + int(screen["locomotion_ticks"])
    stage_wall_ns = np.empty(total_ticks, dtype=np.int64)
    stage_thread_cpu_ns = np.empty(total_ticks, dtype=np.int64)
    voluntary_switches = np.empty(total_ticks, dtype=np.int64)
    involuntary_switches = np.empty(total_ticks, dtype=np.int64)
    minor_faults = np.empty(total_ticks, dtype=np.int64)
    major_faults = np.empty(total_ticks, dtype=np.int64)
    release_lateness_ns = np.empty(total_ticks, dtype=np.int64)
    actions = np.empty((total_ticks, ACTION_DIM), dtype=np.float32)
    sample = base.samples(float(screen["command_x_m_s"]))
    offsets = sample["soft_offsets_rad"]
    host.bind_soft_offsets(offsets)
    maximum_rate_excess = 0.0
    selected_route: str | None = None
    context_sha256: str | None = None
    release_epoch = time.perf_counter_ns()
    counters_before = system_counter_snapshot()
    for tick in range(total_ticks):
        release_lateness_ns[tick] = base.wait_for_release(
            release_epoch + tick * CONTROL_PERIOD_NS
        )
        usage_before = resource.getrusage(resource.RUSAGE_THREAD)
        thread_started = time.thread_time_ns()
        wall_started = time.perf_counter_ns()
        base.stage(host, tick, sample)
        wall_finished = time.perf_counter_ns()
        thread_finished = time.thread_time_ns()
        usage_after = resource.getrusage(resource.RUSAGE_THREAD)
        stage_wall_ns[tick] = wall_finished - wall_started
        stage_thread_cpu_ns[tick] = thread_finished - thread_started
        voluntary_switches[tick] = usage_after.ru_nvcsw - usage_before.ru_nvcsw
        involuntary_switches[tick] = usage_after.ru_nivcsw - usage_before.ru_nivcsw
        minor_faults[tick] = usage_after.ru_minflt - usage_before.ru_minflt
        major_faults[tick] = usage_after.ru_majflt - usage_before.ru_majflt
        np.copyto(actions[tick], host.normalized_action_view)
        maximum_rate_excess = max(
            maximum_rate_excess,
            float(np.max(host.target_pipeline.graph_rate_excess_rad_s)),
        )
        host.complete_send(write_succeeded=True)
        if tick + 1 == CALIBRATION_TICKS:
            host.confirm_calibration_handoff(True)
            context = host.calibration_context
            context_sha256 = hashlib.sha256(context.tobytes()).hexdigest()
            selected_route = base.select_route(router, context)
    counters_after = system_counter_snapshot()
    locomotion = slice(CALIBRATION_TICKS, None)
    attribution = classify_attribution(
        stage_wall_ns[locomotion],
        stage_thread_cpu_ns[locomotion],
        slow_reference_ms=float(screen["slow_tick_reference_ms"]),
    )
    arm = {
        "id": "paced_t247_wall_vs_thread_cpu_attribution",
        "calibration_ticks": host.confirmed_calibration_ticks,
        "locomotion_ticks": host.confirmed_locomotion_ticks,
        "selected_route": selected_route,
        "context_float32_bytes_sha256": context_sha256,
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
        "release_lateness": base.summary_ns(release_lateness_ns),
        "attribution": attribution,
        "rusage_locomotion_totals": {
            "voluntary_context_switches": int(np.sum(voluntary_switches[locomotion])),
            "involuntary_context_switches": int(
                np.sum(involuntary_switches[locomotion])
            ),
            "minor_faults": int(np.sum(minor_faults[locomotion])),
            "major_faults": int(np.sum(major_faults[locomotion])),
        },
        "system_counters_before": counters_before,
        "system_counters_after": counters_after,
        "system_counter_delta": counter_delta(counters_before, counters_after),
        "selection_weight": 0,
    }
    raw = {
        "stage_wall_ns": stage_wall_ns,
        "stage_thread_cpu_ns": stage_thread_cpu_ns,
        "voluntary_context_switches": voluntary_switches,
        "involuntary_context_switches": involuntary_switches,
        "minor_faults": minor_faults,
        "major_faults": major_faults,
        "release_lateness_ns": release_lateness_ns,
        "actions": actions,
    }
    return arm, raw


def main() -> int:
    args = parse_args()
    root = args.staging_root.resolve()
    if root != EXPECTED_ROOT:
        raise RuntimeError(f"unpreregistered attribution staging root: {root}")
    output = require_inside(args.output, root, "output")
    raw_output = require_inside(args.raw_output, root, "raw output")
    if output.exists() or raw_output.exists():
        raise FileExistsError("refusing to overwrite T247 attribution evidence")
    if sha256(PREREGISTRATION) != PREREGISTRATION_SHA256:
        raise RuntimeError("T247 thread-CPU attribution preregistration changed")
    preregistration = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    runtime_prereg = corrected.runtime_preregistration(preregistration)
    package, source_checks = verify_execution_package(args.execution_package)
    tracked_status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        text=True,
    ).strip()
    if tracked_status:
        raise RuntimeError("T247 thread-CPU attribution requires a clean repository")

    paths = {
        "calibrator": require_inside(args.calibrator, root, "calibrator"),
        "policy": require_inside(args.policy, root, "policy"),
        "router": require_inside(args.router, root, "router"),
        "variant": require_inside(args.variant, root, "variant"),
        "p30_fit": require_inside(args.p30_fit, root, "P30 fit"),
        "reference_table": require_inside(
            args.reference_table, root, "reference table"
        ),
    }
    assets = preregistration["unchanged_assets"]
    expected_hashes = {
        "calibrator": assets["calibrator_sha256"],
        "policy": assets["deployment_policy_sha256"],
        "router": assets["context_router_sha256"],
        "variant": assets["lower_cond0_variant_sha256"],
        "p30_fit": assets["fixed_p30_runtime_observer_fit_sha256"],
        "reference_table": assets["projected_reference_table_sha256"],
    }
    asset_receipts = {name: receipt(path) for name, path in paths.items()}
    asset_checks = {
        name: asset_receipts[name]["sha256"] == expected
        for name, expected in expected_hashes.items()
    }
    if not all(asset_checks.values()):
        raise RuntimeError(f"T247 attribution asset mismatch: {asset_checks}")

    machine = platform.machine().lower()
    preflight_values, preflight_checks = platform_preflight(machine)
    if not all(preflight_checks.values()):
        raise RuntimeError(
            "T247 attribution platform preflight failed before graph initialization: "
            f"values={preflight_values} checks={preflight_checks}"
        )

    descriptors_before = robot_descriptors(open_descriptors())
    modules_before = loaded_robot_modules()
    router = base.router_session(paths["router"])
    gc_was_enabled = gc.isenabled()
    gc.collect()
    gc.disable()
    try:
        arm, raw = run_attribution_arm(
            paths,
            assets["lower_cond0_variant_sha256"],
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
    classification = arm["attribution"]["classification"]
    checks = {
        "execution_package_sources_exact": all(source_checks.values()),
        "tracked_repository_clean": not bool(tracked_status),
        "asset_hashes_exact": all(asset_checks.values()),
        **preflight_checks,
        "exact_tick_counts": (
            arm["calibration_ticks"] == CALIBRATION_TICKS
            and arm["locomotion_ticks"] == screen["locomotion_ticks"]
        ),
        "exact_route_and_context": (
            arm["selected_route"] == screen["expected_route"]
            and arm["context_float32_bytes_sha256"]
            == screen["expected_context_float32_bytes_sha256"]
        ),
        "action_trace_exact": (
            arm["action_trace_sha256"] == screen["expected_action_trace_sha256"]
        ),
        "zero_rate_excess": arm["maximum_rate_excess_rad_s"] == 0.0,
        "offsets_immutable_identity_bound": arm[
            "offsets_immutable_and_identity_bound"
        ],
        "locomotion_target_alias": arm["locomotion_desired_sent_buffer_alias"],
        "paired_arrays_complete": all(
            value.shape[0] == CALIBRATION_TICKS + screen["locomotion_ticks"]
            for value in raw.values()
        ),
        "paired_durations_nonnegative": bool(
            np.all(raw["stage_wall_ns"] >= 0)
            and np.all(raw["stage_thread_cpu_ns"] >= 0)
        ),
        "classification_complete": classification
        in {
            "KERNEL_OR_SCHEDULER_DOMINANT",
            "SCHEDULED_COMPUTE_DOMINANT",
            "MIXED",
            "NO_CURRENT_SLOW_POPULATION",
        },
        "no_robot_descriptors": not descriptors_before and not descriptors_after,
        "no_robot_modules": not modules_before and not modules_after,
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    next_by_classification = {
        "KERNEL_OR_SCHEDULER_DOMINANT": (
            "SELECT_READ_ONLY_KERNEL_HOUSEKEEPING_OPTIONS_AUDIT"
        ),
        "SCHEDULED_COMPUTE_DOMINANT": (
            "SELECT_READ_ONLY_STATIC_CONTEXT_VALUE_PARTIAL_EVALUATION_AUDIT"
        ),
        "MIXED": "SELECT_COMPONENT_TIMELINE_INSTRUMENTATION",
        "NO_CURRENT_SLOW_POPULATION": "FILE_INCONCLUSIVE_WITHOUT_RERUN",
    }
    result: dict[str, Any] = {
        "schema_version": "open_duck_x5.t247_x5_thread_cpu_attribution_result.v1",
        "status": (
            "COMPLETE_T247_X5_THREAD_CPU_ATTRIBUTION"
            if not failed
            else "INVALID_T247_X5_THREAD_CPU_ATTRIBUTION"
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
        "platform_preflight": {
            "values": preflight_values,
            "checks": preflight_checks,
            "passed_before_graph_initialization": True,
        },
        "arm": arm,
        "checks": checks,
        "checks_passed": sum(bool(value) for value in checks.values()),
        "checks_total": len(checks),
        "failed_checks": failed,
        "classification": classification if not failed else None,
        "decision": (
            next_by_classification[classification]
            if not failed
            else "INVALID_DIAGNOSTIC_NO_MECHANISM_SELECTED"
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
            "selection_weight": 0,
            "context_route_specialization_reopened": False,
            "reserve_pass_claim": False,
            "boot_change": False,
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
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(raw_output, **raw)
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
