#!/usr/bin/env python3
"""Derive exact post-calibration route variants of the frozen T247 policy.

The source policy remains the authority.  The generated graphs keep the public
115/14/64 ABI and only remove branches made unreachable by the immutable
64-D calibration context.  Generated ONNX files must live outside the
repository and are never deployment assets until the separate CPU contract
and X5 screen pass.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

import onnx
from onnx import TensorProto, checker, helper

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_POLICY_SHA256 = (
    "dadfb446ea7c720f274a15bc65e9171c2e74d715ccfaf58adbb408b6c1365a54"
)
ROUTE_REGIMES = ("lower", "positive", "tail")
ROUTE_NAMES = tuple(
    f"{regime}-cond{conditional}"
    for regime in ROUTE_REGIMES
    for conditional in (0, 1)
)
ROUTER_OUTPUTS = (
    "t243_home_negative_tail_condition",
    "t149_negative_condition",
    "t162_positive_condition",
    "conditional_path_negative_condition",
    "t156_positive_condition",
)
POLICY_INPUTS = (
    "obs",
    "previous_action",
    "h_in",
    "calibration_context",
)
POLICY_OUTPUTS = (
    "continuous_actions",
    "previous_action_out",
    "h_out",
)


class DerivationError(RuntimeError):
    """Raised when the frozen graph does not satisfy the derivation contract."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def model_bytes(model: onnx.ModelProto) -> bytes:
    return model.SerializeToString(deterministic=True)


def _resolve_alias(name: str, aliases: dict[str, str]) -> str:
    seen: set[str] = set()
    while name in aliases:
        if name in seen:
            raise DerivationError(f"tensor alias cycle at {name}")
        seen.add(name)
        name = aliases[name]
    return name


def _all_tensor_names(model: onnx.ModelProto) -> set[str]:
    names = {value.name for value in model.graph.input}
    names.update(value.name for value in model.graph.output)
    names.update(initializer.name for initializer in model.graph.initializer)
    for node in model.graph.node:
        names.update(name for name in node.input if name)
        names.update(name for name in node.output if name)
    return names


def _apply_aliases(model: onnx.ModelProto, aliases: dict[str, str]) -> None:
    names = _all_tensor_names(model)
    for old, new in aliases.items():
        if old not in names or new not in names:
            raise DerivationError(f"unknown tensor alias {old} -> {new}")
    for node in model.graph.node:
        for index, name in enumerate(node.input):
            if name:
                node.input[index] = _resolve_alias(name, aliases)


def _backward_dead_code_elimination(model: onnx.ModelProto) -> None:
    needed = {value.name for value in model.graph.output}
    retained_reversed: list[onnx.NodeProto] = []
    for node in reversed(model.graph.node):
        if any(output in needed for output in node.output):
            retained_reversed.append(node)
            needed.update(name for name in node.input if name)
    retained = list(reversed(retained_reversed))
    del model.graph.node[:]
    model.graph.node.extend(retained)

    referenced = {name for node in retained for name in node.input if name}
    retained_initializers = [
        initializer
        for initializer in model.graph.initializer
        if initializer.name in referenced
    ]
    del model.graph.initializer[:]
    model.graph.initializer.extend(retained_initializers)

    live = {value.name for value in model.graph.input}
    live.update(value.name for value in model.graph.output)
    live.update(initializer.name for initializer in retained_initializers)
    for node in retained:
        live.update(name for name in node.input if name)
        live.update(name for name in node.output if name)
    retained_value_info = [
        value for value in model.graph.value_info if value.name in live
    ]
    del model.graph.value_info[:]
    model.graph.value_info.extend(retained_value_info)


def parse_route(route: str) -> tuple[str, bool]:
    if route not in ROUTE_NAMES:
        raise DerivationError(f"unknown route {route!r}; expected one of {ROUTE_NAMES}")
    regime, conditional = route.rsplit("-cond", 1)
    return regime, conditional == "1"


def route_aliases(route: str) -> dict[str, str]:
    regime, conditional = parse_route(route)
    aliases: dict[str, str] = {}

    if regime == "tail":
        aliases["t243_home_negative_low_command_condition"] = (
            "t243_exact_low_command_condition"
        )
    else:
        aliases["t222_capped_command_x"] = "t243_base_capped_command_x"

    if conditional:
        aliases["t149_selected_command_x"] = "t149_capped_command_x"
    else:
        # With the context condition false the full slice/rebuild is an exact
        # identity, so bypass it rather than retaining an eager no-op branch.
        aliases["t149_policy_obs"] = "t222_global_policy_obs"

    if regime == "positive":
        aliases["t162_rewrite_condition"] = "t162_positive_moving_command"
        aliases["conditional_adapter_location"] = "t156_positive_adapter_location"
        aliases["t159_selected_action_bias"] = "t159_mechanics_action_bias"
    else:
        # The non-positive path gathers the existing command and scatters the
        # same value back into the same slot, making the full rewrite identity.
        aliases["t162_policy_obs"] = "t17_source_obs"
        aliases["t159_selected_action_bias"] = "t159_zero_action_bias"
        aliases["t156_nominal_negative_adapter_location"] = (
            "negative_condition_adapter_location"
            if conditional
            else "nominal_dynamic_conditional_adapter"
        )
        aliases["t247_home_negative_selected_adapter_location"] = (
            "t247_home_negative_half_adapter_location"
            if regime == "tail"
            else "t234_command_selected_adapter_location"
        )
    return aliases


def specialize_model(source: onnx.ModelProto, route: str) -> onnx.ModelProto:
    model = copy.deepcopy(source)
    actual_inputs = tuple(value.name for value in model.graph.input)
    actual_outputs = tuple(value.name for value in model.graph.output)
    if actual_inputs != POLICY_INPUTS or actual_outputs != POLICY_OUTPUTS:
        raise DerivationError(
            f"source ABI mismatch: inputs={actual_inputs}, outputs={actual_outputs}"
        )
    _apply_aliases(model, route_aliases(route))
    _backward_dead_code_elimination(model)
    checker.check_model(model, full_check=True)
    return model


def instrumented_model(source: onnx.ModelProto) -> onnx.ModelProto:
    model = copy.deepcopy(source)
    existing = {value.name for value in model.graph.output}
    for name in ROUTER_OUTPUTS:
        if name in existing:
            raise DerivationError(f"instrumentation output already exists: {name}")
        model.graph.output.append(
            helper.make_tensor_value_info(name, TensorProto.BOOL, [1, 1])
        )
    checker.check_model(model, full_check=True)
    return model


def router_model(source: onnx.ModelProto) -> onnx.ModelProto:
    model = copy.deepcopy(source)
    inputs = [value for value in model.graph.input if value.name == "calibration_context"]
    if len(inputs) != 1:
        raise DerivationError("source must have exactly one calibration_context input")
    del model.graph.input[:]
    model.graph.input.extend(inputs)
    del model.graph.output[:]
    model.graph.output.extend(
        helper.make_tensor_value_info(name, TensorProto.BOOL, [1, 1])
        for name in ROUTER_OUTPUTS
    )
    _backward_dead_code_elimination(model)
    checker.check_model(model, full_check=True)
    return model


def route_from_predicates(values: Iterable[object]) -> str:
    predicates = tuple(bool(value) for value in values)
    if len(predicates) != len(ROUTER_OUTPUTS):
        raise DerivationError(
            f"expected {len(ROUTER_OUTPUTS)} route predicates, got {len(predicates)}"
        )
    tail, t149_conditional, t162_positive, t143_conditional, t156_positive = (
        predicates
    )
    if t149_conditional != t143_conditional:
        raise DerivationError("original conditional-path predicates disagree")
    if t162_positive != t156_positive:
        raise DerivationError("original bounded-positive predicates disagree")
    if tail and t162_positive:
        raise DerivationError("tail and bounded-positive predicates overlap")
    regime = "tail" if tail else "positive" if t162_positive else "lower"
    return f"{regime}-cond{int(t149_conditional)}"


def _summary(name: str, path: Path, model: onnx.ModelProto) -> dict[str, object]:
    counts = Counter(node.op_type for node in model.graph.node)
    return {
        "name": name,
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "nodes": len(model.graph.node),
        "initializers": len(model.graph.initializer),
        "operation_counts": dict(sorted(counts.items())),
    }


def _write_model(path: Path, model: onnx.ModelProto) -> None:
    path.write_bytes(model_bytes(model))


def derive(policy: Path, output_dir: Path) -> dict[str, object]:
    policy = policy.resolve()
    output_dir = output_dir.resolve()
    if output_dir.is_relative_to(ROOT):
        raise DerivationError("generated policy binaries must remain outside the repository")
    if sha256(policy) != EXPECTED_POLICY_SHA256:
        raise DerivationError("source policy SHA-256 does not match frozen T247")
    output_dir.mkdir(parents=True, exist_ok=True)

    source = onnx.load(policy, load_external_data=False)
    checker.check_model(source, full_check=True)
    generated: list[dict[str, object]] = []

    instrumented = instrumented_model(source)
    instrumented_path = output_dir / "policy.instrumented-routes.onnx"
    _write_model(instrumented_path, instrumented)
    generated.append(_summary("instrumented", instrumented_path, instrumented))

    router = router_model(source)
    router_path = output_dir / "policy.context-router.onnx"
    _write_model(router_path, router)
    generated.append(_summary("router", router_path, router))

    for route in ROUTE_NAMES:
        variant = specialize_model(source, route)
        variant_path = output_dir / f"policy.{route}.onnx"
        _write_model(variant_path, variant)
        generated.append(_summary(route, variant_path, variant))

    manifest: dict[str, object] = {
        "schema_version": "open_duck_x5.t247_context_route_variant_manifest.v1",
        "source_policy": {
            "bytes": policy.stat().st_size,
            "sha256": sha256(policy),
            "nodes": len(source.graph.node),
            "initializers": len(source.graph.initializer),
        },
        "routes": list(ROUTE_NAMES),
        "generated": generated,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = derive(args.policy, args.output_dir)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
