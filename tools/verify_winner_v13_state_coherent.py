#!/usr/bin/env python3
"""Verify the T250 state-coherent host with the exact selected CPU assets.

This verifier is offline-only.  It opens no serial, GPIO, I2C, controller, or
robot interface and it never imports the production runtime.  A pass earns
only the separately preregistered no-motion X5 CPU preflight.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from open_duck_x5.constants import (  # noqa: E402
    ACTION_DIM,
    ACTION_SCALE_RAD,
    CONTROL_FREQUENCY_HZ,
    CONTROL_PERIOD_NS,
    HOME_RAD,
    JOINT_NAMES,
    LEGACY_TARGET_RATE_LIMIT_RAD_S,
)
from open_duck_x5.winner_v2 import (  # noqa: E402
    WINNER_V2_HOME_RAD,
    WINNER_V2_PHASE_TABLE,
    WINNER_V2_RATE_LIMITS_RAD_S,
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
    / "t250_state_coherent_runtime_integration_preregistration_20260731.json"
)
PREREGISTRATION_SHA256 = "83970b0447dcb67ce5f56f381ebc8aa171db32e70003d4a029c0bf9d677a2114"
LOCOMOTION_TICKS = 8
FORBIDDEN_IMPORT_ROOTS = {
    "RPi",
    "gpiozero",
    "open_duck_x5.runtime",
    "open_duck_x5.servo_bus",
    "periphery",
    "pygame",
    "serial",
    "smbus2",
}


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


def percentile_summary(values_ns: list[int]) -> dict[str, float | int]:
    values = np.asarray(values_ns, dtype=np.float64) / 1_000_000.0
    return {
        "samples": int(values.size),
        "min_ms": float(np.min(values)),
        "mean_ms": float(np.mean(values)),
        "p50_ms": float(np.percentile(values, 50)),
        "p95_ms": float(np.percentile(values, 95)),
        "p99_ms": float(np.percentile(values, 99)),
        "max_ms": float(np.max(values)),
    }


def exact_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level
            imports.add(prefix + (node.module or ""))
    return imports


def production_consumers() -> list[str]:
    consumers: list[str] = []
    source_root = ROOT / "src" / "open_duck_x5"
    for path in sorted(source_root.rglob("*.py")):
        if path.name == "winner_v13_state_coherent.py":
            continue
        imports = exact_imports(path)
        if {
            ".winner_v13_state_coherent",
            "open_duck_x5.winner_v13_state_coherent",
        } & imports:
            consumers.append(path.relative_to(ROOT).as_posix())
    return consumers


def forbidden_host_imports() -> list[str]:
    path = ROOT / "src" / "open_duck_x5" / "winner_v13_state_coherent.py"
    imports = exact_imports(path)
    return sorted(
        value
        for value in imports
        if any(
            value == forbidden or value.startswith(forbidden + ".")
            for forbidden in FORBIDDEN_IMPORT_ROOTS
        )
        or value in {".winner_v12_two_stage", "open_duck_x5.winner_v12_two_stage"}
    )


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


def direct_session(path: Path) -> Any:
    import onnxruntime as ort

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
    if session.get_providers() != ["CPUExecutionProvider"]:
        raise RuntimeError(f"direct oracle did not bind CPU only: {session.get_providers()}")
    return session


@dataclass(frozen=True)
class ObserverParam:
    delay_ticks: int
    tau_s: float
    velocity_limit_rad_s: float


class IndependentP30Observer:
    """Small independent implementation used only by this verifier."""

    def __init__(self, fit_path: Path) -> None:
        value = json.loads(fit_path.read_text(encoding="utf-8"))
        primary = value.get("primary", value)
        joints = primary.get("joints", {})
        params: list[ObserverParam] = []
        for name in JOINT_NAMES:
            combined = joints.get(name, {}).get("combined")
            if combined is None:
                params.append(ObserverParam(0, 0.0, math.inf))
            else:
                params.append(
                    ObserverParam(
                        int(combined.get("delay_ticks", 0)),
                        float(combined.get("tau_s", 0.0)),
                        float(combined.get("velocity_limit_rad_s", math.inf)),
                    )
                )
        self.params = tuple(params)
        self.value = WINNER_V2_HOME_RAD.astype(np.float64)
        self.queues = [
            np.full(item.delay_ticks + 1, self.value[index], dtype=np.float64)
            for index, item in enumerate(self.params)
        ]

    def step(self, target: np.ndarray) -> None:
        next_value = self.value.copy()
        for index, item in enumerate(self.params):
            queue = self.queues[index]
            if queue.size > 1:
                queue[:-1] = queue[1:]
            queue[-1] = float(target[index])
            delayed = float(queue[0])
            if item.tau_s > 0.0:
                alpha = 1.0 - math.exp(-0.02 / item.tau_s)
                desired = self.value[index] + alpha * (delayed - self.value[index])
            else:
                desired = delayed
            step = desired - self.value[index]
            maximum = item.velocity_limit_rad_s * 0.02
            if math.isfinite(maximum):
                step = max(-maximum, min(maximum, step))
            next_value[index] = self.value[index] + step
        self.value = next_value


class IndependentHistory:
    def __init__(self) -> None:
        self.last = np.zeros(ACTION_DIM, dtype=np.float32)
        self.minus_2 = np.zeros(ACTION_DIM, dtype=np.float32)
        self.minus_3 = np.zeros(ACTION_DIM, dtype=np.float32)
        self.deferred = np.zeros(ACTION_DIM, dtype=np.float32)

    @property
    def visible(self) -> np.ndarray:
        return np.concatenate((self.last, self.minus_2, self.minus_3))

    def commit(self, action: np.ndarray) -> None:
        self.minus_3 = self.minus_2.copy()
        self.minus_2 = self.last.copy()
        self.last = self.deferred.copy()
        self.deferred = action.copy()


def validate_asset(
    path: Path,
    expected: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    value = receipt(path)
    passed = value["bytes"] == int(expected["bytes"]) and value["sha256"] == expected["sha256"]
    return value, passed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify the exact T250 two-stage host with no hardware access"
    )
    parser.add_argument("--calibrator", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--p30-fit", type=Path, required=True)
    parser.add_argument("--reference-table", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists() or args.markdown.exists():
        raise FileExistsError("refusing to overwrite a frozen verification artifact")
    tracked_status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        text=True,
    ).strip()
    if tracked_status:
        raise RuntimeError("verification requires a clean tracked worktree")
    prereg_receipt = receipt(PREREGISTRATION)
    if prereg_receipt["sha256"] != PREREGISTRATION_SHA256:
        raise RuntimeError("T250 runtime-integration preregistration changed")
    prereg = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))

    asset_paths = {
        "calibrator": args.calibrator,
        "deployment_policy": args.policy,
        "fixed_p30_runtime_observer_fit": args.p30_fit,
        "projected_reference_table": args.reference_table,
    }
    asset_expectations = {
        "calibrator": prereg["assets"]["calibrator"],
        "deployment_policy": prereg["assets"]["deployment_policy"],
        "fixed_p30_runtime_observer_fit": prereg["assets"]["fixed_p30_runtime_observer_fit"],
        "projected_reference_table": prereg["assets"]["projected_reference_table"],
    }
    asset_receipts: dict[str, dict[str, Any]] = {}
    asset_checks: dict[str, bool] = {}
    for name, path in asset_paths.items():
        asset_receipts[name], asset_checks[name] = validate_asset(
            path,
            asset_expectations[name],
        )
    if not all(asset_checks.values()):
        raise RuntimeError(f"selected asset receipt mismatch: {asset_checks}")

    frozen_source_checks: dict[str, bool] = {}
    frozen_source_receipts: dict[str, dict[str, Any]] = {}
    for relative, expected_hash in prereg["frozen_existing_sources"].items():
        path = ROOT / relative
        frozen_source_receipts[relative] = receipt(path)
        frozen_source_checks[relative] = sha256(path) == expected_hash

    host = WinnerV13StateCoherentTransaction(
        calibrator=GraphAsset(
            args.calibrator,
            calibrator_spec(),
            frozenset({asset_receipts["calibrator"]["sha256"]}),
        ),
        locomotion=GraphAsset(
            args.policy,
            locomotion_spec(),
            frozenset({asset_receipts["deployment_policy"]["sha256"]}),
        ),
        p30_fit=P30FitAsset(
            args.p30_fit,
            frozenset({asset_receipts["fixed_p30_runtime_observer_fit"]["sha256"]}),
        ),
        reference_table_path=args.reference_table,
        enabled=True,
        warmup_runs=1,
    )
    direct_calibrator = direct_session(args.calibrator)
    direct_policy = direct_session(args.policy)
    oracle_previous = np.zeros((1, ACTION_DIM), dtype=np.float32)
    oracle_hidden = np.zeros((1, 64), dtype=np.float32)
    observer = IndependentP30Observer(args.p30_fit)
    history = IndependentHistory()
    previous_sent = WINNER_V2_HOME_RAD.copy()
    final_calibration_actions: list[np.ndarray] = []
    stage_ns: list[int] = []
    maximum_graph_delta = 0.0
    maximum_observer_delta = 0.0
    maximum_target_delta = 0.0
    maximum_physical_delta = 0.0
    maximum_rate_monitor_delta = 0.0
    maximum_calibration_field_delta = 0.0
    maximum_locomotion_field_delta = 0.0
    maximum_rate_excess = 0.0
    all_finite = True
    soft_offsets = np.linspace(-0.001, 0.001, ACTION_DIM, dtype=np.float64)
    command = np.zeros(7, dtype=np.float64)
    command[0] = 0.074
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
        "soft_offsets_rad": soft_offsets,
    }

    for tick in range(CALIBRATION_TICKS):
        started = time.perf_counter_ns()
        host.stage_tick(
            tick_index=tick,
            logical_period_ns=CONTROL_PERIOD_NS,
            servo_sample_tick_index=tick,
            imu_sample_tick_index=tick,
            contacts_sample_tick_index=tick,
            **samples,
        )
        stage_ns.append(time.perf_counter_ns() - started)
        observation = host.observation_view.copy()
        expected_fixed = np.zeros(115, dtype=np.float32)
        expected_fixed[3:6] = np.asarray([0.0, 0.0, 9.81], dtype=np.float32)
        expected_fixed[41:83] = history.visible
        expected_fixed[83:97] = observer.value
        expected_fixed[97:99] = 1.0
        expected_fixed[99] = 1.0
        maximum_calibration_field_delta = max(
            maximum_calibration_field_delta,
            float(np.max(np.abs(observation - expected_fixed))),
        )
        direct_action, direct_previous, direct_hidden = direct_calibrator.run(
            ["calibration_actions", "previous_action_out", "h_out"],
            {
                "obs": observation[None, :],
                "previous_action": oracle_previous,
                "h_in": oracle_hidden,
            },
        )
        action = host.normalized_action_view.copy()
        maximum_graph_delta = max(
            maximum_graph_delta,
            float(np.max(np.abs(action - direct_action[0]))),
            float(np.max(np.abs(direct_action - direct_previous))),
        )
        desired = (WINNER_V2_HOME_RAD + np.float32(ACTION_SCALE_RAD) * action).astype(np.float32)
        max_step = np.float32(LEGACY_TARGET_RATE_LIMIT_RAD_S / CONTROL_FREQUENCY_HZ)
        expected_sent = np.clip(
            desired,
            previous_sent - max_step,
            previous_sent + max_step,
        )
        maximum_target_delta = max(
            maximum_target_delta,
            float(np.max(np.abs(host.logical_target_view - expected_sent))),
        )
        expected_physical = expected_sent.astype(np.float64) + soft_offsets
        maximum_physical_delta = max(
            maximum_physical_delta,
            float(np.max(np.abs(host.physical_target_view - expected_physical))),
        )
        host.complete_send(write_succeeded=True)
        observer.step(expected_sent)
        maximum_observer_delta = max(
            maximum_observer_delta,
            float(np.max(np.abs(host.observer.value_view - observer.value))),
        )
        history.commit(action)
        previous_sent = expected_sent.copy()
        oracle_previous = direct_previous.astype(np.float32, copy=True)
        oracle_hidden = direct_hidden.astype(np.float32, copy=True)
        final_calibration_actions.append(action)
        final_calibration_actions = final_calibration_actions[-3:]
        all_finite = all_finite and all(
            bool(np.isfinite(value).all())
            for value in (
                observation,
                action,
                host.logical_target_view,
                host.physical_target_view,
                host.observer.value_view,
                oracle_previous,
                oracle_hidden,
            )
        )

    host.confirm_calibration_handoff(True)
    context = oracle_hidden.copy()
    context_sha = hashlib.sha256(context.tobytes()).hexdigest()
    host_context_before = host.calibration_context
    handoff_previous_delta = float(
        np.max(np.abs(host.locomotion_previous_action - oracle_previous[0]))
    )
    handoff_context_delta = float(np.max(np.abs(host_context_before - context[0])))
    handoff_hidden_nonzero = int(np.count_nonzero(host.locomotion_hidden))
    oracle_previous = oracle_previous.copy()
    oracle_hidden = np.zeros((1, 64), dtype=np.float32)

    with np.load(args.reference_table, allow_pickle=False) as table:
        reference_commands = np.asarray(table["commands"], dtype=np.float32)
        reference_actions = np.asarray(table["actions"], dtype=np.float32)
    command3 = np.asarray([0.074, 0.0, 0.0], dtype=np.float32)
    command_index = int(np.argmin(np.sum(np.abs(reference_commands - command3), axis=1)))
    first_observation = None
    second_observation = None
    final_three = np.stack(final_calibration_actions[::-1])

    for local_tick in range(LOCOMOTION_TICKS):
        tick = CALIBRATION_TICKS + local_tick
        started = time.perf_counter_ns()
        host.stage_tick(
            tick_index=tick,
            logical_period_ns=CONTROL_PERIOD_NS,
            servo_sample_tick_index=tick,
            imu_sample_tick_index=tick,
            contacts_sample_tick_index=tick,
            **samples,
        )
        stage_ns.append(time.perf_counter_ns() - started)
        observation = host.observation_view.copy()
        if local_tick == 0:
            first_observation = observation.copy()
            expected_history = final_three.reshape(-1)
        else:
            expected_history = history.visible
            if local_tick == 1:
                second_observation = observation.copy()
        expected_reference = reference_actions[
            command_index,
            local_tick % reference_actions.shape[1],
        ]
        expected_fields = np.concatenate(
            (
                command.astype(np.float32),
                expected_history,
                observer.value.astype(np.float32),
                WINNER_V2_PHASE_TABLE[local_tick],
                expected_reference,
            )
        )
        observed_fields = np.concatenate(
            (
                observation[6:13],
                observation[41:83],
                observation[83:97],
                observation[99:101],
                observation[101:115],
            )
        )
        maximum_locomotion_field_delta = max(
            maximum_locomotion_field_delta,
            float(np.max(np.abs(observed_fields - expected_fields))),
        )
        direct_action, direct_previous, direct_hidden = direct_policy.run(
            ["continuous_actions", "previous_action_out", "h_out"],
            {
                "obs": observation[None, :],
                "previous_action": oracle_previous,
                "h_in": oracle_hidden,
                "calibration_context": context,
            },
        )
        action = host.normalized_action_view.copy()
        maximum_graph_delta = max(
            maximum_graph_delta,
            float(np.max(np.abs(action - direct_action[0]))),
            float(np.max(np.abs(direct_action - direct_previous))),
        )
        expected_sent = (WINNER_V2_HOME_RAD + np.float32(ACTION_SCALE_RAD) * action).astype(
            np.float32
        )
        maximum_target_delta = max(
            maximum_target_delta,
            float(np.max(np.abs(host.logical_target_view - expected_sent))),
        )
        maximum_physical_delta = max(
            maximum_physical_delta,
            float(
                np.max(
                    np.abs(
                        host.physical_target_view
                        - (expected_sent.astype(np.float64) + soft_offsets)
                    )
                )
            ),
        )
        maximum_rate_excess = max(
            maximum_rate_excess,
            float(np.max(host.target_pipeline.graph_rate_excess_rad_s)),
        )
        expected_rate_excess = np.maximum(
            np.abs(
                (expected_sent.astype(np.float64) - previous_sent.astype(np.float64))
                * CONTROL_FREQUENCY_HZ
            )
            - WINNER_V2_RATE_LIMITS_RAD_S,
            0.0,
        )
        expected_rate_excess[expected_rate_excess <= 1.0e-5] = 0.0
        maximum_rate_monitor_delta = max(
            maximum_rate_monitor_delta,
            float(
                np.max(np.abs(host.target_pipeline.graph_rate_excess_rad_s - expected_rate_excess))
            ),
        )
        host.complete_send(write_succeeded=True)
        observer.step(expected_sent)
        maximum_observer_delta = max(
            maximum_observer_delta,
            float(np.max(np.abs(host.observer.value_view - observer.value))),
        )
        history.commit(action)
        previous_sent = expected_sent.copy()
        oracle_previous = direct_previous.astype(np.float32, copy=True)
        oracle_hidden = direct_hidden.astype(np.float32, copy=True)
        all_finite = all_finite and all(
            bool(np.isfinite(value).all())
            for value in (
                observation,
                action,
                host.logical_target_view,
                host.physical_target_view,
                host.observer.value_view,
                oracle_previous,
                oracle_hidden,
            )
        )

    assert first_observation is not None and second_observation is not None
    host_context_after = host.calibration_context
    context_after_sha = hashlib.sha256(host_context_after.tobytes()).hexdigest()
    checks = {
        "all_selected_asset_receipts_exact": all(asset_checks.values()),
        "all_frozen_predecessor_sources_exact": all(frozen_source_checks.values()),
        "tracked_worktree_clean_at_execution": tracked_status == "",
        "new_host_has_no_production_consumer": production_consumers() == [],
        "new_host_has_no_hardware_or_winner_v12_import": forbidden_host_imports() == [],
        "exact_250_calibration_ticks": host.confirmed_calibration_ticks == CALIBRATION_TICKS,
        "zero_home_return_ticks": host.confirmed_home_return_ticks == HOME_RETURN_TICKS == 0,
        "real_graph_chain_bit_exact": maximum_graph_delta == 0.0,
        "calibration_observation_fields_exact": maximum_calibration_field_delta == 0.0,
        "locomotion_observation_fields_exact": maximum_locomotion_field_delta == 0.0,
        "independent_p30_observer_exact": maximum_observer_delta == 0.0,
        "logical_target_pipeline_exact": maximum_target_delta == 0.0,
        "soft_offsets_physical_only_exact": maximum_physical_delta == 0.0,
        "handoff_previous_action_exact": handoff_previous_delta == 0.0,
        "handoff_context_exact": handoff_context_delta == 0.0,
        "locomotion_hidden_exact_zero": handoff_hidden_nonzero == 0,
        "context_immutable": context_sha == context_after_sha,
        "first_locomotion_history_final_three_exact": np.array_equal(
            first_observation[41:83], final_three.reshape(-1)
        ),
        "second_locomotion_history_boundary_exact": np.array_equal(
            second_observation[41:83], final_three.reshape(-1)
        ),
        "first_locomotion_phase_reset_exact": np.array_equal(
            first_observation[99:101],
            np.asarray([1.0, 0.0], dtype=np.float32),
        ),
        "locomotion_5p24_slew_identity": maximum_target_delta == 0.0,
        "measured_rate_monitor_exact": maximum_rate_monitor_delta == 0.0,
        "zero_measured_rate_excess": maximum_rate_excess == 0.0,
        "all_values_finite": all_finite,
        "cpu_only_no_hardware_execution": True,
    }
    checks = {name: bool(value) for name, value in checks.items()}
    failed = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed
    result_basis = {
        "schema_version": "open_duck_x5.t250_state_coherent_runtime_integration_result.v1",
        "status": (
            "PASS_T250_STATE_COHERENT_RUNTIME_INTEGRATION"
            if passed
            else "HOLD_T250_STATE_COHERENT_RUNTIME_INTEGRATION"
        ),
        "decision": (
            "EARN_NO_MOTION_X5_CPU_PREFLIGHT_PREREGISTRATION_ONLY"
            if passed
            else "HOLD_VERSIONED_RUNTIME_INTEGRATION"
        ),
        "date": "2026-07-31",
        "git": {
            "repository": subprocess.check_output(
                ["git", "remote", "get-url", "origin"],
                cwd=ROOT,
                text=True,
            ).strip(),
            "branch": subprocess.check_output(
                ["git", "branch", "--show-current"],
                cwd=ROOT,
                text=True,
            ).strip(),
            "commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=ROOT,
                text=True,
            ).strip(),
        },
        "preregistration": prereg_receipt,
        "asset_receipts": asset_receipts,
        "frozen_source_receipts": frozen_source_receipts,
        "implementation_receipts": {
            "host": receipt(ROOT / "src" / "open_duck_x5" / "winner_v13_state_coherent.py"),
            "tests": receipt(ROOT / "tests" / "test_winner_v13_state_coherent.py"),
            "verifier": receipt(Path(__file__)),
        },
        "execution": {
            "calibration_ticks": CALIBRATION_TICKS,
            "home_return_ticks": HOME_RETURN_TICKS,
            "locomotion_ticks": LOCOMOTION_TICKS,
            "simulator_steps": 0,
            "optimizer_steps": 0,
            "hosted_compute_units": 0,
            "rdkx5_or_robot_access": 0,
            "policy_binaries_copied": 0,
            "stage_latency_offline_windows_host": percentile_summary(stage_ns),
        },
        "maximum_deltas": {
            "direct_onnx_action_or_state": maximum_graph_delta,
            "calibration_observation_field": maximum_calibration_field_delta,
            "locomotion_observation_field": maximum_locomotion_field_delta,
            "independent_observer_rad": maximum_observer_delta,
            "logical_target_rad": maximum_target_delta,
            "physical_target_rad": maximum_physical_delta,
            "handoff_previous_action": handoff_previous_delta,
            "handoff_context": handoff_context_delta,
            "measured_rate_excess_rad_s": maximum_rate_excess,
            "measured_rate_monitor_rad_s": maximum_rate_monitor_delta,
        },
        "handoff": {
            "calibration_context_sha256": context_sha,
            "locomotion_hidden_nonzero": handoff_hidden_nonzero,
            "first_history_sha256": hashlib.sha256(first_observation[41:83].tobytes()).hexdigest(),
            "second_history_sha256": hashlib.sha256(
                second_observation[41:83].tobytes()
            ).hexdigest(),
            "final_three_calibration_actions_sha256": hashlib.sha256(
                final_three.tobytes()
            ).hexdigest(),
        },
        "checks": checks,
        "failed_checks": failed,
        "authority": {
            "offline_cpu_only": True,
            "no_motion_x5_cpu_preflight": False,
            "policy_binary_staging": False,
            "gate5": False,
            "robot_motion": False,
            "grounded_replay": False,
        },
    }
    result = {**result_basis, "result_sha256": canonical_sha256(result_basis)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# T250 state-coherent runtime integration result",
        "",
        f"- Status: `{result['status']}`",
        f"- Decision: `{result['decision']}`",
        f"- Checks: `{len(checks) - len(failed)}/{len(checks)}`",
        f"- Calibration/home-return/locomotion ticks: `{CALIBRATION_TICKS}/0/{LOCOMOTION_TICKS}`",
        f"- Maximum direct-ONNX delta: `{maximum_graph_delta}`",
        "- Maximum observation-field delta: "
        f"`{max(maximum_calibration_field_delta, maximum_locomotion_field_delta)}`",
        f"- Maximum independent-observer delta: `{maximum_observer_delta}` rad",
        f"- Maximum measured-rate excess: `{maximum_rate_excess}` rad/s",
        f"- Result SHA-256: `{result['result_sha256']}`",
        "",
        "This was an offline CPU-only real-asset verification. It used no "
        "simulator, hosted training, X5, serial bus, torque, or robot access. "
        "A pass earns only a separately preregistered no-motion X5 CPU "
        "preflight; Hardware Gate 5 remains `NOT_RUN`.",
    ]
    if failed:
        lines.extend(["", "## Failed checks", "", *[f"- `{name}`" for name in failed]])
    args.markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(result["status"])
    print(f"checks={len(checks) - len(failed)}/{len(checks)}")
    print(f"result_sha256={result['result_sha256']}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
