#!/usr/bin/env python3
"""Run the preregistered T251A2 no-motion optimized X5 paced screen."""

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

from open_duck_x5.constants import ACTION_DIM, CONTROL_PERIOD_NS, HOME_RAD  # noqa: E402
from open_duck_x5.winner_v13_state_coherent import (  # noqa: E402
    CALIBRATION_TICKS,
    GraphAsset,
    GraphSpec,
    P30FitAsset,
    TensorSpec,
    WinnerV13StateCoherentTransaction,
)
from tools.winner_v14_optimized import (  # noqa: E402
    WinnerV14X5OptimizedTransaction,
)

PREREGISTRATION = (
    ROOT
    / "artifacts"
    / "gates"
    / "phase_5_policy"
    / "t251a2_x5_optimized_paced_screen_preregistration_20260731.json"
)
PREREGISTRATION_SHA256 = "cd9e71c724087f1ecffa4e4d6f0c462df3780b64a6723d094bcfab60692b1ebc"
EXPECTED_ROOT = Path("/home/sunrise/open_duck_x5_preflight/t251a2")
ROBOT_MODULES = {
    "pygame",
    "serial",
    "smbus2",
    "open_duck_x5.runtime",
    "open_duck_x5.servo_bus",
    "open_duck_x5.sensors",
}
ROBOT_DEVICE_PREFIXES = (
    "/dev/gpiochip",
    "/dev/i2c-",
    "/dev/input/",
    "/dev/ttyACM",
    "/dev/ttyCH",
    "/dev/ttyS",
    "/dev/ttyUSB",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
    milliseconds = np.asarray(values, dtype=np.float64) / 1_000_000.0
    return {
        "samples": int(milliseconds.size),
        "min_ms": float(np.min(milliseconds)),
        "mean_ms": float(np.mean(milliseconds)),
        "p50_ms": float(np.percentile(milliseconds, 50)),
        "p95_ms": float(np.percentile(milliseconds, 95)),
        "p99_ms": float(np.percentile(milliseconds, 99)),
        "p99_9_ms": float(np.percentile(milliseconds, 99.9)),
        "max_ms": float(np.max(milliseconds)),
    }


def calibrator_spec() -> GraphSpec:
    return GraphSpec(
        observation=TensorSpec("obs", (1, 115)),
        previous_action=TensorSpec("previous_action", (1, 14)),
        hidden_in=TensorSpec("h_in", (1, 64)),
        action=TensorSpec("calibration_actions", (1, 14)),
        previous_action_out=TensorSpec("previous_action_out", (1, 14)),
        hidden_out=TensorSpec("h_out", (1, 64)),
    )


def locomotion_spec() -> GraphSpec:
    return GraphSpec(
        observation=TensorSpec("obs", (1, 115)),
        previous_action=TensorSpec("previous_action", (1, 14)),
        hidden_in=TensorSpec("h_in", (1, 64)),
        calibration_context=TensorSpec("calibration_context", (1, 64)),
        action=TensorSpec("continuous_actions", (1, 14)),
        previous_action_out=TensorSpec("previous_action_out", (1, 14)),
        hidden_out=TensorSpec("h_out", (1, 64)),
    )


def open_descriptors() -> dict[str, str]:
    values: dict[str, str] = {}
    for path in sorted(Path("/proc/self/fd").iterdir(), key=lambda value: int(value.name)):
        try:
            values[path.name] = os.readlink(path)
        except FileNotFoundError:
            continue
    return values


def robot_descriptors(values: dict[str, str]) -> dict[str, str]:
    return {
        descriptor: target
        for descriptor, target in values.items()
        if target.startswith(ROBOT_DEVICE_PREFIXES)
    }


def loaded_robot_modules() -> list[str]:
    return sorted(
        name
        for name in sys.modules
        if any(name == root or name.startswith(root + ".") for root in ROBOT_MODULES)
    )


def require_inside(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise RuntimeError(f"{label} is outside isolated staging root: {resolved}")
    return resolved


def build_host(
    host_type: type[WinnerV13StateCoherentTransaction],
    paths: dict[str, Path],
    prereg: dict[str, Any],
) -> WinnerV13StateCoherentTransaction:
    assets = prereg["unchanged_assets"]
    return host_type(
        calibrator=GraphAsset(
            paths["calibrator"],
            calibrator_spec(),
            frozenset({assets["calibrator_sha256"]}),
        ),
        locomotion=GraphAsset(
            paths["deployment_policy"],
            locomotion_spec(),
            frozenset({assets["deployment_policy_sha256"]}),
        ),
        p30_fit=P30FitAsset(
            paths["fixed_p30_runtime_observer_fit"],
            frozenset({assets["fixed_p30_runtime_observer_fit_sha256"]}),
        ),
        reference_table_path=paths["projected_reference_table"],
        enabled=True,
        warmup_runs=int(prereg["screen"]["warmup_runs_per_graph"]),
    )


def samples(command_x: float) -> dict[str, Any]:
    command = np.zeros(7, dtype=np.float64)
    command[0] = command_x
    return {
        "gyro_rad_s": np.zeros(3, dtype=np.float64),
        "acceleration_m_s2": np.asarray([0.0, 0.0, 9.81], dtype=np.float64),
        "commands": command,
        "positions_rad": HOME_RAD.copy(),
        "velocities_rad_s": np.zeros(ACTION_DIM, dtype=np.float64),
        "foot_contacts": np.ones(2, dtype=np.float64),
        "servo_stale": np.zeros(ACTION_DIM, dtype=np.bool_),
        "imu_stale": False,
        "contacts_stale": False,
        "soft_offsets_rad": np.linspace(-0.001, 0.001, ACTION_DIM, dtype=np.float64),
    }


def stage(
    host: WinnerV13StateCoherentTransaction,
    tick: int,
    sample: dict[str, Any],
) -> np.ndarray:
    return host.stage_tick(
        tick_index=tick,
        logical_period_ns=CONTROL_PERIOD_NS,
        servo_sample_tick_index=tick,
        imu_sample_tick_index=tick,
        contacts_sample_tick_index=tick,
        **sample,
    )


def exact_state_pairs(
    baseline: WinnerV13StateCoherentTransaction,
    optimized: WinnerV13StateCoherentTransaction,
    *,
    committed: bool,
) -> tuple[tuple[str, np.ndarray, np.ndarray], ...]:
    pairs = (
        ("observation", baseline.observation_view, optimized.observation_view),
        ("action", baseline.normalized_action_view, optimized.normalized_action_view),
        ("logical_target", baseline.logical_target_view, optimized.logical_target_view),
        ("physical_target", baseline.physical_target_view, optimized.physical_target_view),
        (
            "calibrator_hidden_out",
            baseline._calibrator._hidden_out,
            optimized._calibrator._hidden_out,
        ),
        (
            "locomotion_hidden_out",
            baseline._locomotion._hidden_out,
            optimized._locomotion._hidden_out,
        ),
        (
            "calibrator_previous_action_out",
            baseline._calibrator._previous_action_out,
            optimized._calibrator._previous_action_out,
        ),
        (
            "locomotion_previous_action_out",
            baseline._locomotion._previous_action_out,
            optimized._locomotion._previous_action_out,
        ),
    )
    if not committed:
        return pairs
    return pairs + (("observer", baseline.observer.value_view, optimized.observer.value_view),)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the T251A2 no-motion paced screen")
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--calibrator", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--p30-fit", type=Path, required=True)
    parser.add_argument("--reference-table", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.staging_root.resolve()
    if root != EXPECTED_ROOT:
        raise RuntimeError(f"unpreregistered staging root: {root}")
    output = require_inside(args.output, root, "output")
    raw_output = require_inside(args.raw_output, root, "raw output")
    if output.exists() or raw_output.exists():
        raise FileExistsError("refusing to overwrite T251A2 output")
    machine = platform.machine().lower()
    if not sys.platform.startswith("linux") or machine not in {"aarch64", "arm64"}:
        raise RuntimeError("T251A2 requires aarch64 Linux")
    if sha256(PREREGISTRATION) != PREREGISTRATION_SHA256:
        raise RuntimeError("T251A2 preregistration changed")
    prereg = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    implementation = prereg["implementation"]
    source_paths = {
        "baseline": ROOT / implementation["baseline_source"],
        "optimized": ROOT / implementation["optimized_source"],
    }
    source_checks = {
        name: sha256(path) == implementation[f"{name}_source_sha256"]
        for name, path in source_paths.items()
    }
    tracked_status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        text=True,
    ).strip()
    if tracked_status or not all(source_checks.values()):
        raise RuntimeError(
            f"T251A2 requires clean exact sources: dirty={bool(tracked_status)} "
            f"checks={source_checks}"
        )

    paths = {
        "calibrator": require_inside(args.calibrator, root, "calibrator"),
        "deployment_policy": require_inside(args.policy, root, "policy"),
        "fixed_p30_runtime_observer_fit": require_inside(args.p30_fit, root, "P30 fit"),
        "projected_reference_table": require_inside(
            args.reference_table, root, "reference table"
        ),
    }
    assets = prereg["unchanged_assets"]
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
        raise RuntimeError(f"T251A2 asset mismatch: {asset_checks}")

    scheduler = os.sched_getscheduler(0)
    priority = os.sched_getparam(0).sched_priority
    affinity = sorted(os.sched_getaffinity(0))
    governor = Path(
        f"/sys/devices/system/cpu/cpu{affinity[0]}/cpufreq/scaling_governor"
    ).read_text(encoding="utf-8").strip()
    descriptors_before = robot_descriptors(open_descriptors())
    modules_before = loaded_robot_modules()
    baseline = build_host(WinnerV13StateCoherentTransaction, paths, prereg)
    optimized = build_host(WinnerV14X5OptimizedTransaction, paths, prereg)
    sample = samples(float(prereg["screen"]["command_x_m_s"]))
    locomotion_ticks = int(prereg["screen"]["locomotion_ticks"])
    total_ticks = CALIBRATION_TICKS + locomotion_ticks
    stage_ns = np.empty(total_ticks, dtype=np.int64)
    commit_ns = np.empty(total_ticks, dtype=np.int64)
    release_lateness_ns = np.empty(total_ticks, dtype=np.int64)
    actions = np.empty((total_ticks, ACTION_DIM), dtype=np.float32)
    mismatch: dict[str, Any] | None = None
    maximum_rate_excess = 0.0
    period_ns = int(prereg["screen"]["release_period_ns"])
    gc_was_enabled = gc.isenabled()
    gc.collect()
    gc.disable()
    release_epoch = time.perf_counter_ns()
    executed = 0
    try:
        for tick in range(total_ticks):
            deadline = release_epoch + tick * period_ns
            remaining = deadline - time.perf_counter_ns()
            if remaining > 0:
                time.sleep(remaining / 1_000_000_000.0)
            release_lateness_ns[tick] = max(0, time.perf_counter_ns() - deadline)
            if tick % 2 == 0:
                stage(baseline, tick, sample)
                started = time.perf_counter_ns()
                stage(optimized, tick, sample)
                stage_ns[tick] = time.perf_counter_ns() - started
            else:
                started = time.perf_counter_ns()
                stage(optimized, tick, sample)
                stage_ns[tick] = time.perf_counter_ns() - started
                stage(baseline, tick, sample)
            for label, expected_value, actual_value in exact_state_pairs(
                baseline, optimized, committed=False
            ):
                if not np.array_equal(expected_value, actual_value):
                    mismatch = {
                        "tick": tick,
                        "boundary": "staged",
                        "field": label,
                        "maximum_delta": float(
                            np.max(
                                np.abs(
                                    expected_value.astype(np.float64)
                                    - actual_value.astype(np.float64)
                                )
                            )
                        ),
                    }
                    break
            if mismatch is not None:
                baseline.discard_staged()
                optimized.discard_staged()
                break
            np.copyto(actions[tick], optimized.normalized_action_view)
            maximum_rate_excess = max(
                maximum_rate_excess,
                float(np.max(optimized.target_pipeline.graph_rate_excess_rad_s)),
            )
            baseline.complete_send(write_succeeded=True)
            started = time.perf_counter_ns()
            optimized.complete_send(write_succeeded=True)
            commit_ns[tick] = time.perf_counter_ns() - started
            for label, expected_value, actual_value in exact_state_pairs(
                baseline, optimized, committed=True
            ):
                if not np.array_equal(expected_value, actual_value):
                    mismatch = {
                        "tick": tick,
                        "boundary": "committed",
                        "field": label,
                        "maximum_delta": float(
                            np.max(
                                np.abs(
                                    expected_value.astype(np.float64)
                                    - actual_value.astype(np.float64)
                                )
                            )
                        ),
                    }
                    break
            executed = tick + 1
            if mismatch is not None:
                break
            if tick + 1 == CALIBRATION_TICKS:
                baseline.confirm_calibration_handoff(True)
                optimized.confirm_calibration_handoff(True)
                if not np.array_equal(
                    baseline.calibration_context,
                    optimized.calibration_context,
                ):
                    mismatch = {
                        "tick": tick,
                        "boundary": "handoff",
                        "field": "calibration_context",
                        "maximum_delta": float(
                            np.max(
                                np.abs(
                                    baseline.calibration_context.astype(np.float64)
                                    - optimized.calibration_context.astype(np.float64)
                                )
                            )
                        ),
                    }
                    break
    finally:
        if gc_was_enabled:
            gc.enable()
        else:
            gc.disable()

    stage_ns = stage_ns[:executed]
    commit_ns = commit_ns[:executed]
    release_lateness_ns = release_lateness_ns[:executed]
    actions = actions[:executed]
    np.savez_compressed(
        raw_output,
        optimized_stage_ns=stage_ns,
        optimized_commit_ns=commit_ns,
        release_lateness_ns=release_lateness_ns,
        actions=actions,
    )
    descriptors_after = robot_descriptors(open_descriptors())
    modules_after = loaded_robot_modules()
    locomotion_stage = stage_ns[CALIBRATION_TICKS:] if executed > CALIBRATION_TICKS else stage_ns
    timing = summary_ns(locomotion_stage)
    limits = prereg["timing_screen_ms"]
    checks = {
        "asset_receipts_exact": all(asset_checks.values()),
        "implementation_sources_exact": all(source_checks.values()),
        "tracked_source_clean": tracked_status == "",
        "aarch64_linux": sys.platform.startswith("linux") and machine in {"aarch64", "arm64"},
        "sched_fifo_priority_80": scheduler == os.SCHED_FIFO and priority == 80,
        "single_cpu7_affinity": affinity == [7],
        "performance_governor": governor == "performance",
        "byte_exact_every_tick": mismatch is None,
        "exact_250_0_2048_chain": executed == total_ticks
        and baseline.confirmed_calibration_ticks == CALIBRATION_TICKS
        and baseline.confirmed_home_return_ticks == 0
        and baseline.confirmed_locomotion_ticks == locomotion_ticks
        and optimized.confirmed_calibration_ticks == CALIBRATION_TICKS
        and optimized.confirmed_home_return_ticks == 0
        and optimized.confirmed_locomotion_ticks == locomotion_ticks,
        "zero_measured_rate_excess": maximum_rate_excess == 0.0,
        "no_robot_modules": modules_before == [] and modules_after == [],
        "no_robot_descriptors": descriptors_before == {} and descriptors_after == {},
        "optimized_p99_with_reserve": timing["p99_ms"] <= float(limits["p99_max"]),
        "optimized_p99_9_with_reserve": timing["p99_9_ms"] <= float(limits["p99_9_max"]),
        "optimized_max_with_reserve": timing["max_ms"] <= float(limits["max_max"]),
    }
    checks = {name: bool(value) for name, value in checks.items()}
    failed = sorted(name for name, value in checks.items() if not value)
    basis = {
        "schema_version": "open_duck_x5.t251a2_x5_optimized_paced_screen_result.v1",
        "status": (
            "PASS_T251A2_X5_OPTIMIZED_PACED_SCREEN"
            if not failed
            else "HOLD_T251A2_X5_OPTIMIZED_PACED_SCREEN"
        ),
        "decision": (
            "EARN_ONE_CORRECTED_T251B_10000_TICK_PREREGISTRATION_ONLY"
            if not failed
            else "HOLD_AND_OPTIMIZE_ONLY_THE_MEASURED_HOST_COMPONENT"
        ),
        "date": "2026-07-31",
        "git": {
            "commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "branch": subprocess.check_output(
                ["git", "branch", "--show-current"], cwd=ROOT, text=True
            ).strip(),
        },
        "platform": {
            "system": platform.system(),
            "machine": machine,
            "release": platform.release(),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scheduler": "SCHED_FIFO" if scheduler == os.SCHED_FIFO else str(scheduler),
            "scheduler_priority": priority,
            "affinity": affinity,
            "governor": governor,
        },
        "preregistration": receipt(PREREGISTRATION),
        "source_receipts": {name: receipt(path) for name, path in source_paths.items()},
        "asset_receipts": asset_receipts,
        "execution": {
            "release_period_ns": period_ns,
            "executed_ticks": executed,
            "calibration_ticks": optimized.confirmed_calibration_ticks,
            "home_return_ticks": optimized.confirmed_home_return_ticks,
            "locomotion_ticks": optimized.confirmed_locomotion_ticks,
            "optimized_stage_locomotion": timing,
            "optimized_commit_all": summary_ns(commit_ns),
            "release_lateness": summary_ns(release_lateness_ns),
            "action_trace_sha256": hashlib.sha256(actions.tobytes()).hexdigest(),
            "maximum_rate_excess_rad_s": maximum_rate_excess,
            "mismatch": mismatch,
        },
        "raw_output": receipt(raw_output),
        "checks": checks,
        "failed_checks": failed,
        "isolation_evidence": {
            "robot_modules_before": modules_before,
            "robot_modules_after": modules_after,
            "robot_descriptors_before": descriptors_before,
            "robot_descriptors_after": descriptors_after,
            "external_send_implementation": False,
            "serial_gpio_i2c_controller_or_torque_access": False,
        },
        "authority": {
            "t251_rerun": False,
            "threshold_changed": False,
            "production_runtime_modified": False,
            "policy_deployed": False,
            "serial_bus": False,
            "servo_reads_or_writes": False,
            "sensors": False,
            "torque": False,
            "motion": False,
            "gate5": False,
            "grounded_replay": False,
        },
    }
    result = {**basis, "result_sha256": canonical_sha256(basis)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(result["status"])
    print(f"checks={len(checks) - len(failed)}/{len(checks)}")
    print(
        "optimized_stage_ms="
        f"p99:{timing['p99_ms']:.6f},"
        f"p99.9:{timing['p99_9_ms']:.6f},"
        f"max:{timing['max_ms']:.6f}"
    )
    print(f"result_sha256={result['result_sha256']}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
