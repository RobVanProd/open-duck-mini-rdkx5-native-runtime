#!/usr/bin/env python3
"""Run the preregistered T251A no-motion X5 compute attribution.

This tool uses only synthetic numpy state and in-memory send confirmations. It
does not import the production runtime or open serial, GPIO, I2C, controller,
sensor, torque, or motion interfaces.
"""

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

try:
    import resource
except ModuleNotFoundError:  # pragma: no cover - Windows test/import support
    resource = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from open_duck_x5.constants import ACTION_DIM, CONTROL_PERIOD_NS, HOME_RAD  # noqa: E402
from open_duck_x5.winner_v13_state_coherent import (  # noqa: E402
    CALIBRATION_TICKS,
    CONTEXT_DIM,
    HIDDEN_DIM,
    OBSERVATION_DIM,
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
    / "t251a_x5_compute_attribution_preregistration_20260731.json"
)
PREREGISTRATION_SHA256 = "c113807cff15d7638015f5463ff6a363e25554db6ee9d6f45d13a65e48f42634"
HOST_SOURCE_SHA256 = "025cbae910f214c28e393f906388cae2723336cd1f024125768bdfae4dfb9cef"
EXPECTED_ROOT = Path("/home/sunrise/open_duck_x5_preflight/t251a")
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
COMPONENTS = ("observation", "onnx", "target_pipeline", "observer")
WORST_TICKS = 64


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
        "over_2ms": int(np.count_nonzero(milliseconds > 2.0)),
        "over_3ms": int(np.count_nonzero(milliseconds > 3.0)),
        "over_5ms": int(np.count_nonzero(milliseconds > 5.0)),
    }


def calibrator_spec() -> GraphSpec:
    return GraphSpec(
        observation=TensorSpec("obs", (1, OBSERVATION_DIM)),
        previous_action=TensorSpec("previous_action", (1, ACTION_DIM)),
        hidden_in=TensorSpec("h_in", (1, HIDDEN_DIM)),
        action=TensorSpec("calibration_actions", (1, ACTION_DIM)),
        previous_action_out=TensorSpec("previous_action_out", (1, ACTION_DIM)),
        hidden_out=TensorSpec("h_out", (1, HIDDEN_DIM)),
    )


def locomotion_spec() -> GraphSpec:
    return GraphSpec(
        observation=TensorSpec("obs", (1, OBSERVATION_DIM)),
        previous_action=TensorSpec("previous_action", (1, ACTION_DIM)),
        hidden_in=TensorSpec("h_in", (1, HIDDEN_DIM)),
        calibration_context=TensorSpec("calibration_context", (1, CONTEXT_DIM)),
        action=TensorSpec("continuous_actions", (1, ACTION_DIM)),
        previous_action_out=TensorSpec("previous_action_out", (1, ACTION_DIM)),
        hidden_out=TensorSpec("h_out", (1, HIDDEN_DIM)),
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


def read_text(path: str) -> str | None:
    candidate = Path(path)
    if not candidate.is_file():
        return None
    return candidate.read_text(encoding="utf-8").strip()


def cpu_column_counters(path: str, cpu: int) -> dict[str, int]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if not lines:
        return {}
    headers = lines[0].split()
    cpu_name = f"CPU{cpu}"
    if cpu_name not in headers:
        return {}
    column = headers.index(cpu_name)
    counters: dict[str, int] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        label, remainder = line.split(":", 1)
        fields = remainder.split()
        if len(fields) <= column or not fields[column].isdigit():
            continue
        counters[label.strip()] = int(fields[column])
    return counters


def counter_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {
        key: int(after.get(key, 0) - before.get(key, 0))
        for key in sorted(set(before) | set(after))
        if after.get(key, 0) != before.get(key, 0)
    }


def resource_snapshot() -> dict[str, int | float]:
    if resource is None:
        raise RuntimeError("resource accounting requires Linux")
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "user_s": float(usage.ru_utime),
        "system_s": float(usage.ru_stime),
        "minor_faults": int(usage.ru_minflt),
        "major_faults": int(usage.ru_majflt),
        "voluntary_context_switches": int(usage.ru_nvcsw),
        "involuntary_context_switches": int(usage.ru_nivcsw),
    }


def numeric_delta(before: dict[str, int | float], after: dict[str, int | float]) -> dict[str, Any]:
    return {key: after[key] - before[key] for key in sorted(before)}


def system_snapshot(cpu: int) -> dict[str, Any]:
    return {
        "resource": resource_snapshot(),
        "interrupts": cpu_column_counters("/proc/interrupts", cpu),
        "softirqs": cpu_column_counters("/proc/softirqs", cpu),
        "cpu_frequency_khz": read_text(
            f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/cpuinfo_cur_freq"
        ),
        "cpu_temperature_millic": read_text("/sys/class/thermal/thermal_zone1/temp"),
        "gc_stats": gc.get_stats(),
        "gc_count": list(gc.get_count()),
    }


def system_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        "resource": numeric_delta(before["resource"], after["resource"]),
        "interrupts": counter_delta(before["interrupts"], after["interrupts"]),
        "softirqs": counter_delta(before["softirqs"], after["softirqs"]),
        "cpu_frequency_khz_before": before["cpu_frequency_khz"],
        "cpu_frequency_khz_after": after["cpu_frequency_khz"],
        "cpu_temperature_millic_before": before["cpu_temperature_millic"],
        "cpu_temperature_millic_after": after["cpu_temperature_millic"],
        "gc_collections": [
            int(after["gc_stats"][index]["collections"] - before["gc_stats"][index]["collections"])
            for index in range(3)
        ],
        "gc_collected": [
            int(after["gc_stats"][index]["collected"] - before["gc_stats"][index]["collected"])
            for index in range(3)
        ],
    }


def build_host(paths: dict[str, Path], prereg: dict[str, Any]) -> WinnerV13StateCoherentTransaction:
    contract = prereg["unchanged_contract"]
    return WinnerV13StateCoherentTransaction(
        calibrator=GraphAsset(
            paths["calibrator"],
            calibrator_spec(),
            frozenset({contract["calibrator_sha256"]}),
        ),
        locomotion=GraphAsset(
            paths["deployment_policy"],
            locomotion_spec(),
            frozenset({contract["deployment_policy_sha256"]}),
        ),
        p30_fit=P30FitAsset(
            paths["fixed_p30_runtime_observer_fit"],
            frozenset({contract["fixed_p30_runtime_observer_fit_sha256"]}),
        ),
        reference_table_path=paths["projected_reference_table"],
        enabled=True,
        warmup_runs=int(contract["warmup_runs_per_graph"]),
    )


def synthetic_samples() -> dict[str, Any]:
    command = np.zeros(7, dtype=np.float64)
    command[0] = 0.074
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


def worst_rows(
    stage_ns: np.ndarray,
    commit_ns: np.ndarray,
    *,
    components_ns: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    count = min(WORST_TICKS, int(stage_ns.size))
    indices = np.argsort(stage_ns)[-count:][::-1]
    rows: list[dict[str, Any]] = []
    for index_value in indices:
        index = int(index_value)
        row: dict[str, Any] = {
            "tick": index,
            "stage_ms": float(stage_ns[index] / 1_000_000.0),
            "commit_ms": float(commit_ns[index] / 1_000_000.0),
        }
        if components_ns is not None:
            values = {
                name: float(components_ns[index, component] / 1_000_000.0)
                for component, name in enumerate(COMPONENTS)
            }
            values["residual_host"] = float(
                max(0, stage_ns[index] - int(np.sum(components_ns[index]))) / 1_000_000.0
            )
            row["components_ms"] = values
        rows.append(row)
    return rows


def arm_summary(
    *,
    stage_ns: np.ndarray,
    commit_ns: np.ndarray,
    calibration_ticks: int,
    system_before: dict[str, Any],
    system_after: dict[str, Any],
    action_sha256: str,
    maximum_abs_action: float,
    maximum_rate_excess_rad_s: float,
    components_ns: np.ndarray | None = None,
) -> dict[str, Any]:
    locomotion = stage_ns[calibration_ticks:]
    result: dict[str, Any] = {
        "ticks": int(stage_ns.size),
        "calibration_ticks": calibration_ticks,
        "locomotion_ticks": int(stage_ns.size - calibration_ticks),
        "stage_all": summary_ns(stage_ns),
        "stage_locomotion": summary_ns(locomotion),
        "commit_all": summary_ns(commit_ns),
        "action_trace_sha256": action_sha256,
        "maximum_abs_action": maximum_abs_action,
        "maximum_rate_excess_rad_s": maximum_rate_excess_rad_s,
        "system_delta": system_delta(system_before, system_after),
        "worst_ticks": worst_rows(stage_ns, commit_ns, components_ns=components_ns),
    }
    if components_ns is not None:
        result["component_locomotion"] = {
            name: summary_ns(components_ns[calibration_ticks:, index])
            for index, name in enumerate(COMPONENTS)
        }
        residual = stage_ns.astype(np.int64) - np.sum(components_ns, axis=1)
        np.maximum(residual, 0, out=residual)
        result["component_locomotion"]["residual_host"] = summary_ns(
            residual[calibration_ticks:]
        )
    return result


def set_gc(enabled: bool) -> bool:
    previous = gc.isenabled()
    gc.collect()
    if enabled:
        gc.enable()
    else:
        gc.disable()
    return previous


def restore_gc(previous: bool) -> None:
    if previous:
        gc.enable()
    else:
        gc.disable()


def run_full_arm(
    *,
    paths: dict[str, Path],
    prereg: dict[str, Any],
    locomotion_ticks: int,
    gc_enabled: bool,
    components: bool,
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    host = build_host(paths, prereg)
    samples = synthetic_samples()
    total_ticks = CALIBRATION_TICKS + locomotion_ticks
    stage_ns = np.empty(total_ticks, dtype=np.int64)
    commit_ns = np.empty(total_ticks, dtype=np.int64)
    actions = np.empty((total_ticks, ACTION_DIM), dtype=np.float32)
    component_ns = (
        np.zeros((total_ticks, len(COMPONENTS)), dtype=np.int64) if components else None
    )
    current_tick = [-1]

    def wrap(obj: object, name: str, component: int) -> None:
        original = getattr(obj, name)

        def timed(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter_ns()
            try:
                return original(*args, **kwargs)
            finally:
                tick = current_tick[0]
                if tick >= 0 and component_ns is not None:
                    component_ns[tick, component] += time.perf_counter_ns() - started

        setattr(obj, name, timed)

    if components:
        wrap(host.assembler, "build", 0)
        wrap(host._calibrator, "stage", 1)
        wrap(host._locomotion, "stage", 1)
        wrap(host.target_pipeline, "stage", 2)
        wrap(host.observer, "stage_confirmed_target", 3)

    previous_gc = set_gc(gc_enabled)
    before = system_snapshot(7)
    maximum_abs_action = 0.0
    maximum_rate_excess = 0.0
    try:
        for tick in range(CALIBRATION_TICKS):
            current_tick[0] = tick
            started = time.perf_counter_ns()
            host.stage_tick(
                tick_index=tick,
                logical_period_ns=CONTROL_PERIOD_NS,
                servo_sample_tick_index=tick,
                imu_sample_tick_index=tick,
                contacts_sample_tick_index=tick,
                **samples,
            )
            stage_ns[tick] = time.perf_counter_ns() - started
            np.copyto(actions[tick], host.normalized_action_view)
            maximum_abs_action = max(
                maximum_abs_action,
                float(np.max(np.abs(host.normalized_action_view))),
            )
            started = time.perf_counter_ns()
            host.complete_send(write_succeeded=True)
            commit_ns[tick] = time.perf_counter_ns() - started
            current_tick[0] = -1
        host.confirm_calibration_handoff(True)
        for local_tick in range(locomotion_ticks):
            tick = CALIBRATION_TICKS + local_tick
            current_tick[0] = tick
            started = time.perf_counter_ns()
            host.stage_tick(
                tick_index=tick,
                logical_period_ns=CONTROL_PERIOD_NS,
                servo_sample_tick_index=tick,
                imu_sample_tick_index=tick,
                contacts_sample_tick_index=tick,
                **samples,
            )
            stage_ns[tick] = time.perf_counter_ns() - started
            np.copyto(actions[tick], host.normalized_action_view)
            maximum_abs_action = max(
                maximum_abs_action,
                float(np.max(np.abs(host.normalized_action_view))),
            )
            maximum_rate_excess = max(
                maximum_rate_excess,
                float(np.max(host.target_pipeline.graph_rate_excess_rad_s)),
            )
            started = time.perf_counter_ns()
            host.complete_send(write_succeeded=True)
            commit_ns[tick] = time.perf_counter_ns() - started
            current_tick[0] = -1
        after = system_snapshot(7)
    finally:
        current_tick[0] = -1
        restore_gc(previous_gc)

    summary = arm_summary(
        stage_ns=stage_ns,
        commit_ns=commit_ns,
        calibration_ticks=CALIBRATION_TICKS,
        system_before=before,
        system_after=after,
        action_sha256=hashlib.sha256(actions.tobytes()).hexdigest(),
        maximum_abs_action=maximum_abs_action,
        maximum_rate_excess_rad_s=maximum_rate_excess,
        components_ns=component_ns,
    )
    summary["confirmed_calibration_ticks"] = host.confirmed_calibration_ticks
    summary["confirmed_home_return_ticks"] = host.confirmed_home_return_ticks
    summary["confirmed_locomotion_ticks"] = host.confirmed_locomotion_ticks
    arrays = {"stage_ns": stage_ns, "commit_ns": commit_ns, "actions": actions}
    if component_ns is not None:
        arrays["components_ns"] = component_ns
    return summary, arrays


def initialize_graph_only_host(
    paths: dict[str, Path], prereg: dict[str, Any]
) -> tuple[WinnerV13StateCoherentTransaction, np.ndarray]:
    host = build_host(paths, prereg)
    samples = synthetic_samples()
    for tick in range(CALIBRATION_TICKS):
        host.stage_tick(
            tick_index=tick,
            logical_period_ns=CONTROL_PERIOD_NS,
            servo_sample_tick_index=tick,
            imu_sample_tick_index=tick,
            contacts_sample_tick_index=tick,
            **samples,
        )
        host.complete_send(write_succeeded=True)
    host.confirm_calibration_handoff(True)
    tick = CALIBRATION_TICKS
    host.stage_tick(
        tick_index=tick,
        logical_period_ns=CONTROL_PERIOD_NS,
        servo_sample_tick_index=tick,
        imu_sample_tick_index=tick,
        contacts_sample_tick_index=tick,
        **samples,
    )
    observation = host.observation_view.copy()
    host.discard_staged()
    return host, observation


def run_graph_only_arm(
    *, paths: dict[str, Path], prereg: dict[str, Any], ticks: int
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    host, observation = initialize_graph_only_host(paths, prereg)
    session = host._locomotion
    stage_ns = np.empty(ticks, dtype=np.int64)
    commit_ns = np.empty(ticks, dtype=np.int64)
    actions = np.empty((ticks, ACTION_DIM), dtype=np.float32)
    previous_gc = set_gc(False)
    before = system_snapshot(7)
    maximum_abs_action = 0.0
    try:
        for tick in range(ticks):
            started = time.perf_counter_ns()
            session.stage(observation)
            stage_ns[tick] = time.perf_counter_ns() - started
            np.copyto(actions[tick], session._staged_action_view)
            maximum_abs_action = max(
                maximum_abs_action,
                float(np.max(np.abs(session._staged_action_view))),
            )
            started = time.perf_counter_ns()
            session.commit(True)
            commit_ns[tick] = time.perf_counter_ns() - started
        after = system_snapshot(7)
    finally:
        restore_gc(previous_gc)
    summary = arm_summary(
        stage_ns=stage_ns,
        commit_ns=commit_ns,
        calibration_ticks=0,
        system_before=before,
        system_after=after,
        action_sha256=hashlib.sha256(actions.tobytes()).hexdigest(),
        maximum_abs_action=maximum_abs_action,
        maximum_rate_excess_rad_s=0.0,
    )
    return summary, {"stage_ns": stage_ns, "commit_ns": commit_ns, "actions": actions}


def classify(arms: dict[str, Any]) -> dict[str, str]:
    graph = arms["graph_only_gc_disabled"]["stage_locomotion"]
    host_off = arms["full_host_gc_disabled"]["stage_locomotion"]
    host_on = arms["full_host_gc_enabled"]["stage_locomotion"]
    if graph["p99_ms"] > 2.0:
        steady = "EXACT_ONNX_GRAPH_FLOOR_EXCEEDS_T251_P99"
    elif host_off["p99_ms"] > 2.0:
        steady = "PYTHON_HOST_OVERHEAD_EXCEEDS_T251_P99"
    else:
        steady = "STEADY_T251_P99_RECOVERABLE_WITH_CURRENT_GRAPH_AND_HOST"
    if host_on["max_ms"] > 5.0 and host_off["max_ms"] <= 5.0 and graph["max_ms"] <= 5.0:
        tail = "PYTHON_GC_TAIL"
    elif graph["max_ms"] > 5.0:
        tail = "GRAPH_OR_KERNEL_TAIL_REMAINS_WITH_GC_DISABLED"
    elif host_off["max_ms"] > 5.0:
        tail = "PYTHON_HOST_OR_KERNEL_TAIL_REMAINS_WITH_GC_DISABLED"
    elif host_on["max_ms"] <= 5.0:
        tail = "ORIGINAL_T251_TAIL_NOT_REPRODUCED"
    else:
        tail = "MIXED_TAIL"
    return {"steady": steady, "tail": tail}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the no-motion T251A X5 attribution")
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--calibrator", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--p30-fit", type=Path, required=True)
    parser.add_argument("--reference-table", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path, required=True)
    return parser.parse_args()


def require_inside(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise RuntimeError(f"{label} is outside isolated staging root: {resolved}")
    return resolved


def main() -> int:
    args = parse_args()
    root = args.staging_root.resolve()
    if root != EXPECTED_ROOT:
        raise RuntimeError(f"unpreregistered staging root: {root}")
    output = require_inside(args.output, root, "output")
    raw_output = require_inside(args.raw_output, root, "raw output")
    if output.exists() or raw_output.exists():
        raise FileExistsError("refusing to overwrite T251A output")
    machine = platform.machine().lower()
    if not sys.platform.startswith("linux") or machine not in {"aarch64", "arm64"}:
        raise RuntimeError("T251A requires aarch64 Linux")
    if sha256(PREREGISTRATION) != PREREGISTRATION_SHA256:
        raise RuntimeError("T251A preregistration changed")
    host_source = ROOT / "src" / "open_duck_x5" / "winner_v13_state_coherent.py"
    if sha256(host_source) != HOST_SOURCE_SHA256:
        raise RuntimeError("T250 host source changed")
    tracked_status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        text=True,
    ).strip()
    if tracked_status:
        raise RuntimeError("T251A requires a clean tracked source checkout")

    paths = {
        "calibrator": require_inside(args.calibrator, root, "calibrator"),
        "deployment_policy": require_inside(args.policy, root, "policy"),
        "fixed_p30_runtime_observer_fit": require_inside(args.p30_fit, root, "P30 fit"),
        "projected_reference_table": require_inside(
            args.reference_table, root, "reference table"
        ),
    }
    prereg = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    expected = prereg["unchanged_contract"]
    expected_hashes = {
        "calibrator": expected["calibrator_sha256"],
        "deployment_policy": expected["deployment_policy_sha256"],
        "fixed_p30_runtime_observer_fit": expected[
            "fixed_p30_runtime_observer_fit_sha256"
        ],
        "projected_reference_table": expected["projected_reference_table_sha256"],
    }
    asset_receipts = {name: receipt(path) for name, path in paths.items()}
    asset_checks = {
        name: asset_receipts[name]["sha256"] == digest
        for name, digest in expected_hashes.items()
    }
    if not all(asset_checks.values()):
        raise RuntimeError(f"T251A asset mismatch: {asset_checks}")

    scheduler = os.sched_getscheduler(0)
    priority = os.sched_getparam(0).sched_priority
    affinity = sorted(os.sched_getaffinity(0))
    governor = read_text(f"/sys/devices/system/cpu/cpu{affinity[0]}/cpufreq/scaling_governor")
    descriptors_before = robot_descriptors(open_descriptors())
    modules_before = loaded_robot_modules()

    arms: dict[str, Any] = {}
    raw: dict[str, np.ndarray] = {}
    arm, arrays = run_full_arm(
        paths=paths,
        prereg=prereg,
        locomotion_ticks=10_000,
        gc_enabled=True,
        components=False,
    )
    arms["full_host_gc_enabled"] = arm
    raw.update({f"full_host_gc_enabled_{key}": value for key, value in arrays.items()})
    arm, arrays = run_full_arm(
        paths=paths,
        prereg=prereg,
        locomotion_ticks=10_000,
        gc_enabled=False,
        components=False,
    )
    arms["full_host_gc_disabled"] = arm
    raw.update({f"full_host_gc_disabled_{key}": value for key, value in arrays.items()})
    arm, arrays = run_graph_only_arm(paths=paths, prereg=prereg, ticks=10_000)
    arms["graph_only_gc_disabled"] = arm
    raw.update({f"graph_only_gc_disabled_{key}": value for key, value in arrays.items()})
    arm, arrays = run_full_arm(
        paths=paths,
        prereg=prereg,
        locomotion_ticks=2048,
        gc_enabled=False,
        components=True,
    )
    arms["component_profile_gc_disabled"] = arm
    raw.update(
        {f"component_profile_gc_disabled_{key}": value for key, value in arrays.items()}
    )
    np.savez_compressed(raw_output, **raw)

    descriptors_after = robot_descriptors(open_descriptors())
    modules_after = loaded_robot_modules()
    traces_equal = (
        arms["full_host_gc_enabled"]["action_trace_sha256"]
        == arms["full_host_gc_disabled"]["action_trace_sha256"]
    )
    checks = {
        "aarch64_linux": sys.platform.startswith("linux") and machine in {"aarch64", "arm64"},
        "asset_receipts_exact": all(asset_checks.values()),
        "host_source_exact": sha256(host_source) == HOST_SOURCE_SHA256,
        "preregistration_exact": sha256(PREREGISTRATION) == PREREGISTRATION_SHA256,
        "tracked_source_clean": tracked_status == "",
        "sched_fifo_priority_80": scheduler == os.SCHED_FIFO and priority == 80,
        "single_cpu7_affinity": affinity == [7],
        "performance_governor": governor == "performance",
        "full_host_action_traces_gc_invariant": traces_equal,
        "full_host_exact_tick_counts": all(
            arms[name]["confirmed_calibration_ticks"] == 250
            and arms[name]["confirmed_home_return_ticks"] == 0
            and arms[name]["confirmed_locomotion_ticks"] == ticks
            for name, ticks in (
                ("full_host_gc_enabled", 10_000),
                ("full_host_gc_disabled", 10_000),
                ("component_profile_gc_disabled", 2048),
            )
        ),
        "zero_measured_rate_excess": all(
            arms[name]["maximum_rate_excess_rad_s"] == 0.0
            for name in (
                "full_host_gc_enabled",
                "full_host_gc_disabled",
                "component_profile_gc_disabled",
            )
        ),
        "no_robot_modules": modules_before == [] and modules_after == [],
        "no_robot_descriptors": descriptors_before == {} and descriptors_after == {},
        "raw_output_written": raw_output.is_file(),
    }
    checks = {name: bool(value) for name, value in checks.items()}
    failed = sorted(name for name, value in checks.items() if not value)
    basis = {
        "schema_version": "open_duck_x5.t251a_x5_compute_attribution_result.v1",
        "status": (
            "COMPLETE_T251A_X5_COMPUTE_ATTRIBUTION"
            if not failed
            else "HOLD_T251A_X5_COMPUTE_ATTRIBUTION"
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
            "cmdline": read_text("/proc/cmdline"),
            "nohz_full": read_text("/sys/devices/system/cpu/nohz_full"),
            "isolated": read_text("/sys/devices/system/cpu/isolated"),
            "rcu_nocbs": read_text("/sys/module/rcutree/parameters/rcu_nocbs"),
        },
        "preregistration": receipt(PREREGISTRATION),
        "host_source": receipt(host_source),
        "asset_receipts": asset_receipts,
        "raw_output": receipt(raw_output),
        "arms": arms,
        "classification": classify(arms),
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
    print(json.dumps(result["classification"], sort_keys=True))
    print(f"checks={len(checks) - len(failed)}/{len(checks)}")
    print(f"result_sha256={result['result_sha256']}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
