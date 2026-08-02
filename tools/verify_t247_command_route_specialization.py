#!/usr/bin/env python3
"""Verify the preregistered exact T247 command-route CPU contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import onnx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from tools import run_t247_x5_context_route_reserved_screen as host_tools  # noqa: E402
from tools.derive_t247_command_route_variants import (  # noqa: E402
    COMMAND_TAGS,
    COMMANDS,
    POLICY_INPUTS,
    POLICY_OUTPUTS,
    ROUTE_NAMES,
    sha256,
)
from tools.verify_t247_context_route_specialization import (  # noqa: E402
    benchmark_route,
    create_session,
    graph_case,
    interior_contexts,
)

PREREGISTRATION = (
    ROOT
    / "artifacts"
    / "gates"
    / "phase_5_policy"
    / "t247_deployment_command_route_specialization_preregistration_20260801.json"
)
PREREGISTRATION_SHA256 = "d8e66e005c5185c6656dcc588856ad6b85cfee91993159b770fb67d53b27a0d6"
ONE_STEP_CASES_PER_CONTEXT_COMMAND = 128
ROUTE_SWITCH_TICKS_PER_CONTEXT = 660
ROUTE_SWITCH_COMMANDS = (0.0, 0.074, 0.077, 0.080, 0.075, 0.079, 0.080, 0.0, 0.077, 0.074, 0.076)
ACTUAL_CHAIN_TICKS = 2298


class VerificationError(RuntimeError):
    """Raised when a sealed CPU-contract requirement fails."""


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def receipt(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def _initializer_bytes(model: onnx.ModelProto) -> dict[str, bytes]:
    return {
        initializer.name: initializer.SerializeToString(deterministic=True)
        for initializer in model.graph.initializer
    }


def verify_derivations(
    context_root: Path,
    derive_a: Path,
    derive_b: Path,
    preregistration: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Path]]:
    context_manifest_path = context_root / "manifest.json"
    if (
        sha256(context_manifest_path)
        != preregistration["source_assets"]["context_variant_manifest_sha256"]
    ):
        raise VerificationError("context-route manifest hash mismatch")
    manifest_a_path = derive_a / "manifest.json"
    manifest_b_path = derive_b / "manifest.json"
    if manifest_a_path.read_bytes() != manifest_b_path.read_bytes():
        raise VerificationError("two command derivations differ")
    manifest = json.loads(manifest_a_path.read_text(encoding="utf-8"))
    if manifest["generated_models"] != 24:
        raise VerificationError("command manifest does not contain 24 models")

    context_manifest = json.loads(context_manifest_path.read_text(encoding="utf-8"))
    context_entries = {
        entry["name"]: entry
        for entry in context_manifest["generated"]
        if entry["name"] in ROUTE_NAMES
    }
    paths: dict[str, Path] = {}
    abi_exact = True
    retained_initializers_exact = True
    checker_passed = True
    pair_hashes_exact = True
    for route in ROUTE_NAMES:
        source_path = context_root / context_entries[route]["file"]
        source = onnx.load(source_path, load_external_data=False)
        source_initializers = _initializer_bytes(source)
        for command in COMMANDS:
            tag = COMMAND_TAGS[command]
            name = f"{route}-{tag}"
            entry = manifest["generated"][name]
            path_a = derive_a / entry["file"]
            path_b = derive_b / entry["file"]
            if sha256(path_a) != entry["sha256"] or sha256(path_b) != entry["sha256"]:
                pair_hashes_exact = False
            candidate = onnx.load(path_a, load_external_data=False)
            try:
                onnx.checker.check_model(candidate, full_check=True)
            except Exception:
                checker_passed = False
                raise
            abi_exact = abi_exact and (
                tuple(value.name for value in candidate.graph.input) == POLICY_INPUTS
                and tuple(value.name for value in candidate.graph.output) == POLICY_OUTPUTS
            )
            for initializer in candidate.graph.initializer:
                expected = source_initializers.get(initializer.name)
                if expected is not None and expected != initializer.SerializeToString(
                    deterministic=True
                ):
                    retained_initializers_exact = False
            paths[name] = path_a
    return (
        {
            "context_manifest": receipt(context_manifest_path),
            "derive_a_manifest": receipt(manifest_a_path),
            "derive_b_manifest": receipt(manifest_b_path),
            "derive_twice_byte_exact": manifest_a_path.read_bytes() == manifest_b_path.read_bytes()
            and pair_hashes_exact,
            "generated_models": len(paths),
            "all_onnx_checker_pass": checker_passed,
            "all_policy_abis_exact": abi_exact,
            "all_retained_initializers_exact": retained_initializers_exact,
        },
        paths,
    )


def verify_one_step_and_switching(
    policy: Path,
    router: Path,
    context_root: Path,
    candidate_paths: dict[str, Path],
) -> tuple[dict[str, Any], dict[str, dict[str, list[dict[str, np.ndarray]]]]]:
    router_session = create_session(router)
    contexts, context_evidence = interior_contexts(policy, router_session)
    rng = np.random.default_rng(247_080)
    sessions: dict[str, Any] = {}
    banks: dict[str, dict[str, list[dict[str, np.ndarray]]]] = {}
    one_step_cases = 0
    for route in ROUTE_NAMES:
        source = create_session(context_root / f"policy.{route}.onnx")
        sessions[route] = source
        banks[route] = {}
        for command in COMMANDS:
            tag = COMMAND_TAGS[command]
            candidate = create_session(candidate_paths[f"{route}-{tag}"])
            sessions[f"{route}-{tag}"] = candidate
            bank: list[dict[str, np.ndarray]] = []
            for context_index, context in enumerate(contexts[route]):
                for _ in range(ONE_STEP_CASES_PER_CONTEXT_COMMAND):
                    case = graph_case(rng, context, command)
                    expected = source.run(list(POLICY_OUTPUTS), case)
                    actual = candidate.run(list(POLICY_OUTPUTS), case)
                    if not all(
                        np.array_equal(left, right)
                        for left, right in zip(expected, actual, strict=True)
                    ):
                        raise VerificationError(f"one-step mismatch for {route} command {command}")
                    if context_index == 0:
                        bank.append(case)
                    one_step_cases += 1
            banks[route][tag] = bank

    switch_ticks = 0
    switches = 0
    fallback_ticks = 0
    for route in ROUTE_NAMES:
        source = sessions[route]
        for context in contexts[route]:
            baseline_previous = np.zeros((1, 14), dtype=np.float32)
            baseline_hidden = np.zeros((1, 64), dtype=np.float32)
            routed_previous = baseline_previous.copy()
            routed_hidden = baseline_hidden.copy()
            last_session: Any | None = None
            for tick in range(ROUTE_SWITCH_TICKS_PER_CONTEXT):
                command = ROUTE_SWITCH_COMMANDS[tick % len(ROUTE_SWITCH_COMMANDS)]
                obs = rng.uniform(-0.9, 0.9, (1, 115)).astype(np.float32)
                obs[0, 6] = np.float32(command)
                obs[0, 7:13] = 0.0
                baseline_feed = {
                    "obs": obs,
                    "previous_action": baseline_previous,
                    "h_in": baseline_hidden,
                    "calibration_context": context,
                }
                routed_feed = {
                    "obs": obs,
                    "previous_action": routed_previous,
                    "h_in": routed_hidden,
                    "calibration_context": context,
                }
                expected = source.run(list(POLICY_OUTPUTS), baseline_feed)
                if command in COMMAND_TAGS:
                    selected = sessions[f"{route}-{COMMAND_TAGS[command]}"]
                else:
                    selected = source
                    fallback_ticks += 1
                actual = selected.run(list(POLICY_OUTPUTS), routed_feed)
                if last_session is not None and selected is not last_session:
                    switches += 1
                last_session = selected
                if not all(
                    np.array_equal(left, right)
                    for left, right in zip(expected, actual, strict=True)
                ):
                    raise VerificationError(f"route-switch mismatch for {route} tick {tick}")
                baseline_previous = expected[1].copy()
                baseline_hidden = expected[2].copy()
                routed_previous = actual[1].copy()
                routed_hidden = actual[2].copy()
                switch_ticks += 1
    return (
        {
            "interior_contexts": context_evidence,
            "interior_contexts_per_route": 2,
            "one_step_cases": one_step_cases,
            "one_step_outputs_byte_exact": True,
            "route_switch_ticks": switch_ticks,
            "route_switches": switches,
            "fallback_ticks": fallback_ticks,
            "route_switch_outputs_byte_exact": True,
        },
        banks,
    )


def runtime_preregistration(preregistration: dict[str, Any]) -> dict[str, Any]:
    assets = preregistration["source_assets"]
    return {
        "unchanged_assets": {
            "calibrator_sha256": assets["calibrator_sha256"],
            "fixed_p30_runtime_observer_fit_sha256": assets["p30_fit_sha256"],
            "projected_reference_table_sha256": assets["reference_table_sha256"],
        }
    }


def verify_actual_chains(
    paths: dict[str, Path],
    context_root: Path,
    candidate_paths: dict[str, Path],
    preregistration: dict[str, Any],
) -> dict[str, Any]:
    runtime = runtime_preregistration(preregistration)
    source_path = context_root / "policy.lower-cond0.onnx"
    source_sha256 = sha256(source_path)
    results: dict[str, Any] = {}
    for command in COMMANDS:
        tag = COMMAND_TAGS[command]
        candidate_path = candidate_paths[f"lower-cond0-{tag}"]
        source = host_tools.build_host(paths, source_path, source_sha256, runtime)
        candidate = host_tools.build_host(
            paths,
            candidate_path,
            sha256(candidate_path),
            runtime,
        )
        sample = host_tools.samples(command)
        offsets = sample["soft_offsets_rad"]
        source.bind_soft_offsets(offsets)
        candidate.bind_soft_offsets(offsets)
        source_actions = np.empty((ACTUAL_CHAIN_TICKS, 14), dtype=np.float32)
        candidate_actions = np.empty_like(source_actions)
        maximum_rate_excess = 0.0
        for tick in range(ACTUAL_CHAIN_TICKS):
            host_tools.stage(source, tick, sample)
            host_tools.stage(candidate, tick, sample)
            mismatch = host_tools.mismatch(source, candidate, committed=False)
            if mismatch is not None:
                raise VerificationError(f"staged chain mismatch {tag}: {mismatch}")
            np.copyto(source_actions[tick], source.normalized_action_view)
            np.copyto(candidate_actions[tick], candidate.normalized_action_view)
            maximum_rate_excess = max(
                maximum_rate_excess,
                float(np.max(candidate.target_pipeline.graph_rate_excess_rad_s)),
            )
            source.complete_send(write_succeeded=True)
            candidate.complete_send(write_succeeded=True)
            mismatch = host_tools.mismatch(source, candidate, committed=True)
            if mismatch is not None:
                raise VerificationError(f"committed chain mismatch {tag}: {mismatch}")
            if tick + 1 == 250:
                source.confirm_calibration_handoff(True)
                candidate.confirm_calibration_handoff(True)
        if not np.array_equal(source_actions, candidate_actions):
            raise VerificationError(f"action-trace mismatch for {tag}")
        results[tag] = {
            "command_x_m_s": command,
            "ticks": ACTUAL_CHAIN_TICKS,
            "handoff_switches": 1,
            "all_state_and_actions_byte_exact": True,
            "action_trace_sha256": hashlib.sha256(candidate_actions.tobytes()).hexdigest(),
            "maximum_rate_excess_rad_s": maximum_rate_excess,
        }
    return results


def verify_timing(
    context_root: Path,
    candidate_paths: dict[str, Path],
    banks: dict[str, dict[str, list[dict[str, np.ndarray]]]],
) -> dict[str, Any]:
    routes: dict[str, Any] = {}
    for route in ROUTE_NAMES:
        routes[route] = {}
        source = context_root / f"policy.{route}.onnx"
        for command in COMMANDS:
            tag = COMMAND_TAGS[command]
            routes[route][tag] = benchmark_route(
                source,
                candidate_paths[f"{route}-{tag}"],
                banks[route][tag],
            )
    values = [value for commands in routes.values() for value in commands.values()]
    return {
        "routes": routes,
        "variants": len(values),
        "all_outputs_byte_exact": all(value["outputs_byte_exact"] for value in values),
        "worst_p50_ratio": max(value["specialized_to_source_p50_ratio"] for value in values),
        "worst_p99_ratio": max(value["specialized_to_source_p99_ratio"] for value in values),
        "required_maximum_ratio": 0.88,
        "all_p50_materiality_pass": all(
            value["specialized_to_source_p50_ratio"] <= 0.88 for value in values
        ),
        "all_p99_materiality_pass": all(
            value["specialized_to_source_p99_ratio"] <= 0.88 for value in values
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--calibrator", type=Path, required=True)
    parser.add_argument("--p30-fit", type=Path, required=True)
    parser.add_argument("--reference-table", type=Path, required=True)
    parser.add_argument("--router", type=Path, required=True)
    parser.add_argument("--context-root", type=Path, required=True)
    parser.add_argument("--derive-a", type=Path, required=True)
    parser.add_argument("--derive-b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if sha256(PREREGISTRATION) != PREREGISTRATION_SHA256:
        raise VerificationError("command-route preregistration changed")
    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        raise VerificationError("raw CPU-contract output must remain outside repository")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite CPU-contract result: {output}")
    preregistration = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    assets = preregistration["source_assets"]
    asset_paths = {
        "policy": args.policy.resolve(),
        "calibrator": args.calibrator.resolve(),
        "p30_fit": args.p30_fit.resolve(),
        "reference_table": args.reference_table.resolve(),
        "router": args.router.resolve(),
    }
    expected_hashes = {
        "policy": assets["deployment_policy_sha256"],
        "calibrator": assets["calibrator_sha256"],
        "p30_fit": assets["p30_fit_sha256"],
        "reference_table": assets["reference_table_sha256"],
        "router": assets["context_router_sha256"],
    }
    asset_receipts = {name: receipt(path) for name, path in asset_paths.items()}
    asset_hashes_exact = all(
        asset_receipts[name]["sha256"] == expected for name, expected in expected_hashes.items()
    )
    if not asset_hashes_exact:
        raise VerificationError("source asset hash mismatch")

    derivation, candidate_paths = verify_derivations(
        args.context_root.resolve(),
        args.derive_a.resolve(),
        args.derive_b.resolve(),
        preregistration,
    )
    semantics, banks = verify_one_step_and_switching(
        asset_paths["policy"],
        asset_paths["router"],
        args.context_root.resolve(),
        candidate_paths,
    )
    host_paths = {
        "calibrator": asset_paths["calibrator"],
        "p30_fit": asset_paths["p30_fit"],
        "reference_table": asset_paths["reference_table"],
    }
    actual_chains = verify_actual_chains(
        host_paths,
        args.context_root.resolve(),
        candidate_paths,
        preregistration,
    )
    timing = verify_timing(args.context_root.resolve(), candidate_paths, banks)
    checks = {
        "asset_hashes_exact": asset_hashes_exact,
        "derive_twice_byte_exact": derivation["derive_twice_byte_exact"],
        "all_24_onnx_checker_pass": derivation["all_onnx_checker_pass"],
        "all_24_policy_abis_exact": derivation["all_policy_abis_exact"],
        "all_retained_initializers_exact": derivation["all_retained_initializers_exact"],
        "exact_one_step_case_count": semantics["one_step_cases"] == 6144,
        "one_step_outputs_byte_exact": semantics["one_step_outputs_byte_exact"],
        "exact_route_switch_tick_count": semantics["route_switch_ticks"] == 7920,
        "fallback_exercised": semantics["fallback_ticks"] > 0,
        "route_switch_outputs_byte_exact": semantics["route_switch_outputs_byte_exact"],
        "four_actual_chains_exact": len(actual_chains) == 4
        and all(value["all_state_and_actions_byte_exact"] for value in actual_chains.values()),
        "zero_rate_excess": all(
            value["maximum_rate_excess_rad_s"] == 0.0 for value in actual_chains.values()
        ),
        "all_timing_outputs_byte_exact": timing["all_outputs_byte_exact"],
        "all_p50_materiality_pass": timing["all_p50_materiality_pass"],
        "all_p99_materiality_pass": timing["all_p99_materiality_pass"],
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    result: dict[str, Any] = {
        "schema_version": "open_duck_x5.t247_command_route_specialization_result.v1",
        "status": (
            "PASS_T247_COMMAND_ROUTE_SPECIALIZATION_CPU_CONTRACT"
            if not failed
            else "FAIL_T247_COMMAND_ROUTE_SPECIALIZATION_CPU_CONTRACT"
        ),
        "date": preregistration["date"],
        "preregistration": receipt(PREREGISTRATION),
        "asset_receipts": asset_receipts,
        "derivation": derivation,
        "semantics": semantics,
        "actual_chains": actual_chains,
        "timing": timing,
        "checks": checks,
        "checks_passed": sum(bool(value) for value in checks.values()),
        "checks_total": len(checks),
        "failed_checks": failed,
        "decision": (
            "EARN_ONE_SEPARATELY_PREREGISTERED_NO_DEVICE_X5_COMMAND_ROUTE_RESERVED_SCREEN"
            if not failed
            else "CLOSE_COMMAND_ROUTE_SPECIALIZATION_WITHOUT_X5_RUN"
        ),
        "authority": {
            "local_cpu_only": True,
            "x5_execution": False,
            "robot_devices": False,
            "serial_bus": False,
            "servo_reads_or_writes": False,
            "sensors": False,
            "torque": False,
            "motion": False,
            "policy_training": False,
            "production_integration": False,
            "gate5": False,
        },
    }
    result["result_sha256"] = canonical_sha256(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(result, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
