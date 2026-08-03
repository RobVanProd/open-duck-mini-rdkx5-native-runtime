#!/usr/bin/env python3
"""Verify the preregistered exact context-route specialization of T247."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import onnx
import onnxruntime as ort
from onnx import checker, numpy_helper

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from open_duck_x5.constants import ACTION_DIM  # noqa: E402
from open_duck_x5.winner_v13_state_coherent import (  # noqa: E402
    CALIBRATION_TICKS,
    GraphAsset,
    P30FitAsset,
)
from tools.derive_t247_context_route_variants import (  # noqa: E402
    EXPECTED_POLICY_SHA256,
    POLICY_OUTPUTS,
    ROUTE_NAMES,
    ROUTER_OUTPUTS,
    derive,
    route_from_predicates,
    sha256,
)
from tools.run_winner_v14_x5_paced_screen import (  # noqa: E402
    calibrator_spec,
    locomotion_spec,
    samples,
    stage,
)
from tools.verify_winner_v15_graph_host_optimized import (  # noqa: E402
    exact_pairs,
)
from tools.winner_v16_target_optimized import (  # noqa: E402
    WinnerV16TargetOptimizedTransaction,
)

PREREGISTRATION = (
    ROOT
    / "artifacts"
    / "gates"
    / "phase_5_policy"
    / "t247_deployment_context_route_specialization_preregistration_20260731.json"
)
PREREGISTRATION_SHA256 = (
    "4a038b0db38703e9a8adbd2439c1c23d82d09805a7119985874cbde48cd5a5ec"
)
EXPECTED_CONTEXT_SHA256 = (
    "a59216123ca92bb3ce9a02cd3af8d898e708c59ae317bf2b9fac8a276e41c404"
)
LOCOMOTION_TICKS = 2_048
ONE_STEP_CASES_PER_CONTEXT = 256
TIMING_WARMUP_SAMPLES = 2_000
TIMING_SAMPLES = 20_000
TIMING_RATIO_LIMIT = 0.88
COMMANDS_M_S = (0.0, 0.074, 0.077, 0.08)


class VerificationError(RuntimeError):
    """Raised when an exact specialization contract check fails."""


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def receipt(path: Path) -> dict[str, Any]:
    path = path.resolve()
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def session_options() -> ort.SessionOptions:
    options = ort.SessionOptions()
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    options.add_session_config_entry("session.inter_op.allow_spinning", "0")
    return options


def create_session(path: Path) -> ort.InferenceSession:
    session = ort.InferenceSession(
        str(path),
        sess_options=session_options(),
        providers=["CPUExecutionProvider"],
    )
    if session.get_providers() != ["CPUExecutionProvider"]:
        raise VerificationError("specialization requires CPUExecutionProvider only")
    return session


def graph_abi(model: onnx.ModelProto) -> dict[str, list[dict[str, Any]]]:
    def values(values: Any) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for value in values:
            tensor = value.type.tensor_type
            result.append(
                {
                    "name": value.name,
                    "elem_type": tensor.elem_type,
                    "shape": [dimension.dim_value for dimension in tensor.shape.dim],
                }
            )
        return result

    return {"inputs": values(model.graph.input), "outputs": values(model.graph.output)}


def verify_derivation(
    policy: Path, derived_root: Path
) -> tuple[dict[str, Any], dict[str, Path]]:
    first = derived_root / "derive-a"
    second = derived_root / "derive-b"
    manifest_a = derive(policy, first)
    manifest_b = derive(policy, second)
    names_a = sorted(path.name for path in first.iterdir() if path.is_file())
    names_b = sorted(path.name for path in second.iterdir() if path.is_file())
    deterministic = names_a == names_b and all(
        (first / name).read_bytes() == (second / name).read_bytes()
        for name in names_a
    )
    if not deterministic or manifest_a != manifest_b:
        raise VerificationError("repeated route derivation is not byte deterministic")

    source = onnx.load(policy, load_external_data=False)
    source_abi = graph_abi(source)
    source_initializers = {
        initializer.name: initializer.SerializeToString(deterministic=True)
        for initializer in source.graph.initializer
    }
    variant_receipts: dict[str, Any] = {}
    all_abi_exact = True
    all_initializers_exact = True
    all_checker_pass = True
    paths: dict[str, Path] = {
        "router": first / "policy.context-router.onnx",
        "instrumented": first / "policy.instrumented-routes.onnx",
    }
    for route in ROUTE_NAMES:
        path = first / f"policy.{route}.onnx"
        paths[route] = path
        model = onnx.load(path, load_external_data=False)
        try:
            checker.check_model(model, full_check=True)
        except Exception:
            all_checker_pass = False
        abi_exact = graph_abi(model) == source_abi
        initializer_exact = all(
            initializer.name in source_initializers
            and initializer.SerializeToString(deterministic=True)
            == source_initializers[initializer.name]
            for initializer in model.graph.initializer
        )
        all_abi_exact = all_abi_exact and abi_exact
        all_initializers_exact = all_initializers_exact and initializer_exact
        variant_receipts[route] = {
            **receipt(path),
            "nodes": len(model.graph.node),
            "initializers": len(model.graph.initializer),
            "abi_exact": abi_exact,
            "retained_initializers_exact": initializer_exact,
        }
    for key in ("router", "instrumented"):
        try:
            checker.check_model(onnx.load(paths[key]), full_check=True)
        except Exception:
            all_checker_pass = False
    if not all_checker_pass or not all_abi_exact or not all_initializers_exact:
        raise VerificationError("derived graph structure or initializer contract failed")

    return (
        {
            "derive_a_manifest": manifest_a,
            "derive_b_manifest": manifest_b,
            "generated_filenames": names_a,
            "derive_twice_byte_exact": deterministic,
            "all_onnx_checker_pass": all_checker_pass,
            "all_policy_abis_exact": all_abi_exact,
            "all_retained_initializers_exact": all_initializers_exact,
            "router": receipt(paths["router"]),
            "instrumented": receipt(paths["instrumented"]),
            "variants": variant_receipts,
        },
        paths,
    )


def router_coefficients(policy: Path) -> dict[str, Any]:
    model = onnx.load(policy, load_external_data=False)
    initializers = {
        initializer.name: numpy_helper.to_array(initializer).astype(np.float64)
        for initializer in model.graph.initializer
    }
    return {
        "positive": initializers["positive_router_coefficient"].reshape(64),
        "conditional": initializers[
            "conditional_path_router_coefficient"
        ].reshape(64),
        "positive_intercept": float(
            initializers["positive_router_intercept"].item()
        ),
        "conditional_intercept": float(
            initializers["conditional_path_router_intercept"].item()
        ),
        "positive_upper": float(
            initializers["t241_positive_router_upper_bound"].item()
        ),
    }


def extreme_context_at_positive_score(
    coefficients: dict[str, Any],
    target_score: float,
    *,
    maximize_conditional: bool,
) -> np.ndarray:
    positive = coefficients["positive"]
    conditional = coefficients["conditional"]
    objective = conditional if maximize_conditional else -conditional
    context = np.sign(objective)
    context[context == 0.0] = 1.0
    current = float(positive @ context)
    goal = target_score - coefficients["positive_intercept"]
    direction = 1.0 if goal > current else -1.0
    choices: list[tuple[float, int, float]] = []
    for index, (p_value, objective_value, value) in enumerate(
        zip(positive, objective, context, strict=True)
    ):
        delta = -2.0 * p_value * value
        progress = direction * delta
        if progress > 1.0e-15:
            loss = 2.0 * abs(objective_value)
            choices.append((loss / progress, index, delta))
    for _, index, delta in sorted(choices):
        needed = direction * (goal - current)
        if needed <= 1.0e-12:
            break
        fraction = min(1.0, needed / (direction * delta))
        context[index] *= 1.0 - 2.0 * fraction
        current = float(positive @ context)
    if abs(current - goal) > 1.0e-9:
        raise VerificationError("could not construct a bounded route context")
    result = context.astype(np.float32).reshape(1, 64)
    if float(np.max(np.abs(result))) > 1.0:
        raise VerificationError("constructed route context is outside [-1, 1]")
    return result


def interior_contexts(
    policy: Path, router: ort.InferenceSession
) -> tuple[dict[str, list[np.ndarray]], dict[str, Any]]:
    coefficients = router_coefficients(policy)
    upper = coefficients["positive_upper"]
    targets = {
        "lower": (-0.2, -0.1),
        "positive": (0.05, 0.12),
        "tail": (upper + 0.00005, upper + 0.0001),
    }
    contexts: dict[str, list[np.ndarray]] = {}
    evidence: dict[str, Any] = {}
    for regime, regime_targets in targets.items():
        for conditional in (0, 1):
            route = f"{regime}-cond{conditional}"
            route_contexts = [
                extreme_context_at_positive_score(
                    coefficients,
                    target,
                    maximize_conditional=bool(conditional),
                )
                for target in regime_targets
            ]
            route_evidence: list[dict[str, Any]] = []
            for context in route_contexts:
                predicates = router.run(list(ROUTER_OUTPUTS), {"calibration_context": context})
                selected = route_from_predicates(value.item() for value in predicates)
                if selected != route:
                    raise VerificationError(
                        f"constructed {route} context selected unexpected {selected}"
                    )
                positive_score = float(
                    context.reshape(64)
                    @ coefficients["positive"].astype(np.float32)
                    + np.float32(coefficients["positive_intercept"])
                )
                conditional_score = float(
                    context.reshape(64)
                    @ coefficients["conditional"].astype(np.float32)
                    + np.float32(coefficients["conditional_intercept"])
                )
                route_evidence.append(
                    {
                        "context_sha256": hashlib.sha256(context.tobytes()).hexdigest(),
                        "positive_score": positive_score,
                        "conditional_score": conditional_score,
                        "predicates": [bool(value.item()) for value in predicates],
                        "selected_route": selected,
                    }
                )
            contexts[route] = route_contexts
            evidence[route] = route_evidence
    return contexts, evidence


def router_predicates(session: ort.InferenceSession, context: np.ndarray) -> list[bool]:
    return [
        bool(value.item())
        for value in session.run(
            list(ROUTER_OUTPUTS), {"calibration_context": context}
        )
    ]


def interpolated_context(low: np.ndarray, high: np.ndarray, t: np.float32) -> np.ndarray:
    return np.asarray(
        low.astype(np.float64) * (1.0 - float(t))
        + high.astype(np.float64) * float(t),
        dtype=np.float32,
    )


def threshold_neighborhood(
    router: ort.InferenceSession,
    low: np.ndarray,
    high: np.ndarray,
    predicate_index: int,
) -> list[np.ndarray]:
    if router_predicates(router, low)[predicate_index]:
        raise VerificationError("threshold low endpoint is already true")
    if not router_predicates(router, high)[predicate_index]:
        raise VerificationError("threshold high endpoint is not true")
    low_bits = int(np.float32(0.0).view(np.uint32))
    high_bits = int(np.float32(1.0).view(np.uint32))
    while high_bits - low_bits > 1:
        middle_bits = (low_bits + high_bits) // 2
        middle = np.asarray(middle_bits, dtype=np.uint32).view(np.float32)
        context = interpolated_context(low, high, middle)
        if router_predicates(router, context)[predicate_index]:
            high_bits = middle_bits
        else:
            low_bits = middle_bits
    below_t = np.asarray(low_bits, dtype=np.uint32).view(np.float32)
    first_true_t = np.asarray(high_bits, dtype=np.uint32).view(np.float32)
    above_t = np.nextafter(first_true_t, np.float32(1.0), dtype=np.float32)
    contexts = [
        interpolated_context(low, high, value)
        for value in (below_t, first_true_t, above_t)
    ]
    states = [router_predicates(router, context)[predicate_index] for context in contexts]
    if states != [False, True, True]:
        raise VerificationError(f"threshold neighborhood is not [false,true,true]: {states}")
    return contexts


def graph_case(
    rng: np.random.Generator,
    context: np.ndarray,
    command: float,
) -> dict[str, np.ndarray]:
    obs = rng.uniform(-0.9, 0.9, (1, 115)).astype(np.float32)
    obs[0, 6] = np.float32(command)
    return {
        "obs": obs,
        "previous_action": rng.uniform(-0.8, 0.8, (1, 14)).astype(np.float32),
        "h_in": rng.uniform(-0.9, 0.9, (1, 64)).astype(np.float32),
        "calibration_context": context.copy(),
    }


def verify_router_and_one_step(
    policy: Path,
    paths: dict[str, Path],
) -> tuple[dict[str, Any], dict[str, list[dict[str, np.ndarray]]]]:
    source_session = create_session(policy)
    instrumented = create_session(paths["instrumented"])
    router = create_session(paths["router"])
    contexts, context_evidence = interior_contexts(policy, router)

    boundary_contexts = {
        "positive_zero": threshold_neighborhood(
            router, contexts["lower-cond0"][1], contexts["positive-cond0"][0], 2
        ),
        "positive_upper": threshold_neighborhood(
            router, contexts["positive-cond0"][1], contexts["tail-cond0"][1], 0
        ),
        "conditional_zero": threshold_neighborhood(
            router, contexts["lower-cond0"][1], contexts["lower-cond1"][1], 1
        ),
    }

    rng = np.random.default_rng(247_031)
    route_banks: dict[str, list[dict[str, np.ndarray]]] = {}
    one_step_cases = 0
    one_step_mismatch: dict[str, Any] | None = None
    router_cases = 0
    for route in ROUTE_NAMES:
        variant = create_session(paths[route])
        bank: list[dict[str, np.ndarray]] = []
        for context_index, context in enumerate(contexts[route]):
            for case_index in range(ONE_STEP_CASES_PER_CONTEXT):
                case = graph_case(
                    rng,
                    context,
                    COMMANDS_M_S[case_index % len(COMMANDS_M_S)],
                )
                expected = source_session.run(list(POLICY_OUTPUTS), case)
                actual = variant.run(list(POLICY_OUTPUTS), case)
                one_step_cases += 1
                if not all(
                    np.array_equal(expected_value, actual_value)
                    for expected_value, actual_value in zip(
                        expected, actual, strict=True
                    )
                ):
                    one_step_mismatch = {
                        "route": route,
                        "context_index": context_index,
                        "case_index": case_index,
                        "maximum_absolute_deltas": [
                            float(np.max(np.abs(expected_value - actual_value)))
                            for expected_value, actual_value in zip(
                                expected, actual, strict=True
                            )
                        ],
                    }
                    break
                if context_index == 0:
                    bank.append(case)

                instrumented_values = instrumented.run(None, case)
                original_predicates = [
                    bool(value.item()) for value in instrumented_values[-len(ROUTER_OUTPUTS) :]
                ]
                extracted_predicates = router_predicates(router, context)
                router_cases += 1
                if original_predicates != extracted_predicates:
                    raise VerificationError("extracted router differs from original predicates")
            if one_step_mismatch is not None:
                break
        if one_step_mismatch is not None:
            break
        route_banks[route] = bank
    if one_step_mismatch is not None:
        raise VerificationError(f"one-step output mismatch: {one_step_mismatch}")

    boundary_evidence: dict[str, Any] = {}
    for label, neighborhood in boundary_contexts.items():
        entries: list[dict[str, Any]] = []
        for context in neighborhood:
            case = graph_case(rng, context, 0.077)
            original = instrumented.run(None, case)
            original_predicates = [
                bool(value.item()) for value in original[-len(ROUTER_OUTPUTS) :]
            ]
            extracted_predicates = router_predicates(router, context)
            if original_predicates != extracted_predicates:
                raise VerificationError("boundary router output mismatch")
            route = route_from_predicates(extracted_predicates)
            actual = create_session(paths[route]).run(list(POLICY_OUTPUTS), case)
            if not all(
                np.array_equal(expected_value, actual_value)
                for expected_value, actual_value in zip(
                    original[:3], actual, strict=True
                )
            ):
                raise VerificationError("boundary selected variant output mismatch")
            entries.append(
                {
                    "context_sha256": hashlib.sha256(context.tobytes()).hexdigest(),
                    "predicates": extracted_predicates,
                    "selected_route": route,
                }
            )
        boundary_evidence[label] = entries

    return (
        {
            "interior_contexts": context_evidence,
            "interior_contexts_per_route": 2,
            "router_cases": router_cases,
            "boundary_neighborhoods": boundary_evidence,
            "one_step_cases": one_step_cases,
            "one_step_cases_per_route": ONE_STEP_CASES_PER_CONTEXT * 2,
            "commands_m_s": list(COMMANDS_M_S),
            "all_router_predicates_exact": True,
            "all_one_step_outputs_byte_exact": True,
        },
        route_banks,
    )


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
        warmup_runs=3,
    )


def mismatch_between(
    expected: WinnerV16TargetOptimizedTransaction,
    actual: WinnerV16TargetOptimizedTransaction,
) -> dict[str, Any] | None:
    for name, expected_value, actual_value in exact_pairs(expected, actual):
        if not np.array_equal(expected_value, actual_value):
            return {
                "field": name,
                "maximum_absolute_delta": float(
                    np.max(np.abs(expected_value - actual_value))
                ),
            }
    return None


def verify_actual_chain(
    asset_paths: dict[str, Path],
    policy: Path,
    variant: Path,
    router_path: Path,
    preregistration: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, np.ndarray]]]:
    baseline = build_host(asset_paths, policy, EXPECTED_POLICY_SHA256, preregistration)
    specialized = build_host(
        asset_paths, variant, sha256(variant), preregistration
    )
    sample = samples(0.074)
    baseline.bind_soft_offsets(sample["soft_offsets_rad"])
    specialized.bind_soft_offsets(sample["soft_offsets_rad"])
    total_ticks = CALIBRATION_TICKS + LOCOMOTION_TICKS
    baseline_actions = np.empty((total_ticks, ACTION_DIM), dtype=np.float32)
    specialized_actions = np.empty((total_ticks, ACTION_DIM), dtype=np.float32)
    input_bank: list[dict[str, np.ndarray]] = []
    mismatch: dict[str, Any] | None = None
    handoff_switches = 0
    selected_route: str | None = None
    context_sha: str | None = None
    router = create_session(router_path)

    for tick in range(total_ticks):
        stage(baseline, tick, sample)
        stage(specialized, tick, sample)
        np.copyto(baseline_actions[tick], baseline.normalized_action_view)
        np.copyto(specialized_actions[tick], specialized.normalized_action_view)
        mismatch = mismatch_between(baseline, specialized)
        if mismatch is not None:
            mismatch.update({"tick": tick, "boundary": "staged"})
            break
        if tick >= CALIBRATION_TICKS:
            input_bank.append(
                {
                    "obs": baseline._locomotion._observation.copy(),
                    "previous_action": baseline._locomotion._previous_action.copy(),
                    "h_in": baseline._locomotion._hidden_in.copy(),
                    "calibration_context": baseline._locomotion._context.copy(),
                }
            )
        baseline.complete_send(write_succeeded=True)
        specialized.complete_send(write_succeeded=True)
        mismatch = mismatch_between(baseline, specialized)
        if mismatch is not None:
            mismatch.update({"tick": tick, "boundary": "committed"})
            break
        if tick + 1 == CALIBRATION_TICKS:
            baseline.confirm_calibration_handoff(True)
            specialized.confirm_calibration_handoff(True)
            handoff_switches += 1
            context = baseline.calibration_context.reshape(1, 64)
            context_sha = hashlib.sha256(context.tobytes()).hexdigest()
            predicates = router.run(
                list(ROUTER_OUTPUTS), {"calibration_context": context}
            )
            selected_route = route_from_predicates(value.item() for value in predicates)

    if mismatch is not None:
        raise VerificationError(f"actual chain mismatch: {mismatch}")
    if selected_route != "lower-cond0" or context_sha != EXPECTED_CONTEXT_SHA256:
        raise VerificationError(
            f"actual handoff selected {selected_route} with context {context_sha}"
        )
    return (
        {
            "calibration_ticks": specialized.confirmed_calibration_ticks,
            "locomotion_ticks": specialized.confirmed_locomotion_ticks,
            "handoff_switches": handoff_switches,
            "selected_route": selected_route,
            "context_float32_bytes_sha256": context_sha,
            "mismatch": mismatch,
            "baseline_action_trace_sha256": hashlib.sha256(
                baseline_actions.tobytes()
            ).hexdigest(),
            "specialized_action_trace_sha256": hashlib.sha256(
                specialized_actions.tobytes()
            ).hexdigest(),
            "all_ticks_byte_exact": bool(
                np.array_equal(baseline_actions, specialized_actions)
            ),
            "maximum_rate_excess_rad_s": float(
                np.max(specialized.target_pipeline.graph_rate_excess_rad_s)
            ),
            "captured_locomotion_inputs": len(input_bank),
        },
        input_bank,
    )


class BoundRunner:
    def __init__(self, path: Path) -> None:
        self.session = create_session(path)
        self.obs = np.zeros((1, 115), dtype=np.float32)
        self.previous_action = np.zeros((1, 14), dtype=np.float32)
        self.h_in = np.zeros((1, 64), dtype=np.float32)
        self.context = np.zeros((1, 64), dtype=np.float32)
        self.action = np.zeros((1, 14), dtype=np.float32)
        self.previous_action_out = np.zeros((1, 14), dtype=np.float32)
        self.h_out = np.zeros((1, 64), dtype=np.float32)
        self.binding = self.session.io_binding()
        self.values: list[ort.OrtValue] = []
        for name, value in (
            ("obs", self.obs),
            ("previous_action", self.previous_action),
            ("h_in", self.h_in),
            ("calibration_context", self.context),
        ):
            ort_value = ort.OrtValue.ortvalue_from_numpy(value)
            self.values.append(ort_value)
            self.binding.bind_ortvalue_input(name, ort_value)
        for name, value in (
            ("continuous_actions", self.action),
            ("previous_action_out", self.previous_action_out),
            ("h_out", self.h_out),
        ):
            ort_value = ort.OrtValue.ortvalue_from_numpy(value)
            self.values.append(ort_value)
            self.binding.bind_ortvalue_output(name, ort_value)

    def load(self, case: dict[str, np.ndarray]) -> None:
        np.copyto(self.obs, case["obs"])
        np.copyto(self.previous_action, case["previous_action"])
        np.copyto(self.h_in, case["h_in"])
        np.copyto(self.context, case["calibration_context"])

    def run_ns(self) -> int:
        started = time.perf_counter_ns()
        self.session.run_with_iobinding(self.binding)
        return time.perf_counter_ns() - started

    def outputs_exact(self, other: BoundRunner) -> bool:
        return (
            np.array_equal(self.action, other.action)
            and np.array_equal(self.previous_action_out, other.previous_action_out)
            and np.array_equal(self.h_out, other.h_out)
        )


def timing_summary(values_ns: np.ndarray) -> dict[str, float | int]:
    values_ms = values_ns.astype(np.float64) / 1_000_000.0
    return {
        "samples": int(values_ms.size),
        "min_ms": float(np.min(values_ms)),
        "mean_ms": float(np.mean(values_ms)),
        "p50_ms": float(np.percentile(values_ms, 50)),
        "p95_ms": float(np.percentile(values_ms, 95)),
        "p99_ms": float(np.percentile(values_ms, 99)),
        "p99_9_ms": float(np.percentile(values_ms, 99.9)),
        "max_ms": float(np.max(values_ms)),
    }


def benchmark_route(
    policy: Path,
    variant: Path,
    bank: list[dict[str, np.ndarray]],
) -> dict[str, Any]:
    source = BoundRunner(policy)
    specialized = BoundRunner(variant)
    for index in range(TIMING_WARMUP_SAMPLES):
        case = bank[index % len(bank)]
        source.load(case)
        specialized.load(case)
        source.run_ns()
        specialized.run_ns()
        if not source.outputs_exact(specialized):
            raise VerificationError("timing warm-up output mismatch")

    source_ns = np.empty(TIMING_SAMPLES, dtype=np.int64)
    specialized_ns = np.empty(TIMING_SAMPLES, dtype=np.int64)
    outputs_exact = True
    gc_enabled = gc.isenabled()
    gc.disable()
    try:
        for index in range(TIMING_SAMPLES):
            case = bank[index % len(bank)]
            source.load(case)
            specialized.load(case)
            if index % 2 == 0:
                source_ns[index] = source.run_ns()
                specialized_ns[index] = specialized.run_ns()
            else:
                specialized_ns[index] = specialized.run_ns()
                source_ns[index] = source.run_ns()
            outputs_exact = outputs_exact and source.outputs_exact(specialized)
    finally:
        if gc_enabled:
            gc.enable()
    if not outputs_exact:
        raise VerificationError("timing benchmark output mismatch")
    source_summary = timing_summary(source_ns)
    specialized_summary = timing_summary(specialized_ns)
    p50_ratio = specialized_summary["p50_ms"] / source_summary["p50_ms"]
    p99_ratio = specialized_summary["p99_ms"] / source_summary["p99_ms"]
    return {
        "warmup_samples": TIMING_WARMUP_SAMPLES,
        "measured_samples": TIMING_SAMPLES,
        "alternated_order": True,
        "outputs_byte_exact": outputs_exact,
        "source": source_summary,
        "specialized": specialized_summary,
        "specialized_to_source_p50_ratio": p50_ratio,
        "specialized_to_source_p99_ratio": p99_ratio,
        "required_maximum_ratio": TIMING_RATIO_LIMIT,
        "p50_materiality_pass": p50_ratio <= TIMING_RATIO_LIMIT,
        "p99_materiality_pass": p99_ratio <= TIMING_RATIO_LIMIT,
    }


def run_timing_contract(
    policy: Path,
    variant_paths: dict[str, Path],
    route_banks: dict[str, list[dict[str, np.ndarray]]],
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for route in ROUTE_NAMES:
        results[route] = benchmark_route(
            policy,
            variant_paths[route],
            route_banks[route],
        )
    return {
        "routes": results,
        "all_outputs_byte_exact": all(
            result["outputs_byte_exact"] for result in results.values()
        ),
        "all_routes_p50_materiality_pass": all(
            result["p50_materiality_pass"] for result in results.values()
        ),
        "all_routes_p99_materiality_pass": all(
            result["p99_materiality_pass"] for result in results.values()
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibrator", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--p30-fit", type=Path, required=True)
    parser.add_argument("--reference-table", type=Path, required=True)
    parser.add_argument("--derived-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if sha256(PREREGISTRATION) != PREREGISTRATION_SHA256:
        raise VerificationError("preregistration SHA-256 mismatch")
    preregistration = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    asset_paths = {
        "calibrator": args.calibrator.resolve(),
        "policy": args.policy.resolve(),
        "p30_fit": args.p30_fit.resolve(),
        "reference_table": args.reference_table.resolve(),
    }
    assets = preregistration["unchanged_assets"]
    expected_hashes = {
        "calibrator": assets["calibrator_sha256"],
        "policy": assets["deployment_policy_sha256"],
        "p30_fit": assets["fixed_p30_runtime_observer_fit_sha256"],
        "reference_table": assets["projected_reference_table_sha256"],
    }
    asset_hashes_exact = all(
        sha256(asset_paths[name]) == expected for name, expected in expected_hashes.items()
    )
    if not asset_hashes_exact:
        raise VerificationError("source asset hash mismatch")

    derived_root = args.derived_root.resolve()
    if derived_root.is_relative_to(ROOT):
        raise VerificationError("derived ONNX root must remain outside the repository")
    derivation, variant_paths = verify_derivation(asset_paths["policy"], derived_root)
    router_semantics, route_banks = verify_router_and_one_step(
        asset_paths["policy"], variant_paths
    )
    actual_chain, actual_bank = verify_actual_chain(
        asset_paths,
        asset_paths["policy"],
        variant_paths["lower-cond0"],
        variant_paths["router"],
        preregistration,
    )
    route_banks["lower-cond0"] = actual_bank

    semantic_pass = (
        derivation["derive_twice_byte_exact"]
        and derivation["all_onnx_checker_pass"]
        and derivation["all_policy_abis_exact"]
        and derivation["all_retained_initializers_exact"]
        and router_semantics["all_router_predicates_exact"]
        and router_semantics["all_one_step_outputs_byte_exact"]
        and actual_chain["all_ticks_byte_exact"]
        and actual_chain["handoff_switches"] == 1
        and actual_chain["captured_locomotion_inputs"] == LOCOMOTION_TICKS
        and actual_chain["maximum_rate_excess_rad_s"] == 0.0
    )
    if not semantic_pass:
        raise VerificationError("semantic contract failed before timing")

    timing = run_timing_contract(
        asset_paths["policy"], variant_paths, route_banks
    )
    checks = {
        "asset_hashes_exact": asset_hashes_exact,
        "derive_twice_byte_exact": derivation["derive_twice_byte_exact"],
        "all_onnx_checker_pass": derivation["all_onnx_checker_pass"],
        "all_policy_abis_exact": derivation["all_policy_abis_exact"],
        "all_retained_initializers_exact": derivation[
            "all_retained_initializers_exact"
        ],
        "all_six_routes_have_two_interior_contexts": (
            router_semantics["interior_contexts_per_route"] == 2
            and len(router_semantics["interior_contexts"]) == 6
        ),
        "router_predicates_exact_interior_and_boundaries": router_semantics[
            "all_router_predicates_exact"
        ],
        "all_one_step_outputs_byte_exact": router_semantics[
            "all_one_step_outputs_byte_exact"
        ],
        "actual_2298_tick_chain_byte_exact": actual_chain["all_ticks_byte_exact"],
        "actual_exact_handoff_and_route": (
            actual_chain["handoff_switches"] == 1
            and actual_chain["selected_route"] == "lower-cond0"
            and actual_chain["context_float32_bytes_sha256"]
            == EXPECTED_CONTEXT_SHA256
        ),
        "zero_measured_rate_excess": actual_chain[
            "maximum_rate_excess_rad_s"
        ]
        == 0.0,
        "timing_outputs_byte_exact": timing["all_outputs_byte_exact"],
        "all_routes_p50_improve_at_least_12_percent": timing[
            "all_routes_p50_materiality_pass"
        ],
        "all_routes_p99_improve_at_least_12_percent": timing[
            "all_routes_p99_materiality_pass"
        ],
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    passed = not failed_checks
    result: dict[str, Any] = {
        "schema_version": "open_duck_x5.t247_context_route_specialization_result.v1",
        "status": (
            "PASS_T247_CONTEXT_ROUTE_SPECIALIZATION_CPU_CONTRACT"
            if passed
            else "FAIL_T247_CONTEXT_ROUTE_SPECIALIZATION_CPU_CONTRACT"
        ),
        "candidate_id": "T247_HOME_NEGATIVE_HALF_ADAPTER_FINAL",
        "deployment_policy_sha256": EXPECTED_POLICY_SHA256,
        "preregistration": receipt(PREREGISTRATION),
        "asset_receipts": {
            name: receipt(path) for name, path in asset_paths.items()
        },
        "derivation": derivation,
        "router_and_one_step_semantics": router_semantics,
        "actual_chain_semantics": actual_chain,
        "local_timing_contract": timing,
        "checks": checks,
        "checks_passed": sum(bool(value) for value in checks.values()),
        "checks_total": len(checks),
        "failed_checks": failed_checks,
        "decision": (
            "EARN_SEPARATE_T247_X5_NO_MOTION_CONTEXT_SPECIALIZATION_SCREEN_PREREGISTRATION"
            if passed
            else "CLOSE_CONTEXT_ROUTE_SPECIALIZATION_WITHOUT_X5_EXECUTION"
        ),
        "authority": {
            "local_cpu_contract": True,
            "x5_execution": False,
            "robot_device_access": False,
            "servo_reads_or_writes": False,
            "torque": False,
            "motion": False,
            "policy_deployed": False,
            "policy_training_earned": False,
            "production_integration_earned": False,
            "gate5": False,
        },
    }
    result["result_sha256"] = canonical_sha256(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
