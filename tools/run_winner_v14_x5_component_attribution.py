#!/usr/bin/env python3
"""Run the preregistered T251A3 no-device X5 component attribution."""

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
    GraphAsset,
    P30FitAsset,
)
from tools.run_winner_v14_x5_paced_screen import (  # noqa: E402
    calibrator_spec,
    canonical_sha256,
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
from tools.winner_v14_optimized import WinnerV14X5OptimizedTransaction  # noqa: E402

PREREGISTRATION = (
    ROOT
    / "artifacts"
    / "gates"
    / "phase_5_policy"
    / "t251a3_x5_single_host_component_attribution_preregistration_20260731.json"
)
PREREGISTRATION_SHA256 = "3e2fb876070901eaa9167c5402f6017d5b653702971065df25515469cbbd6b8f"
EXPECTED_ROOT = Path("/home/sunrise/open_duck_x5_preflight/t251a3")


class _TimedSession:
    """Transparent ONNX session proxy that records only run_with_iobinding."""

    def __init__(self, inner: object, sink: list[int]) -> None:
        self._inner = inner
        self._sink = sink

    def run_with_iobinding(self, binding: object) -> object:
        started = time.perf_counter_ns()
        try:
            return self._inner.run_with_iobinding(binding)
        finally:
            self._sink.append(time.perf_counter_ns() - started)

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


class ComponentProfiler:
    """Instance-only wrappers around exact optimized-host stage components."""

    def __init__(self, host: WinnerV14X5OptimizedTransaction) -> None:
        self.values: dict[str, list[int]] = {
            "observation": [],
            "graph_total": [],
            "onnx": [],
            "target": [],
            "observer_stage": [],
        }
        host._calibrator.session = _TimedSession(
            host._calibrator.session,
            self.values["onnx"],
        )
        host._locomotion.session = _TimedSession(
            host._locomotion.session,
            self.values["onnx"],
        )
        self._wrap(host.assembler, "build", "observation")
        self._wrap(host._calibrator, "stage", "graph_total")
        self._wrap(host._locomotion, "stage", "graph_total")
        self._wrap(host.target_pipeline, "stage", "target")
        self._wrap(host.observer, "stage_confirmed_target", "observer_stage")

    def _wrap(self, owner: object, attribute: str, label: str) -> None:
        original = getattr(owner, attribute)

        def timed(*args: object, **kwargs: object) -> object:
            started = time.perf_counter_ns()
            try:
                return original(*args, **kwargs)
            finally:
                self.values[label].append(time.perf_counter_ns() - started)

        setattr(owner, attribute, timed)

    def arrays(self, stage_ns: np.ndarray) -> dict[str, np.ndarray]:
        count = int(stage_ns.size)
        arrays = {
            name: np.asarray(values, dtype=np.int64)
            for name, values in self.values.items()
        }
        lengths = {name: int(value.size) for name, value in arrays.items()}
        if any(length != count for length in lengths.values()):
            raise RuntimeError(
                f"component timer population mismatch: stage={count}, components={lengths}"
            )
        arrays["graph_host"] = arrays["graph_total"] - arrays["onnx"]
        arrays["transaction_residual"] = stage_ns - (
            arrays["observation"]
            + arrays["graph_total"]
            + arrays["target"]
            + arrays["observer_stage"]
        )
        return arrays


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run T251A3 X5 component attribution")
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--calibrator", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--p30-fit", type=Path, required=True)
    parser.add_argument("--reference-table", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path, required=True)
    return parser.parse_args()


def build_host(paths: dict[str, Path], prereg: dict[str, Any]) -> WinnerV14X5OptimizedTransaction:
    assets = prereg["unchanged_assets"]
    return WinnerV14X5OptimizedTransaction(
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
        warmup_runs=int(prereg["platform"]["warmup_runs_per_graph"]),
    )


def run_arm(
    *,
    spec: dict[str, Any],
    paths: dict[str, Path],
    prereg: dict[str, Any],
    profile: bool,
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    host = build_host(paths, prereg)
    profiler = ComponentProfiler(host) if profile else None
    locomotion_ticks = int(spec["locomotion_ticks"])
    total_ticks = CALIBRATION_TICKS + locomotion_ticks
    stage_ns = np.empty(total_ticks, dtype=np.int64)
    commit_ns = np.empty(total_ticks, dtype=np.int64)
    release_lateness_ns = np.empty(total_ticks, dtype=np.int64)
    actions = np.empty((total_ticks, ACTION_DIM), dtype=np.float32)
    sample = samples(float(spec["command_x_m_s"]))
    maximum_rate_excess = 0.0
    gc_was_enabled = gc.isenabled()
    gc.collect()
    gc.disable()
    release_epoch = time.perf_counter_ns()
    try:
        for tick in range(total_ticks):
            deadline = release_epoch + tick * CONTROL_PERIOD_NS
            remaining = deadline - time.perf_counter_ns()
            if remaining > 0:
                time.sleep(remaining / 1_000_000_000.0)
            release_lateness_ns[tick] = max(0, time.perf_counter_ns() - deadline)
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
    finally:
        if gc_was_enabled:
            gc.enable()
        else:
            gc.disable()

    component_arrays = profiler.arrays(stage_ns) if profiler is not None else {}
    locomotion_slice = slice(CALIBRATION_TICKS, None)
    arm = {
        "id": spec["id"],
        "calibration_ticks": host.confirmed_calibration_ticks,
        "home_return_ticks": host.confirmed_home_return_ticks,
        "locomotion_ticks": host.confirmed_locomotion_ticks,
        "stage_all": summary_ns(stage_ns),
        "stage_locomotion": summary_ns(stage_ns[locomotion_slice]),
        "commit_all": summary_ns(commit_ns),
        "release_lateness": summary_ns(release_lateness_ns),
        "action_trace_sha256": hashlib.sha256(actions.tobytes()).hexdigest(),
        "expected_action_trace_sha256": spec["expected_action_trace_sha256"],
        "maximum_rate_excess_rad_s": maximum_rate_excess,
        "components_locomotion": {
            name: summary_ns(values[locomotion_slice])
            for name, values in component_arrays.items()
        },
    }
    arrays = {
        "stage_ns": stage_ns,
        "commit_ns": commit_ns,
        "release_lateness_ns": release_lateness_ns,
        "actions": actions,
        **{f"component_{name}_ns": value for name, value in component_arrays.items()},
    }
    return arm, arrays


def main() -> int:
    args = parse_args()
    root = args.staging_root.resolve()
    if root != EXPECTED_ROOT:
        raise RuntimeError(f"unpreregistered staging root: {root}")
    output = require_inside(args.output, root, "output")
    raw_output = require_inside(args.raw_output, root, "raw output")
    if output.exists() or raw_output.exists():
        raise FileExistsError("refusing to overwrite T251A3 output")
    machine = platform.machine().lower()
    if not sys.platform.startswith("linux") or machine not in {"aarch64", "arm64"}:
        raise RuntimeError("T251A3 requires aarch64 Linux")
    if sha256(PREREGISTRATION) != PREREGISTRATION_SHA256:
        raise RuntimeError("T251A3 preregistration changed")
    prereg = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))

    source_paths = {
        label.removesuffix("_source"): ROOT / value
        for label, value in prereg["exact_sources"].items()
        if label.endswith("_source")
    }
    source_checks = {
        name: sha256(path)
        == prereg["exact_sources"][f"{name}_source_sha256"]
        for name, path in source_paths.items()
    }
    tracked_status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        text=True,
    ).strip()
    if tracked_status or not all(source_checks.values()):
        raise RuntimeError(
            f"T251A3 requires clean exact sources: dirty={bool(tracked_status)} "
            f"checks={source_checks}"
        )

    paths = {
        "calibrator": require_inside(args.calibrator, root, "calibrator"),
        "deployment_policy": require_inside(args.policy, root, "policy"),
        "fixed_p30_runtime_observer_fit": require_inside(args.p30_fit, root, "P30 fit"),
        "projected_reference_table": require_inside(
            args.reference_table,
            root,
            "reference table",
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
        raise RuntimeError(f"T251A3 asset mismatch: {asset_checks}")

    scheduler = os.sched_getscheduler(0)
    priority = os.sched_getparam(0).sched_priority
    affinity = sorted(os.sched_getaffinity(0))
    governor = Path(
        f"/sys/devices/system/cpu/cpu{affinity[0]}/cpufreq/scaling_governor"
    ).read_text(encoding="utf-8").strip()
    descriptors_before = robot_descriptors(open_descriptors())
    modules_before = loaded_robot_modules()

    arm_specs = prereg["arms_in_fixed_order"]
    uninstrumented, uninstrumented_arrays = run_arm(
        spec=arm_specs[0],
        paths=paths,
        prereg=prereg,
        profile=False,
    )
    profiled, profiled_arrays = run_arm(
        spec=arm_specs[1],
        paths=paths,
        prereg=prereg,
        profile=True,
    )
    arms = {
        uninstrumented["id"]: uninstrumented,
        profiled["id"]: profiled,
    }
    raw_arrays = {
        **{f"uninstrumented_{name}": value for name, value in uninstrumented_arrays.items()},
        **{f"profiled_{name}": value for name, value in profiled_arrays.items()},
    }
    np.savez_compressed(raw_output, **raw_arrays)

    descriptors_after = robot_descriptors(open_descriptors())
    modules_after = loaded_robot_modules()
    components = profiled["components_locomotion"]
    accounting_arrays = {
        name: value
        for name, value in profiled_arrays.items()
        if name.startswith("component_")
    }
    accounting_nonnegative = all(bool(np.all(value >= 0)) for value in accounting_arrays.values())
    exact_traces = all(
        arm["action_trace_sha256"] == arm["expected_action_trace_sha256"]
        for arm in arms.values()
    )
    exact_chains = all(
        arm["calibration_ticks"] == CALIBRATION_TICKS
        and arm["home_return_ticks"] == 0
        and arm["locomotion_ticks"] == int(spec["locomotion_ticks"])
        for arm, spec in zip(arms.values(), arm_specs, strict=True)
    )
    reserve = prereg["reference_only_limits_ms"]
    single_timing = uninstrumented["stage_locomotion"]
    clears_reference_reserve = (
        single_timing["p99_ms"] <= float(reserve["p99"])
        and single_timing["p99_9_ms"] <= float(reserve["p99_9"])
        and single_timing["max_ms"] <= float(reserve["max"])
    )
    candidate_components = {
        name: value["p50_ms"]
        for name, value in components.items()
        if name in {"observation", "graph_host", "target", "observer_stage", "transaction_residual"}
    }
    largest_non_onnx_component = max(candidate_components, key=candidate_components.get)
    checks = {
        "asset_receipts_exact": all(asset_checks.values()),
        "implementation_sources_exact": all(source_checks.values()),
        "tracked_source_clean": tracked_status == "",
        "aarch64_linux": sys.platform.startswith("linux") and machine in {"aarch64", "arm64"},
        "sched_fifo_priority_80": scheduler == os.SCHED_FIFO and priority == 80,
        "single_cpu7_affinity": affinity == [7],
        "performance_governor": governor == "performance",
        "exact_action_trace_prefixes": exact_traces,
        "exact_250_0_arm_chains": exact_chains,
        "zero_measured_rate_excess": all(
            arm["maximum_rate_excess_rad_s"] == 0.0 for arm in arms.values()
        ),
        "component_accounting_nonnegative_and_complete": accounting_nonnegative,
        "no_robot_modules": modules_before == [] and modules_after == [],
        "no_robot_descriptors": descriptors_before == {} and descriptors_after == {},
    }
    checks = {name: bool(value) for name, value in checks.items()}
    failed = sorted(name for name, value in checks.items() if not value)
    if failed:
        decision = "HOLD_AND_FIX_THE_ATTRIBUTION_HARNESS_WITHOUT_TIMING_CLAIMS"
    elif clears_reference_reserve:
        decision = (
            "ATTRIBUTE_T251A2_MISS_TO_PAIRED_ORACLE_COHABITATION_AND_PREREGISTER_"
            "A_SEPARATED_SEMANTIC_PLUS_TIMING_SCREEN"
        )
    else:
        decision = f"CHANGE_ONLY_MEASURED_HOST_COMPONENT:{largest_non_onnx_component}"

    basis = {
        "schema_version": "open_duck_x5.t251a3_x5_component_attribution_result.v1",
        "status": (
            "COMPLETE_T251A3_X5_SINGLE_HOST_COMPONENT_ATTRIBUTION"
            if not failed
            else "HOLD_T251A3_X5_SINGLE_HOST_COMPONENT_ATTRIBUTION"
        ),
        "decision": decision,
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
        "arms": arms,
        "attribution": {
            "single_host_clears_reference_reserve": clears_reference_reserve,
            "reference_reserve_selection_weight": 0,
            "largest_non_onnx_host_component_by_p50": largest_non_onnx_component,
            "non_onnx_host_component_p50_ms": candidate_components,
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
            "t251b_earned": False,
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
        "single_optimized_stage_ms="
        f"p99:{single_timing['p99_ms']:.6f},"
        f"p99.9:{single_timing['p99_9_ms']:.6f},"
        f"max:{single_timing['max_ms']:.6f}"
    )
    print(f"decision={decision}")
    print(f"result_sha256={result['result_sha256']}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
