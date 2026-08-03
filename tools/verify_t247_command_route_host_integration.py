#!/usr/bin/env python3
"""Verify the preregistered production T247 command-route host contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from open_duck_x5.constants import ACTION_DIM  # noqa: E402
from open_duck_x5.t247_command_routes import (  # noqa: E402
    ROUTE_NAMES,
    T247CommandRouteCatalog,
    T247CommandRouteTransaction,
    _T247ContextRouter,
    calibrator_spec,
)
from open_duck_x5.winner_v13_state_coherent import (  # noqa: E402
    CALIBRATION_TICKS,
    GraphAsset,
    P30FitAsset,
    WinnerV13SendError,
    WinnerV13StateError,
)
from tools import run_t247_x5_context_route_reserved_screen as host_tools  # noqa: E402
from tools.run_winner_v14_x5_paced_screen import (  # noqa: E402
    locomotion_spec,
    receipt,
    samples,
    stage,
)
from tools.verify_t247_context_route_specialization import (  # noqa: E402
    interior_contexts,
)
from tools.winner_v16_target_optimized import (  # noqa: E402
    WinnerV16TargetOptimizedTransaction,
)

PREREGISTRATION = (
    ROOT
    / "artifacts"
    / "gates"
    / "phase_5_policy"
    / "t247_deployment_command_route_host_integration_preregistration_20260801.json"
)
PREREGISTRATION_SHA256 = "ebf7f46e40883ae10cc947fe928315012be6d9cea67bd1ff272a4ddbc54cdd62"
CALIBRATOR_SHA256 = "0f3aebfd9946a6271fdb14adec3d68d556648f270984639d372c973a7d7dc576"
POLICY_SHA256 = "dadfb446ea7c720f274a15bc65e9171c2e74d715ccfaf58adbb408b6c1365a54"
MANIFEST_SHA256 = "5621f7c6782a8346bf25f05ce7f0bc002acbe8e98872cf658f0d44773511b4cd"
ROUTER_SHA256 = "3b1f406fba5147a3f38ec59fc7f9c8d42dd27fa7eeb54344f447c060eb95b284"
LOWER_COND0_SHA256 = "9f07e51595658a085effdd0e682905ea32ef36f9c4de591254407cd178c54825"
P30_SHA256 = "a58db8ffc505d2bb64cba7f5618d0e2c65904fc9f9ac37b560a1231e090f5f4f"
REFERENCE_SHA256 = "8102d9cd139584816d807ca635bcca6d37fa6b3c455848e00395b6d565968212"
FULL_CHAIN_TICKS = 2298
ROUTE_SWITCH_TICKS = 7920
ROUTE_SWITCH_COMMANDS = (
    0.0,
    0.074,
    0.077,
    0.080,
    0.075,
    0.079,
    0.080,
    0.0,
    0.077,
    0.074,
    0.076,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibrator", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--context-root", type=Path, required=True)
    parser.add_argument("--command-root", type=Path, required=True)
    parser.add_argument("--command-manifest", type=Path, required=True)
    parser.add_argument("--p30-fit", type=Path, required=True)
    parser.add_argument("--reference-table", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_catalog(args: argparse.Namespace) -> T247CommandRouteCatalog:
    return T247CommandRouteCatalog(
        context_root=args.context_root,
        command_root=args.command_root,
        command_manifest_path=args.command_manifest,
        command_manifest_sha256=MANIFEST_SHA256,
        context_router_sha256=ROUTER_SHA256,
    )


def graph_assets(
    args: argparse.Namespace,
) -> tuple[GraphAsset, P30FitAsset]:
    calibrator = GraphAsset(
        args.calibrator,
        calibrator_spec(),
        frozenset({CALIBRATOR_SHA256}),
    )
    fit = P30FitAsset(args.p30_fit, frozenset({P30_SHA256}))
    return calibrator, fit


def build_routed(
    args: argparse.Namespace,
    catalog: T247CommandRouteCatalog,
    *,
    enabled: bool,
) -> T247CommandRouteTransaction:
    calibrator, fit = graph_assets(args)
    return T247CommandRouteTransaction(
        calibrator=calibrator,
        catalog=catalog,
        p30_fit=fit,
        reference_table_path=args.reference_table,
        enabled=enabled,
        warmup_runs=1,
    )


def build_source(args: argparse.Namespace) -> WinnerV16TargetOptimizedTransaction:
    calibrator, fit = graph_assets(args)
    return WinnerV16TargetOptimizedTransaction(
        calibrator=calibrator,
        locomotion=GraphAsset(
            args.context_root / "policy.lower-cond0.onnx",
            locomotion_spec(),
            frozenset({LOWER_COND0_SHA256}),
        ),
        p30_fit=fit,
        reference_table_path=args.reference_table,
        enabled=True,
        warmup_runs=1,
    )


def require_equal(
    source: WinnerV16TargetOptimizedTransaction,
    routed: T247CommandRouteTransaction,
    *,
    tick: int,
    boundary: str,
) -> None:
    mismatch = host_tools.mismatch(source, routed, committed=boundary == "committed")
    if mismatch is not None:
        raise RuntimeError(
            f"T247 host mismatch at tick {tick} ({boundary}): {mismatch}"
        )


def run_full_chain(
    args: argparse.Namespace,
    catalog: T247CommandRouteCatalog,
    command: float,
) -> dict[str, Any]:
    source = build_source(args)
    routed = build_routed(args, catalog, enabled=True)
    sample = samples(command)
    offsets = sample["soft_offsets_rad"]
    source.bind_soft_offsets(offsets)
    routed.bind_soft_offsets(offsets)
    source_actions = np.empty((FULL_CHAIN_TICKS, ACTION_DIM), dtype=np.float32)
    routed_actions = np.empty_like(source_actions)
    maximum_rate_excess = 0.0
    for tick in range(FULL_CHAIN_TICKS):
        stage(source, tick, sample)
        stage(routed, tick, sample)
        np.copyto(source_actions[tick], source.normalized_action_view)
        np.copyto(routed_actions[tick], routed.normalized_action_view)
        require_equal(source, routed, tick=tick, boundary="staged")
        maximum_rate_excess = max(
            maximum_rate_excess,
            float(np.max(routed.target_pipeline.graph_rate_excess_rad_s)),
        )
        source.complete_send(write_succeeded=True)
        routed.complete_send(write_succeeded=True)
        require_equal(source, routed, tick=tick, boundary="committed")
        if tick + 1 == CALIBRATION_TICKS:
            source.confirm_calibration_handoff(True)
            routed.confirm_calibration_handoff(True)
    if not np.array_equal(source_actions, routed_actions):
        raise RuntimeError(f"fixed command {command} action traces differ")
    return {
        "command_x_m_s": command,
        "ticks": FULL_CHAIN_TICKS,
        "selected_context_route": routed.selected_context_route,
        "selected_command_route": routed.selected_command_route,
        "route_switches": routed.route_switches,
        "fallback_ticks": routed.fallback_ticks,
        "action_trace_sha256": hashlib.sha256(routed_actions.tobytes()).hexdigest(),
        "all_outputs_and_states_byte_exact": True,
        "maximum_rate_excess_rad_s": maximum_rate_excess,
    }


def run_switch_chain(
    args: argparse.Namespace,
    catalog: T247CommandRouteCatalog,
) -> dict[str, Any]:
    source = build_source(args)
    routed = build_routed(args, catalog, enabled=True)
    sample = samples(0.0)
    offsets = sample["soft_offsets_rad"]
    source.bind_soft_offsets(offsets)
    routed.bind_soft_offsets(offsets)
    maximum_rate_excess = 0.0
    total_ticks = CALIBRATION_TICKS + ROUTE_SWITCH_TICKS
    for tick in range(total_ticks):
        if tick >= CALIBRATION_TICKS:
            index = (tick - CALIBRATION_TICKS) % len(ROUTE_SWITCH_COMMANDS)
            sample["commands"][0] = ROUTE_SWITCH_COMMANDS[index]
        stage(source, tick, sample)
        stage(routed, tick, sample)
        require_equal(source, routed, tick=tick, boundary="staged")
        maximum_rate_excess = max(
            maximum_rate_excess,
            float(np.max(routed.target_pipeline.graph_rate_excess_rad_s)),
        )
        source.complete_send(write_succeeded=True)
        routed.complete_send(write_succeeded=True)
        require_equal(source, routed, tick=tick, boundary="committed")
        if tick + 1 == CALIBRATION_TICKS:
            source.confirm_calibration_handoff(True)
            routed.confirm_calibration_handoff(True)
    return {
        "locomotion_ticks": ROUTE_SWITCH_TICKS,
        "selected_context_route": routed.selected_context_route,
        "route_switches": routed.route_switches,
        "fallback_ticks": routed.fallback_ticks,
        "all_outputs_and_states_byte_exact": True,
        "maximum_rate_excess_rad_s": maximum_rate_excess,
    }


def verify_default_and_fault_boundaries(
    args: argparse.Namespace,
    catalog: T247CommandRouteCatalog,
) -> dict[str, bool]:
    sample = samples(0.0)
    disabled = build_routed(args, catalog, enabled=False)
    disabled_closed = False
    try:
        stage(disabled, 0, sample)
    except WinnerV13StateError:
        disabled_closed = True

    host = build_routed(args, catalog, enabled=True)
    host.bind_soft_offsets(sample["soft_offsets_rad"])
    stage(host, 0, sample)
    staged = host.normalized_action_view.copy()
    host.discard_staged()
    discard_exact = not host.pending and host.committed_ticks == 0 and not host.faulted
    stage(host, 0, sample)
    discard_exact = discard_exact and bool(
        np.array_equal(staged, host.normalized_action_view)
    )
    send_failure_closed = False
    try:
        host.complete_send(write_succeeded=False)
    except WinnerV13SendError:
        send_failure_closed = host.faulted and not host.pending and host.committed_ticks == 0
    return {
        "default_disabled_fault_closed": disabled_closed,
        "discard_and_restage_exact": discard_exact,
        "send_failure_fault_closed": send_failure_closed,
    }


def main() -> int:
    args = parse_args()
    output = args.output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(output)
    if sha256(PREREGISTRATION) != PREREGISTRATION_SHA256:
        raise RuntimeError("T247 host integration preregistration changed")
    tracked_status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        text=True,
    ).strip()
    if tracked_status:
        raise RuntimeError("T247 host verifier requires a clean tracked worktree")
    expected_assets = {
        "calibrator": (args.calibrator.resolve(), CALIBRATOR_SHA256),
        "policy": (args.policy.resolve(), POLICY_SHA256),
        "command_manifest": (args.command_manifest.resolve(), MANIFEST_SHA256),
        "router": (
            (args.context_root / "policy.context-router.onnx").resolve(),
            ROUTER_SHA256,
        ),
        "p30_fit": (args.p30_fit.resolve(), P30_SHA256),
        "reference_table": (args.reference_table.resolve(), REFERENCE_SHA256),
    }
    asset_receipts = {name: receipt(path) for name, (path, _) in expected_assets.items()}
    asset_checks = {
        name: asset_receipts[name]["sha256"] == expected
        for name, (_, expected) in expected_assets.items()
    }
    if not all(asset_checks.values()):
        raise RuntimeError(f"selected asset mismatch: {asset_checks}")

    catalog = build_catalog(args)
    router = _T247ContextRouter(catalog, warmup_runs=1)
    contexts, context_evidence = interior_contexts(args.policy, router.session)
    router_exact = True
    for route in ROUTE_NAMES:
        for context in contexts[route]:
            router_exact = router_exact and router.select(context.reshape(64)) == route

    full_chains = [
        run_full_chain(args, catalog, command)
        for command in (0.0, 0.074, 0.077, 0.08)
    ]
    switch_chain = run_switch_chain(args, catalog)
    boundaries = verify_default_and_fault_boundaries(args, catalog)
    runtime_source = (ROOT / "src" / "open_duck_x5" / "runtime.py").read_text(
        encoding="utf-8"
    )
    production_sources = [
        ROOT / "src" / "open_duck_x5" / "t247_x5_optimized.py",
        ROOT / "src" / "open_duck_x5" / "t247_command_routes.py",
    ]
    source_text = "\n".join(path.read_text(encoding="utf-8") for path in production_sources)
    forbidden_imports_absent = all(
        value not in source_text
        for value in (
            "from tools",
            "import tools",
            "from .bus",
            "from .sensors",
            "from .runtime",
        )
    )
    checks = {
        "preregistration_exact": True,
        "tracked_worktree_clean_at_execution": not bool(tracked_status),
        "all_selected_asset_receipts_exact": all(asset_checks.values()),
        "all_30_route_assets_verified": catalog.asset_count == 30,
        "all_six_context_routes_selected_exactly": router_exact,
        "four_full_real_asset_chains": len(full_chains) == 4,
        "all_9192_full_chain_ticks_exact": all(
            chain["ticks"] == FULL_CHAIN_TICKS
            and chain["all_outputs_and_states_byte_exact"]
            for chain in full_chains
        ),
        "all_full_chains_select_lower_cond0": all(
            chain["selected_context_route"] == "lower-cond0"
            for chain in full_chains
        ),
        "all_full_chains_zero_rate_excess": all(
            chain["maximum_rate_excess_rad_s"] == 0.0 for chain in full_chains
        ),
        "route_switch_tick_count_exact": (
            switch_chain["locomotion_ticks"] == ROUTE_SWITCH_TICKS
        ),
        "route_switch_outputs_and_states_exact": switch_chain[
            "all_outputs_and_states_byte_exact"
        ],
        "route_switch_count_exact": switch_chain["route_switches"] == 7200,
        "fallback_tick_count_exact": switch_chain["fallback_ticks"] == 2160,
        "route_switch_chain_zero_rate_excess": (
            switch_chain["maximum_rate_excess_rad_s"] == 0.0
        ),
        **boundaries,
        "production_sources_have_no_tools_or_hardware_import": forbidden_imports_absent,
        "existing_runtime_has_no_t247_import_or_cli": "t247_command" not in runtime_source,
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    result: dict[str, Any] = {
        "schema_version": "open_duck_x5.t247_command_route_host_integration_result.v1",
        "status": (
            "PASS_T247_COMMAND_ROUTE_HOST_INTEGRATION"
            if not failed
            else "HOLD_T247_COMMAND_ROUTE_HOST_INTEGRATION"
        ),
        "date": "2026-08-01",
        "git": {
            "commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=ROOT,
                text=True,
            ).strip(),
            "tracked_clean": not bool(tracked_status),
        },
        "preregistration": receipt(PREREGISTRATION),
        "production_sources": {
            str(path.relative_to(ROOT)).replace("\\", "/"): receipt(path)
            for path in production_sources
        },
        "asset_receipts": asset_receipts,
        "catalog": {
            "verified_graph_assets": catalog.asset_count,
            "source_context_models": 6,
            "exact_command_models": 24,
            "fallback_preserved": True,
        },
        "context_routes": context_evidence,
        "full_chains": full_chains,
        "route_switch_chain": switch_chain,
        "boundary_checks": boundaries,
        "checks": checks,
        "checks_passed": sum(bool(value) for value in checks.values()),
        "checks_total": len(checks),
        "failed_checks": failed,
        "decision": (
            "EARN_EXPLICIT_RUNTIME_OPT_IN_WIRING_PREREGISTRATION_AND_GATE5_READINESS_AUDIT"
            if not failed
            else "HOLD_HOST_INTEGRATION_AND_FIX_ONLY_THE_CONTRACT_DEFECT"
        ),
        "authority": {
            "offline_cpu_only": True,
            "robot_access": False,
            "serial_bus": False,
            "servo_reads_or_writes": False,
            "sensors": False,
            "torque": False,
            "motion": False,
            "policy_deployed": False,
            "production_runtime_wiring": False,
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
