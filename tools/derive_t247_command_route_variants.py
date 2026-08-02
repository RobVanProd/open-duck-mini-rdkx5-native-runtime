#!/usr/bin/env python3
"""Derive exact command subroutes from frozen T247 context-route models.

The source context variants remain authoritative. Generated ONNX models live
outside the repository and preserve the four-input/three-output policy ABI.
Each specialized model is valid only for its exact command value; a deployment
host must retain the selected context-route source as the fallback for every
other valid command and transfer recurrent state exactly when routes change.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import onnx
from onnx import checker, helper, numpy_helper

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.derive_t247_context_route_variants import (  # noqa: E402
    EXPECTED_POLICY_SHA256,
    POLICY_INPUTS,
    POLICY_OUTPUTS,
    ROUTE_NAMES,
    DerivationError,
    _apply_aliases,
    _backward_dead_code_elimination,
    model_bytes,
    parse_route,
    sha256,
)

COMMANDS = (0.0, 0.074, 0.077, 0.080)
COMMAND_TAGS = {
    0.0: "x000",
    0.074: "x074",
    0.077: "x077",
    0.080: "x080",
}
COMMAND_INDEX = 6
VECTOR_DIM = 115


def _tensor_names(model: onnx.ModelProto) -> set[str]:
    names = {value.name for value in model.graph.input}
    names.update(value.name for value in model.graph.output)
    names.update(initializer.name for initializer in model.graph.initializer)
    for node in model.graph.node:
        names.update(name for name in node.input if name)
        names.update(name for name in node.output if name)
    return names


def _safe_name(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value)


def _add_command_replacement(
    model: onnx.ModelProto,
    *,
    source: str,
    target: str,
    command: float,
    tag: str,
) -> str:
    """Add one exact Where that preserves every field except command x."""

    names = _tensor_names(model)
    if source not in names or target not in names:
        raise DerivationError(f"unknown command replacement {source} -> {target} for {tag}")
    stem = f"t247_{tag}_{_safe_name(target)}"
    output = f"{stem}_value"
    mask_name = f"{stem}_mask"
    values_name = f"{stem}_values"
    mask = np.zeros((1, VECTOR_DIM), dtype=np.bool_)
    mask[0, COMMAND_INDEX] = True
    values = np.zeros((1, VECTOR_DIM), dtype=np.float32)
    values[0, COMMAND_INDEX] = np.float32(command)
    model.graph.initializer.extend(
        (
            numpy_helper.from_array(mask, mask_name),
            numpy_helper.from_array(values, values_name),
        )
    )
    model.graph.node.append(
        helper.make_node(
            "Where",
            (mask_name, values_name, source),
            (output,),
            name=f"{stem}_replace_command",
        )
    )
    return output


def _stable_topological_sort(model: onnx.ModelProto) -> None:
    available = {value.name for value in model.graph.input}
    available.update(initializer.name for initializer in model.graph.initializer)
    pending = list(model.graph.node)
    ordered: list[onnx.NodeProto] = []
    while pending:
        advanced = False
        remaining: list[onnx.NodeProto] = []
        for node in pending:
            if all(not name or name in available for name in node.input):
                ordered.append(node)
                available.update(name for name in node.output if name)
                advanced = True
            else:
                remaining.append(node)
        if not advanced:
            blocked = [
                {
                    "name": node.name,
                    "missing": [name for name in node.input if name and name not in available],
                }
                for node in remaining[:5]
            ]
            raise DerivationError(f"cannot topologically order command graph: {blocked}")
        pending = remaining
    del model.graph.node[:]
    model.graph.node.extend(ordered)


def _context_aliases(route: str, names: set[str]) -> dict[str, str]:
    regime, conditional = parse_route(route)
    if regime == "positive" or "conditional_adapter_location" not in names:
        return {}
    selected = (
        "negative_condition_adapter_location"
        if conditional
        else "nominal_dynamic_conditional_adapter"
    )
    return {"conditional_adapter_location": selected}


def _pre_inverse_command(route: str, command: float) -> float:
    regime, conditional = parse_route(route)
    if conditional:
        return 0.074 if command != 0.0 else 0.0
    if regime == "tail" and command != 0.0:
        return 0.077
    return min(command, 0.077)


def command_aliases_and_nodes(
    model: onnx.ModelProto,
    route: str,
    command: float,
) -> dict[str, str]:
    if command not in COMMAND_TAGS:
        raise DerivationError(f"unsupported exact command {command!r}")
    regime, conditional = parse_route(route)
    tag = COMMAND_TAGS[command]
    names = _tensor_names(model)
    aliases = _context_aliases(route, names)

    if command == 0.0:
        pre_inverse_target = "t149_policy_obs" if conditional else "t222_global_policy_obs"
        aliases[pre_inverse_target] = "obs"
        if regime == "positive":
            aliases["t162_policy_obs"] = "t17_source_obs"
        aliases["v117_source_continuous_actions"] = "deadband_zero_action"
        aliases["t17_source_continuous_actions"] = "v117_zero_action"
        return aliases

    pre_inverse_target = "t149_policy_obs" if conditional else "t222_global_policy_obs"
    effective = _pre_inverse_command(route, command)
    if np.float32(effective) == np.float32(command):
        aliases[pre_inverse_target] = "obs"
    else:
        replacement = _add_command_replacement(
            model,
            source="obs",
            target=pre_inverse_target,
            command=effective,
            tag=tag,
        )
        aliases[pre_inverse_target] = replacement

    if regime == "positive":
        replacement = _add_command_replacement(
            model,
            source="t17_source_obs",
            target="t162_policy_obs",
            command=0.074,
            tag=f"{tag}_positive",
        )
        aliases["t162_policy_obs"] = replacement

    if route == "lower-cond0" and "t234_command_selected_adapter_location" in names:
        aliases["t234_command_selected_adapter_location"] = (
            "t234_paired_final_adapter_location"
            if command == 0.074
            else "nominal_condition_adapter_location"
        )
    aliases["v117_source_continuous_actions"] = "deadband_source_actions"
    aliases["t17_source_continuous_actions"] = "v117_rate_projected_action"
    return aliases


def specialize_model(
    source: onnx.ModelProto,
    route: str,
    command: float,
) -> onnx.ModelProto:
    model = copy.deepcopy(source)
    actual_inputs = tuple(value.name for value in model.graph.input)
    actual_outputs = tuple(value.name for value in model.graph.output)
    if actual_inputs != POLICY_INPUTS or actual_outputs != POLICY_OUTPUTS:
        raise DerivationError(
            f"source ABI mismatch: inputs={actual_inputs}, outputs={actual_outputs}"
        )
    aliases = command_aliases_and_nodes(model, route, command)
    _apply_aliases(model, aliases)
    _stable_topological_sort(model)
    _backward_dead_code_elimination(model)
    checker.check_model(model, full_check=True)
    return model


def _summary(path: Path, model: onnx.ModelProto) -> dict[str, object]:
    counts = Counter(node.op_type for node in model.graph.node)
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "nodes": len(model.graph.node),
        "initializers": len(model.graph.initializer),
        "operation_counts": dict(sorted(counts.items())),
    }


def derive(context_root: Path, output_root: Path) -> dict[str, object]:
    context_root = context_root.resolve()
    output_root = output_root.resolve()
    if output_root.is_relative_to(ROOT):
        raise DerivationError("generated ONNX output must remain outside the repository")
    manifest_path = context_root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    context_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if context_manifest.get("schema_version") != (
        "open_duck_x5.t247_context_route_variant_manifest.v1"
    ):
        raise DerivationError("unexpected context-route manifest schema")
    if context_manifest["source_policy"]["sha256"] != EXPECTED_POLICY_SHA256:
        raise DerivationError("context routes do not derive from frozen T247")
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"refusing non-empty command output root: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    source_entries = {
        entry["name"]: entry
        for entry in context_manifest["generated"]
        if entry["name"] in ROUTE_NAMES
    }
    if set(source_entries) != set(ROUTE_NAMES):
        raise DerivationError("context manifest does not contain all six routes")

    generated: dict[str, dict[str, object]] = {}
    sources: dict[str, dict[str, object]] = {}
    for route in ROUTE_NAMES:
        source_path = context_root / source_entries[route]["file"]
        if sha256(source_path) != source_entries[route]["sha256"]:
            raise DerivationError(f"context route hash mismatch: {route}")
        source = onnx.load(source_path, load_external_data=False)
        sources[route] = {
            "file": source_path.name,
            "bytes": source_path.stat().st_size,
            "sha256": sha256(source_path),
            "nodes": len(source.graph.node),
            "initializers": len(source.graph.initializer),
        }
        for command in COMMANDS:
            tag = COMMAND_TAGS[command]
            name = f"{route}-{tag}"
            output_path = output_root / f"policy.{name}.onnx"
            model = specialize_model(source, route, command)
            output_path.write_bytes(model_bytes(model))
            generated[name] = {
                "route": route,
                "command_x_m_s": command,
                **_summary(output_path, model),
            }

    manifest: dict[str, object] = {
        "schema_version": "open_duck_x5.t247_command_route_variant_manifest.v1",
        "source_policy_sha256": EXPECTED_POLICY_SHA256,
        "context_manifest": {
            "file": manifest_path.name,
            "sha256": sha256(manifest_path),
        },
        "commands_m_s": list(COMMANDS),
        "routes": list(ROUTE_NAMES),
        "sources": sources,
        "generated": generated,
        "generated_models": len(generated),
        "fallback_rule": "retain each source context route for every other valid command",
        "policy_inputs": list(POLICY_INPUTS),
        "policy_outputs": list(POLICY_OUTPUTS),
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context-variant-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = derive(args.context_variant_root, args.output_root)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
