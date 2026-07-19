"""Evidence-backed completion audit for the default-disabled winner-v2 track."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any

from .winner_v2 import (
    WINNER_V2_OBSERVATION_DIM,
    WINNER_V2_SELECTED_POLICY_SHA256,
)

AUDIT_SCHEMA_VERSION = "open_duck_x5.winner_v2_completion_audit.v1"
EXPECTED_SHA256 = {
    "src/open_duck_x5/contract.py": (
        "96dabb64e7e36b8e8515f2f34961b9d01e0f3da0de9e8e41260cd256bb7fa504"
    ),
    "docs/OBSERVATION_ACTION_CONTRACT.md": (
        "f9fb7b6edbf8d1ae6ad24e92bfe4371b83944e69eb8f611bb4aba296a9025db3"
    ),
    "src/open_duck_x5/winner_v2.py": (
        "235d32eca034e4d7d5507337bb851b84ccb206d4ad499c86279381e82d38ae2b"
    ),
    "artifacts/gates/phase_5_policy/winner_v2_runtime_v2_verification_20260719.json": (
        "e1842ca64e91056b96c297666803bdeec7c5ff2950d4dfe32e27044379049b14"
    ),
    "artifacts/gates/phase_5_policy/winner_v2_full_chain_verification_20260719.json": (
        "85a5b230a8f4f79e04683b1098357df3ade55e90154a7e7ee2b8dc415d4ca541"
    ),
    "artifacts/gates/phase_5_policy/winner_v2_final_asset_freeze_closure_20260719.json": (
        "281382bb7d29d71e27211356da740535e0bcbbbe21ff5c6ef429fd05bf383110"
    ),
    "artifacts/gates/phase_5_policy/winner_v2_variable_configuration_hold_20260719.json": (
        "534d78e485739c1a956acc8907c5021ec27f2b600503b7ab4b274bc12bdb3791"
    ),
}
ALLOWED_WINNER_V2_CONSUMERS = {
    "winner_v2.py",
    "winner_v2_verifier.py",
    "winner_v2_cpu_preflight.py",
    "winner_v2_completion_audit.py",
}
FORBIDDEN_HARDWARE_IMPORT_ROOTS = {
    "gpiod",
    "serial",
    "smbus2",
}
FORBIDDEN_WINNER_V2_SOURCE_TOKENS = {
    "head_overlay",
    "head_mode",
    "low_pass_filter",
    "position_filter",
}


class WinnerV2CompletionAuditError(RuntimeError):
    """The current evidence cannot support a winner-v2 completion claim."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WinnerV2CompletionAuditError(f"could not read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise WinnerV2CompletionAuditError(f"{label} must be a JSON object")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise WinnerV2CompletionAuditError(message)


def _import_target(node: ast.ImportFrom) -> str:
    prefix = "." * node.level
    return prefix + (node.module or "")


def _audit_default_disabled(root: Path) -> dict[str, Any]:
    source_root = root / "src/open_duck_x5"
    winner_path = source_root / "winner_v2.py"
    try:
        winner_source = winner_path.read_text(encoding="utf-8")
        winner_tree = ast.parse(winner_source, filename=str(winner_path))
    except (OSError, SyntaxError) as exc:
        raise WinnerV2CompletionAuditError(f"could not parse winner-v2 source: {exc}") from exc
    imported_roots: set[str] = set()
    for node in ast.walk(winner_tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            target = _import_target(node).lstrip(".")
            if target:
                imported_roots.add(target.split(".", 1)[0])
    forbidden_imports = sorted(imported_roots & FORBIDDEN_HARDWARE_IMPORT_ROOTS)
    _require(not forbidden_imports, f"winner-v2 imports hardware modules: {forbidden_imports}")
    forbidden_tokens = sorted(
        token for token in FORBIDDEN_WINNER_V2_SOURCE_TOKENS if token in winner_source
    )
    _require(not forbidden_tokens, f"winner-v2 contains forbidden transforms: {forbidden_tokens}")

    consumers: list[str] = []
    for path in sorted(source_root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            raise WinnerV2CompletionAuditError(f"could not scan {path}: {exc}") from exc
        imports_winner = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports_winner = imports_winner or any(
                    alias.name == "open_duck_x5.winner_v2" for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom):
                target = _import_target(node)
                imports_winner = imports_winner or target in {
                    ".winner_v2",
                    "open_duck_x5.winner_v2",
                }
        if imports_winner:
            consumers.append(path.name)
            _require(
                path.name in ALLOWED_WINNER_V2_CONSUMERS,
                f"production module {path.name} enables winner-v2",
            )
    _require("winner_v2_verifier.py" in consumers, "winner-v2 verifier import is missing")
    _require("winner_v2_cpu_preflight.py" in consumers, "winner-v2 CPU preflight import is missing")
    return {
        "hardware_imports": forbidden_imports,
        "forbidden_transforms": forbidden_tokens,
        "allowed_consumers": consumers,
        "production_runtime_consumer_count": 0,
    }


def audit_winner_v2_completion(*, repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    identities: dict[str, str] = {}
    for relative_path, expected in EXPECTED_SHA256.items():
        path = root / relative_path
        try:
            actual = _sha256(path)
        except OSError as exc:
            raise WinnerV2CompletionAuditError(
                f"could not hash frozen input {relative_path}: {exc}"
            ) from exc
        _require(actual == expected, f"frozen identity changed for {relative_path}")
        identities[relative_path] = actual

    runtime = _load_object(
        root
        / "artifacts/gates/phase_5_policy/winner_v2_runtime_v2_verification_20260719.json",
        "winner-v2 runtime verification",
    )
    full_chain = _load_object(
        root
        / "artifacts/gates/phase_5_policy/winner_v2_full_chain_verification_20260719.json",
        "winner-v2 full-chain verification",
    )
    freeze = _load_object(
        root
        / "artifacts/gates/phase_5_policy/winner_v2_final_asset_freeze_closure_20260719.json",
        "winner-v2 asset freeze closure",
    )
    hold = _load_object(
        root
        / "artifacts/gates/phase_5_policy/winner_v2_variable_configuration_hold_20260719.json",
        "winner-v2 configuration hold",
    )

    _require(WINNER_V2_OBSERVATION_DIM == 115, "winner-v2 observation dimension changed")
    _require(
        runtime.get("status") == "PASS_RECURSIVE_BIT_EXACT_WIRE_CLOSURE",
        "runtime verification is not a pass",
    )
    _require(runtime.get("ticks") == 2400, "runtime verification does not cover 2,400 ticks")
    _require(
        runtime.get("recursive_numeric_closure_passed") is True,
        "recursive numeric closure failed",
    )
    _require(
        runtime.get("selected_policy", {}).get("sha256")
        == WINNER_V2_SELECTED_POLICY_SHA256,
        "selected policy identity changed",
    )
    faults = runtime.get("fault_injection")
    _require(
        faults
        == {
            "ambiguous_sample_epoch": True,
            "failed_send_rejected": True,
            "failed_send_state_unchanged": True,
            "nonfinite_sensor": True,
            "stale_sample": True,
            "unsupported_command": True,
        },
        "winner-v2 fault-injection coverage differs",
    )
    semantic_cells = runtime.get("semantic_cells")
    recursive_cells = runtime.get("recursive_runtime_cells")
    _require(
        isinstance(semantic_cells, list)
        and len(semantic_cells) == 4
        and all(cell.get("ticks") == 600 for cell in semantic_cells),
        "semantic verification population differs",
    )
    _require(
        isinstance(recursive_cells, list)
        and len(recursive_cells) == 4
        and all(cell.get("ticks") == 600 for cell in recursive_cells),
        "recursive verification population differs",
    )
    for cell in recursive_cells:
        classifications = cell.get("classifications", {})
        for key in (
            "external_5p24_limiter_identity",
            "rate_and_envelope_unchanged",
            "saturation_unchanged",
        ):
            _require(classifications.get(key) is True, f"recursive classification failed: {key}")

    _require(
        full_chain.get("status") == "PASS_FULL_2400_TICK_CPU_REPLAY",
        "full-chain verification is not a pass",
    )
    _require(full_chain.get("ticks") == 2400, "full-chain verification does not cover 2,400 ticks")
    _require(
        full_chain.get("execution_provider") == "CPUExecutionProvider",
        "full-chain verification was not CPU-only",
    )
    _require(
        full_chain.get("external_5p24_limiter_identity_all_ticks") is True,
        "legacy limiter is not identity",
    )
    chain_cells = full_chain.get("cells")
    _require(
        isinstance(chain_cells, list) and len(chain_cells) == 4,
        "full-chain cell population differs",
    )
    for cell in chain_cells:
        _require(
            cell.get("max_observer_obs_83_97_error_rad") == 0.0,
            "obs[83:97] differs from P30 observer",
        )
        _require(cell.get("max_observer_next_error_rad") == 0.0, "P30 observer next state differs")

    _require(
        freeze.get("status") == "PASS_FINAL_OFFLINE_ASSET_FREEZE",
        "final offline asset freeze is not a pass",
    )
    _require(
        freeze.get("frozen_identities", {}).get("selected_onnx_sha256")
        == WINNER_V2_SELECTED_POLICY_SHA256,
        "asset freeze selected ONNX differs",
    )
    freeze_authority = freeze.get("authority", {})
    _require(
        freeze_authority.get("robot_clearance") is False
        and freeze_authority.get("gate5") is False
        and freeze_authority.get("runtime_deployment") is False,
        "asset freeze broadened hardware authority",
    )
    _require(
        hold.get("status") == "REQUEST_POLICY_ROBUSTNESS_REPLACEMENT",
        "configuration hold is missing",
    )
    operator = hold.get("operator_requirement", {})
    _require(
        operator.get("measuring_equipment_required") is False
        and operator.get("manual_com_entry_required") is False
        and operator.get("per_build_com_clearance_route_selected") is False,
        "manual measurement route was reintroduced",
    )
    architecture = _audit_default_disabled(root)

    offline_requirements = [
        {"id": "frozen_v1_101d_untouched", "status": "PASS"},
        {"id": "separate_default_disabled_115d_path", "status": "PASS"},
        {"id": "p30_observer_in_obs_83_97", "status": "PASS"},
        {"id": "projected_reference_in_obs_101_115", "status": "PASS"},
        {"id": "stateful_previous_action_chain", "status": "PASS"},
        {"id": "phase_reset_and_observe_then_advance", "status": "PASS"},
        {"id": "graph_authoritative_limits_guard_deadband", "status": "PASS"},
        {"id": "legacy_5p24_limiter_identity", "status": "PASS"},
        {"id": "no_overlay_filter_or_extra_projection", "status": "PASS"},
        {"id": "transactional_fail_closed_state", "status": "PASS"},
        {"id": "full_2400_tick_cpu_verification", "status": "PASS"},
        {"id": "selected_checkpoint_and_asset_freeze", "status": "PASS"},
    ]
    campaign_requirements = [
        {"id": "manual_com_measurement_packet", "status": "SUPERSEDED_NO_MEASUREMENT"},
        {"id": "supported_configuration_envelope", "status": "PENDING_POLICY"},
        {"id": "policy_robot_clearance", "status": "PENDING_POLICY"},
        {"id": "automatic_supported_calibration", "status": "NOT_RUN"},
        {"id": "x5_cpu_only_preflight", "status": "NOT_RUN"},
        {"id": "frozen_gate5_launcher", "status": "BLOCKED_BY_PRIOR_GATES"},
        {"id": "suspended_x0_600_ticks", "status": "NOT_RUN"},
        {"id": "suspended_x008_600_ticks", "status": "NOT_RUN"},
        {"id": "grounded_walking", "status": "OUT_OF_SCOPE"},
    ]
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "status": "HOLD_POLICY_ENVELOPE_AND_PHYSICAL_GATES",
        "offline_runtime_v2_complete": True,
        "goal_complete": False,
        "identities": identities,
        "architecture": architecture,
        "offline_requirements": offline_requirements,
        "campaign_requirements": campaign_requirements,
        "authority": {
            "robot_clearance": False,
            "rdkx5_policy_execution": False,
            "serial": False,
            "torque": False,
            "motion": False,
            "gate5": False,
            "grounded_walking": False,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit winner-v2 completion evidence")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = args.output.resolve()
    output.unlink(missing_ok=True)
    try:
        result = audit_winner_v2_completion(repo_root=args.repo_root)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, WinnerV2CompletionAuditError) as exc:
        output.unlink(missing_ok=True)
        print(f"result=FAIL reason={exc}")
        return 2
    print(f"result={result['status']} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
