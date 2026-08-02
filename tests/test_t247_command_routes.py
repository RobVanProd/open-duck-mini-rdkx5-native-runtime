from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from open_duck_x5.t247_command_routes import (
    COMMAND_TAGS,
    CONTEXT_MANIFEST_SCHEMA,
    ROUTE_NAMES,
    T247_POLICY_SHA256,
    T247CommandRouteCatalog,
    T247CommandRouteTransaction,
    route_from_predicates,
)
from open_duck_x5.winner_v13_state_coherent import WinnerV13ContractError


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _entry(path: Path, **extra: object) -> dict[str, object]:
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
        **extra,
    }


def _dummy_catalog(tmp_path: Path) -> tuple[dict[str, Path], dict[str, object]]:
    context_root = tmp_path / "context"
    command_root = tmp_path / "command"
    context_root.mkdir()
    command_root.mkdir()
    router = context_root / "policy.context-router.onnx"
    router.write_bytes(b"router")
    generated_context: list[dict[str, object]] = [
        {"name": "router", **_entry(router)}
    ]
    sources: dict[str, dict[str, object]] = {}
    for route in ROUTE_NAMES:
        path = context_root / f"policy.{route}.onnx"
        path.write_bytes(f"source:{route}".encode())
        receipt = _entry(path)
        sources[route] = receipt
        generated_context.append({"name": route, **receipt})
    context_manifest = context_root / "manifest.json"
    context_manifest.write_text(
        json.dumps(
            {
                "schema_version": CONTEXT_MANIFEST_SCHEMA,
                "source_policy": {"sha256": T247_POLICY_SHA256},
                "routes": list(ROUTE_NAMES),
                "generated": generated_context,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    generated: dict[str, dict[str, object]] = {}
    for route in ROUTE_NAMES:
        for command, tag in COMMAND_TAGS:
            path = command_root / f"policy.{route}-{tag}.onnx"
            path.write_bytes(f"command:{route}:{tag}".encode())
            generated[f"{route}-{tag}"] = {
                "route": route,
                "command_x_m_s": command,
                **_entry(path),
            }
    command_manifest = command_root / "manifest.json"
    payload: dict[str, object] = {
        "schema_version": "open_duck_x5.t247_command_route_variant_manifest.v1",
        "source_policy_sha256": T247_POLICY_SHA256,
        "context_manifest": {
            "file": context_manifest.name,
            "sha256": _sha256(context_manifest),
        },
        "commands_m_s": [value for value, _ in COMMAND_TAGS],
        "routes": list(ROUTE_NAMES),
        "sources": sources,
        "generated": generated,
        "generated_models": 24,
        "fallback_rule": (
            "retain each source context route for every other valid command"
        ),
        "policy_inputs": [
            "obs",
            "previous_action",
            "h_in",
            "calibration_context",
        ],
        "policy_outputs": [
            "continuous_actions",
            "previous_action_out",
            "h_out",
        ],
    }
    command_manifest.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    return (
        {
            "context_root": context_root,
            "command_root": command_root,
            "command_manifest_path": command_manifest,
        },
        payload,
    )


@pytest.mark.parametrize(
    ("predicates", "expected"),
    [
        ((False, False, False, False, False), "lower-cond0"),
        ((False, True, False, True, False), "lower-cond1"),
        ((False, False, True, False, True), "positive-cond0"),
        ((False, True, True, True, True), "positive-cond1"),
        ((True, False, False, False, False), "tail-cond0"),
        ((True, True, False, True, False), "tail-cond1"),
    ],
)
def test_route_from_predicates_maps_all_routes(
    predicates: tuple[bool, ...],
    expected: str,
) -> None:
    assert route_from_predicates(predicates) == expected


@pytest.mark.parametrize(
    "predicates",
    [
        (False, False, False, True, False),
        (False, False, True, False, False),
        (True, False, True, False, True),
    ],
)
def test_route_from_predicates_rejects_inconsistent_graph_state(
    predicates: tuple[bool, ...],
) -> None:
    with pytest.raises(WinnerV13ContractError):
        route_from_predicates(predicates)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ([0.0, 0, 0, 0, 0, 0, 0], "x000"),
        ([0.074, 0, 0, 0, 0, 0, 0], "x074"),
        ([0.077, 0, 0, 0, 0, 0, 0], "x077"),
        ([0.08, 0, 0, 0, 0, 0, 0], "x080"),
        ([0.075, 0, 0, 0, 0, 0, 0], "fallback"),
        ([0.08, 0.001, 0, 0, 0, 0, 0], "fallback"),
        ([-0.0, 0, 0, 0, 0, 0, 0], "fallback"),
    ],
)
def test_command_specialization_requires_an_exact_supported_vector(
    command: list[float],
    expected: str,
) -> None:
    value = np.asarray(command, dtype=np.float64)
    assert T247CommandRouteTransaction._tag_for_commands(value) == expected


def test_catalog_verifies_all_30_external_models(tmp_path: Path) -> None:
    paths, _ = _dummy_catalog(tmp_path)
    catalog = T247CommandRouteCatalog(
        **paths,
        command_manifest_sha256=_sha256(paths["command_manifest_path"]),
        context_router_sha256=_sha256(
            paths["context_root"] / "policy.context-router.onnx"
        ),
    )
    assert catalog.asset_count == 30
    assert catalog.graph_asset("lower-cond0", "fallback").path == (
        paths["context_root"] / "policy.lower-cond0.onnx"
    )
    assert catalog.graph_asset("tail-cond1", "x080").path == (
        paths["command_root"] / "policy.tail-cond1-x080.onnx"
    )


def test_catalog_rejects_a_model_changed_after_manifest(tmp_path: Path) -> None:
    paths, _ = _dummy_catalog(tmp_path)
    manifest_hash = _sha256(paths["command_manifest_path"])
    (paths["command_root"] / "policy.tail-cond1-x080.onnx").write_bytes(b"tampered")
    with pytest.raises(WinnerV13ContractError, match="byte count differs"):
        T247CommandRouteCatalog(
            **paths,
            command_manifest_sha256=manifest_hash,
            context_router_sha256=_sha256(
                paths["context_root"] / "policy.context-router.onnx"
            ),
        )


def test_production_host_modules_do_not_import_robot_or_tools_code() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "src/open_duck_x5/t247_x5_optimized.py",
        "src/open_duck_x5/t247_command_routes.py",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        assert "from tools" not in source
        assert "import tools" not in source
        assert "from .bus" not in source
        assert "from .sensors" not in source
        assert "from .runtime" not in source
