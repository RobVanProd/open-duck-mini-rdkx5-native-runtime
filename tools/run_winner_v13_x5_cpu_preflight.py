#!/usr/bin/env python3
"""Run the preregistered T251 no-motion CPU preflight on an RDK-X5.

The process never imports production runtime or hardware modules and never
opens a robot device.  ``complete_send(True)`` commits only in-memory state;
there is no external send implementation in this tool.
"""

from __future__ import annotations

import argparse
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
sys.path.insert(0, str(ROOT / "src"))

from open_duck_x5.constants import (  # noqa: E402
    ACTION_DIM,
    CONTROL_PERIOD_NS,
    HOME_RAD,
)
from open_duck_x5.winner_v13_state_coherent import (  # noqa: E402
    CALIBRATION_TICKS,
    HOME_RETURN_TICKS,
    GraphAsset,
    GraphSpec,
    P30FitAsset,
    TensorSpec,
    WinnerV13StateCoherentTransaction,
)

PREREGISTRATION = (
    ROOT
    / "artifacts"
    / "gates"
    / "phase_5_policy"
    / "t251_x5_no_motion_cpu_preflight_preregistration_20260731.json"
)
PREREGISTRATION_SHA256 = "7593cd1a87733fcf469a7c9d68f2aa0361456b32a24fa70c49a5109a3b3ed138"
HOST_SOURCE_SHA256 = "025cbae910f214c28e393f906388cae2723336cd1f024125768bdfae4dfb9cef"
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


def summary_ns(values: list[int]) -> dict[str, float | int]:
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
    result: dict[str, str] = {}
    fd_root = Path("/proc/self/fd")
    for path in sorted(fd_root.iterdir(), key=lambda value: int(value.name)):
        try:
            result[path.name] = os.readlink(path)
        except FileNotFoundError:
            continue
    return result


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the isolated no-motion T251 RDK-X5 CPU preflight"
    )
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--calibrator", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--p30-fit", type=Path, required=True)
    parser.add_argument("--reference-table", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    staging_root = args.staging_root.resolve()
    if str(staging_root) != "/home/sunrise/open_duck_x5_preflight/t251":
        raise RuntimeError(f"unpreregistered staging root: {staging_root}")
    paths = {
        "calibrator": require_inside(args.calibrator, staging_root, "calibrator"),
        "deployment_policy": require_inside(args.policy, staging_root, "policy"),
        "fixed_p30_runtime_observer_fit": require_inside(
            args.p30_fit,
            staging_root,
            "P30 fit",
        ),
        "projected_reference_table": require_inside(
            args.reference_table,
            staging_root,
            "reference table",
        ),
    }
    output = require_inside(args.output, staging_root, "output")
    if output.exists():
        raise FileExistsError("refusing to overwrite T251 preflight output")
    if not sys.platform.startswith("linux"):
        raise RuntimeError(f"T251 requires Linux, got {sys.platform}")
    machine = platform.machine().lower()
    if machine not in {"aarch64", "arm64"}:
        raise RuntimeError(f"T251 requires aarch64, got {machine}")
    if sha256(PREREGISTRATION) != PREREGISTRATION_SHA256:
        raise RuntimeError("T251 preregistration changed")
    host_source = ROOT / "src" / "open_duck_x5" / "winner_v13_state_coherent.py"
    if sha256(host_source) != HOST_SOURCE_SHA256:
        raise RuntimeError("T250 state-coherent host source changed")
    tracked_status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        text=True,
    ).strip()
    if tracked_status:
        raise RuntimeError("T251 requires a clean tracked source checkout")

    prereg = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    expected_assets = prereg["assets"]
    asset_receipts = {name: receipt(path) for name, path in paths.items()}
    asset_receipt_checks = {
        name: value["bytes"] == int(expected_assets[name]["bytes"])
        and value["sha256"] == expected_assets[name]["sha256"]
        for name, value in asset_receipts.items()
    }
    if not all(asset_receipt_checks.values()):
        raise RuntimeError(f"T251 selected asset mismatch: {asset_receipt_checks}")

    scheduler = os.sched_getscheduler(0)
    scheduler_name = "SCHED_FIFO" if scheduler == os.SCHED_FIFO else str(scheduler)
    priority = os.sched_getparam(0).sched_priority
    affinity = sorted(os.sched_getaffinity(0))
    governor_path = Path(f"/sys/devices/system/cpu/cpu{affinity[0]}/cpufreq/scaling_governor")
    governor = (
        governor_path.read_text(encoding="utf-8").strip()
        if len(affinity) == 1 and governor_path.is_file()
        else None
    )
    descriptors_before = open_descriptors()
    robot_descriptors_before = robot_descriptors(descriptors_before)
    robot_modules_before = loaded_robot_modules()

    import onnxruntime as ort

    started = time.perf_counter_ns()
    host = WinnerV13StateCoherentTransaction(
        calibrator=GraphAsset(
            paths["calibrator"],
            calibrator_spec(),
            frozenset({asset_receipts["calibrator"]["sha256"]}),
        ),
        locomotion=GraphAsset(
            paths["deployment_policy"],
            locomotion_spec(),
            frozenset({asset_receipts["deployment_policy"]["sha256"]}),
        ),
        p30_fit=P30FitAsset(
            paths["fixed_p30_runtime_observer_fit"],
            frozenset({asset_receipts["fixed_p30_runtime_observer_fit"]["sha256"]}),
        ),
        reference_table_path=paths["projected_reference_table"],
        enabled=True,
        warmup_runs=int(prereg["runner_contract"]["warmup_runs_per_graph"]),
    )
    initialization_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    session_providers = {
        "calibrator": host._calibrator.session.get_providers(),
        "locomotion": host._locomotion.session.get_providers(),
    }

    command = np.zeros(7, dtype=np.float64)
    command[0] = float(prereg["runner_contract"]["locomotion_command_x_m_s"])
    samples = {
        "gyro_rad_s": np.zeros(3, dtype=np.float64),
        "acceleration_m_s2": np.asarray([0.0, 0.0, 9.81], dtype=np.float64),
        "commands": command,
        "positions_rad": HOME_RAD.copy(),
        "velocities_rad_s": np.zeros(ACTION_DIM, dtype=np.float64),
        "foot_contacts": np.ones(2, dtype=np.float64),
        "servo_stale": np.zeros(ACTION_DIM, dtype=np.bool_),
        "imu_stale": False,
        "contacts_stale": False,
        "soft_offsets_rad": np.linspace(
            -0.001,
            0.001,
            ACTION_DIM,
            dtype=np.float64,
        ),
    }
    stage_ns: list[int] = []
    all_finite = True
    maximum_rate_excess = 0.0
    maximum_abs_action = 0.0

    for tick in range(CALIBRATION_TICKS):
        tick_started = time.perf_counter_ns()
        host.stage_tick(
            tick_index=tick,
            logical_period_ns=CONTROL_PERIOD_NS,
            servo_sample_tick_index=tick,
            imu_sample_tick_index=tick,
            contacts_sample_tick_index=tick,
            **samples,
        )
        stage_ns.append(time.perf_counter_ns() - tick_started)
        action = host.normalized_action_view
        maximum_abs_action = max(maximum_abs_action, float(np.max(np.abs(action))))
        all_finite = all_finite and all(
            bool(np.isfinite(value).all())
            for value in (
                action,
                host.observation_view,
                host.logical_target_view,
                host.physical_target_view,
                host.observer.value_view,
            )
        )
        host.complete_send(write_succeeded=True)

    host.confirm_calibration_handoff(True)
    context_before = host.calibration_context
    context_sha_before = hashlib.sha256(context_before.tobytes()).hexdigest()
    locomotion_ticks = int(prereg["runner_contract"]["locomotion_ticks"])
    for local_tick in range(locomotion_ticks):
        tick = CALIBRATION_TICKS + local_tick
        tick_started = time.perf_counter_ns()
        host.stage_tick(
            tick_index=tick,
            logical_period_ns=CONTROL_PERIOD_NS,
            servo_sample_tick_index=tick,
            imu_sample_tick_index=tick,
            contacts_sample_tick_index=tick,
            **samples,
        )
        stage_ns.append(time.perf_counter_ns() - tick_started)
        action = host.normalized_action_view
        maximum_abs_action = max(maximum_abs_action, float(np.max(np.abs(action))))
        maximum_rate_excess = max(
            maximum_rate_excess,
            float(np.max(host.target_pipeline.graph_rate_excess_rad_s)),
        )
        all_finite = all_finite and all(
            bool(np.isfinite(value).all())
            for value in (
                action,
                host.observation_view,
                host.logical_target_view,
                host.physical_target_view,
                host.observer.value_view,
            )
        )
        host.complete_send(write_succeeded=True)

    context_after = host.calibration_context
    context_sha_after = hashlib.sha256(context_after.tobytes()).hexdigest()
    descriptors_after = open_descriptors()
    robot_descriptors_after = robot_descriptors(descriptors_after)
    robot_modules_after = loaded_robot_modules()
    timing = summary_ns(stage_ns)
    gates = prereg["preflight_gates"]
    checks = {
        "all_asset_receipts_exact": all(asset_receipt_checks.values()),
        "runtime_source_receipt_exact": sha256(host_source) == HOST_SOURCE_SHA256,
        "aarch64_linux": sys.platform.startswith("linux") and machine in {"aarch64", "arm64"},
        "cpu_provider_only": all(
            value == ["CPUExecutionProvider"] for value in session_providers.values()
        ),
        "sched_fifo_verified": scheduler == os.SCHED_FIFO and priority > 0,
        "single_cpu_affinity_verified": len(affinity) == 1,
        "performance_governor_verified": governor == "performance",
        "no_robot_interface_imports": robot_modules_before == [] and robot_modules_after == [],
        "no_robot_device_descriptors_before_or_after": robot_descriptors_before == {}
        and robot_descriptors_after == {},
        "exact_250_tick_calibration": host.confirmed_calibration_ticks
        == CALIBRATION_TICKS
        == int(prereg["runner_contract"]["calibration_ticks"]),
        "zero_home_return_ticks": host.confirmed_home_return_ticks == HOME_RETURN_TICKS == 0,
        "exact_10000_tick_locomotion_chain": host.confirmed_locomotion_ticks
        == locomotion_ticks
        == 10_000,
        "all_values_finite": all_finite,
        "zero_measured_rate_excess": maximum_rate_excess == 0.0,
        "context_immutable": context_sha_before == context_sha_after,
        "stage_latency_p99": timing["p99_ms"] <= float(gates["stage_latency_p99_ms_max"]),
        "stage_latency_p99_9": timing["p99_9_ms"] <= float(gates["stage_latency_p99_9_ms_max"]),
        "stage_latency_max": timing["max_ms"] <= float(gates["stage_latency_max_ms_max"]),
    }
    checks = {name: bool(value) for name, value in checks.items()}
    failed = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed
    basis = {
        "schema_version": "open_duck_x5.t251_x5_no_motion_cpu_preflight_result.v1",
        "status": (
            "PASS_T251_X5_NO_MOTION_CPU_PREFLIGHT"
            if passed
            else "HOLD_T251_X5_NO_MOTION_CPU_PREFLIGHT"
        ),
        "decision": (
            "EARN_VERSIONED_PRODUCTION_INTEGRATION_PREREGISTRATION_ONLY"
            if passed
            else "HOLD_T250_X5_INTEGRATION_AND_ATTRIBUTE_WITHOUT_CHANGING_THRESHOLDS"
        ),
        "date": "2026-07-31",
        "git": {
            "commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=ROOT,
                text=True,
            ).strip(),
            "branch": subprocess.check_output(
                ["git", "branch", "--show-current"],
                cwd=ROOT,
                text=True,
            ).strip(),
            "tracked_status_clean": tracked_status == "",
        },
        "platform": {
            "system": platform.system(),
            "machine": machine,
            "release": platform.release(),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "onnxruntime": ort.__version__,
            "onnxruntime_device": ort.get_device(),
            "session_providers": session_providers,
            "scheduler": scheduler_name,
            "scheduler_priority": priority,
            "affinity": affinity,
            "governor": governor,
        },
        "preregistration": receipt(PREREGISTRATION),
        "host_source": receipt(host_source),
        "asset_receipts": asset_receipts,
        "execution": {
            "initialization_and_warmup_ms": initialization_ms,
            "calibration_ticks": host.confirmed_calibration_ticks,
            "home_return_ticks": host.confirmed_home_return_ticks,
            "locomotion_ticks": host.confirmed_locomotion_ticks,
            "stage_latency_compute_only": timing,
            "maximum_abs_action": maximum_abs_action,
            "maximum_rate_excess_rad_s": maximum_rate_excess,
            "calibration_context_sha256": context_sha_before,
        },
        "isolation_evidence": {
            "staging_root": str(staging_root),
            "robot_modules_before": robot_modules_before,
            "robot_modules_after": robot_modules_after,
            "robot_descriptors_before": robot_descriptors_before,
            "robot_descriptors_after": robot_descriptors_after,
            "external_send_implementation": False,
            "serial_gpio_i2c_controller_or_torque_access": False,
        },
        "checks": checks,
        "failed_checks": failed,
        "interpretation": prereg["interpretation"],
        "authority": {
            "no_motion_x5_cpu_preflight_executed": True,
            "production_runtime_modified": False,
            "policy_deployed": False,
            "serial_bus": False,
            "servo_reads_or_writes": False,
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
        "stage_ms="
        f"p99:{timing['p99_ms']:.6f},"
        f"p99.9:{timing['p99_9_ms']:.6f},max:{timing['max_ms']:.6f}"
    )
    print(f"result_sha256={result['result_sha256']}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
