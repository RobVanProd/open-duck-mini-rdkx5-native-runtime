#!/usr/bin/env python3
"""Verify the preregistered default-off T247 runtime wiring on the mock bus."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from jsonschema import Draft202012Validator  # noqa: E402

from open_duck_x5 import runtime as runtime_module  # noqa: E402
from open_duck_x5.bus import ErrorCode  # noqa: E402
from open_duck_x5.bus.mock import MockSTS3215Bus  # noqa: E402
from open_duck_x5.runtime import (  # noqa: E402
    POLICY_CONTRACT_T247,
    Runtime,
    build_parser,
)
from open_duck_x5.safety import SafetyError  # noqa: E402
from open_duck_x5.t247_command_routes import (  # noqa: E402
    ROUTE_NAMES,
    T247_CALIBRATOR_SHA256,
    T247_COMMAND_MANIFEST_SHA256,
    T247_CONTEXT_ROUTER_SHA256,
    T247_P30_SHA256,
    T247_POLICY_SHA256,
    T247_REFERENCE_SHA256,
)

PREREGISTRATION = (
    ROOT
    / "artifacts"
    / "gates"
    / "phase_5_policy"
    / "t247_deployment_runtime_opt_in_wiring_replacement_preregistration_20260801.json"
)
PREREGISTRATION_SHA256 = "075f06df4ae1e7ef9ac73ee8126702a7db8a839b61bd813d7cc42d6eaf5fb622"
ACTIVE_TICKS = 258
CALIBRATION_TICKS = 250


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


def receipt(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    return {
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": sha256(resolved),
    }


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_config(path: Path, *, start_paused: bool) -> None:
    source = json.loads((ROOT / "duck_config.example.json").read_text(encoding="utf-8"))
    source["start_paused"] = start_paused
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(source, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def runtime_args(
    args: argparse.Namespace,
    *,
    config: Path,
    telemetry: Path,
    max_ticks: int,
    max_active_ticks: int,
) -> argparse.Namespace:
    values = [
        "--bus",
        "mock",
        "--config",
        str(config),
        "--telemetry",
        str(telemetry),
        "--policy-contract",
        POLICY_CONTRACT_T247,
        "--policy",
        str(args.policy),
        "--calibrator",
        str(args.calibrator),
        "--context-route-root",
        str(args.context_root),
        "--command-route-root",
        str(args.command_root),
        "--command-route-manifest",
        str(args.command_manifest),
        "--p30-fit",
        str(args.p30_fit),
        "--reference-table",
        str(args.reference_table),
        "--fixed-command-x",
        "0.08",
        "--home-seconds",
        "0.001",
        "--max-ticks",
        str(max_ticks),
        "--max-active-ticks",
        str(max_active_ticks),
    ]
    return build_parser().parse_args(values)


def load_telemetry(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ticks = [
        record
        for record in records
        if record["schema_version"] == "open_duck_x5.control_tick.v1"
    ]
    events = [
        record
        for record in records
        if record["schema_version"] == "open_duck_x5.runtime_event.v1"
    ]
    return ticks, events


def run_success(
    args: argparse.Namespace,
    *,
    config: Path,
    telemetry: Path,
) -> dict[str, Any]:
    runtime = Runtime(
        runtime_args(
            args,
            config=config,
            telemetry=telemetry,
            max_ticks=ACTIVE_TICKS + 4,
            max_active_ticks=ACTIVE_TICKS,
        )
    )
    host = runtime.t247_host
    bus = runtime.bus
    if host is None or not isinstance(bus, MockSTS3215Bus):
        raise RuntimeError("T247 mock runtime did not construct the reviewed host and bus")
    try:
        runtime.run()
        before_close = {
            "committed_ticks": host.committed_ticks,
            "confirmed_calibration_ticks": host.confirmed_calibration_ticks,
            "handoff_complete": host.handoff_complete,
            "faulted": host.faulted,
            "selected_context_route": host.selected_context_route,
            "selected_command_route": host.selected_command_route,
            "route_switches": host.route_switches,
            "fallback_ticks": host.fallback_ticks,
            "torque_enabled_after_run": bus.torque_enabled,
        }
    finally:
        runtime.close()
    ticks, events = load_telemetry(telemetry)
    return {
        "before_close": before_close,
        "torque_enabled_after_close": bus.torque_enabled,
        "ticks": ticks,
        "events": events,
    }


def run_paused(
    args: argparse.Namespace,
    *,
    config: Path,
    telemetry: Path,
) -> dict[str, Any]:
    runtime = Runtime(
        runtime_args(
            args,
            config=config,
            telemetry=telemetry,
            max_ticks=3,
            max_active_ticks=0,
        )
    )
    host = runtime.t247_host
    bus = runtime.bus
    if host is None or not isinstance(bus, MockSTS3215Bus):
        raise RuntimeError("paused T247 mock runtime did not construct expected objects")
    try:
        runtime.run()
        committed_ticks = host.committed_ticks
    finally:
        runtime.close()
    ticks, events = load_telemetry(telemetry)
    return {
        "committed_ticks": committed_ticks,
        "torque_enabled_after_close": bus.torque_enabled,
        "ticks": ticks,
        "events": events,
    }


class _FailFirstPolicyWriteBus(MockSTS3215Bus):
    latest: _FailFirstPolicyWriteBus | None = None

    def __init__(self) -> None:
        super().__init__()
        self.write_count = 0
        self.disable_count = 0
        type(self).latest = self

    def write_positions(self, positions_rad: Any) -> ErrorCode:
        self.write_count += 1
        if self.write_count == 3:
            return ErrorCode.IO
        return super().write_positions(positions_rad)

    def disable_torque(self) -> ErrorCode:
        self.disable_count += 1
        return super().disable_torque()


def run_failure_injection(
    args: argparse.Namespace,
    *,
    config: Path,
    telemetry: Path,
) -> dict[str, Any]:
    original = runtime_module.MockSTS3215Bus
    runtime_module.MockSTS3215Bus = _FailFirstPolicyWriteBus
    runtime: Runtime | None = None
    error: BaseException | None = None
    host = None
    try:
        runtime = Runtime(
            runtime_args(
                args,
                config=config,
                telemetry=telemetry,
                max_ticks=2,
                max_active_ticks=1,
            )
        )
        host = runtime.t247_host
        try:
            runtime.run()
        except SafetyError as exc:
            error = exc
            runtime.halt_reason = f"SafetyError: {exc}"
    finally:
        if runtime is not None:
            runtime.close()
        runtime_module.MockSTS3215Bus = original
    bus = _FailFirstPolicyWriteBus.latest
    if host is None or bus is None:
        raise RuntimeError("failure-injection runtime did not initialize")
    ticks, events = load_telemetry(telemetry)
    return {
        "error_type": type(error).__name__ if error is not None else None,
        "error": str(error) if error is not None else None,
        "committed_ticks": host.committed_ticks,
        "pending": host.pending,
        "faulted": host.faulted,
        "write_count": bus.write_count,
        "disable_count": bus.disable_count,
        "torque_enabled_after_close": bus.torque_enabled,
        "ticks": ticks,
        "events": events,
    }


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if sha256(PREREGISTRATION) != PREREGISTRATION_SHA256:
        raise RuntimeError("runtime wiring preregistration SHA-256 differs")
    tracked_status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        text=True,
    ).strip()
    if tracked_status:
        raise RuntimeError("runtime wiring verifier requires a clean tracked worktree")

    inputs = output.parent / "inputs"
    config_unpaused = inputs / "duck_config.mock-unpaused.json"
    config_paused = inputs / "duck_config.mock-paused.json"
    write_config(config_unpaused, start_paused=False)
    write_config(config_paused, start_paused=True)
    success = run_success(
        args,
        config=config_unpaused,
        telemetry=output.parent / "success-control.jsonl",
    )
    paused = run_paused(
        args,
        config=config_paused,
        telemetry=output.parent / "paused-control.jsonl",
    )
    failure = run_failure_injection(
        args,
        config=config_unpaused,
        telemetry=output.parent / "failed-write-control.jsonl",
    )

    schema = json.loads(
        (ROOT / "schemas" / "control_tick.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)
    for tick in (*success["ticks"], *paused["ticks"], *failure["ticks"]):
        validator.validate(tick)

    success_ticks = success["ticks"]
    paused_ticks = paused["ticks"]
    locomotion_ticks = success_ticks[CALIBRATION_TICKS:]
    start_event = success["events"][0]
    halt_event = success["events"][-1]
    policy_details = start_event["details"]["policy"]
    expected_assets = {
        "policy": (args.policy, T247_POLICY_SHA256),
        "calibrator": (args.calibrator, T247_CALIBRATOR_SHA256),
        "command_manifest": (args.command_manifest, T247_COMMAND_MANIFEST_SHA256),
        "context_router": (
            args.context_root / "policy.context-router.onnx",
            T247_CONTEXT_ROUTER_SHA256,
        ),
        "p30_fit": (args.p30_fit, T247_P30_SHA256),
        "reference_table": (args.reference_table, T247_REFERENCE_SHA256),
    }
    asset_receipts = {
        name: receipt(path) for name, (path, _) in expected_assets.items()
    }
    asset_checks = {
        name: asset_receipts[name]["sha256"] == expected
        for name, (_, expected) in expected_assets.items()
    }
    checks = {
        "preregistration_exact": True,
        "tracked_worktree_clean_at_execution": not bool(tracked_status),
        "all_selected_asset_receipts_exact": all(asset_checks.values()),
        "runtime_start_contract_is_t247_115": (
            policy_details["contract"] == POLICY_CONTRACT_T247
            and policy_details["calibrator_inputs"]["obs"] == [1, 115]
            and policy_details["locomotion_inputs"]["obs"] == [1, 115]
        ),
        "all_30_route_assets_verified_before_run": (
            policy_details["context_routes"] == 6
            and policy_details["exact_command_routes"] == 24
        ),
        "mock_backend_only": (
            start_event["details"]["bus"]["backend"] == "mock"
            and start_event["details"]["bus"]["device"].startswith("mock://")
            and start_event["details"]["sensors"]["imu"]["backend"] == "mock"
        ),
        "exactly_258_valid_policy_ticks": (
            len(success_ticks) == ACTIVE_TICKS
            and all(tick["observation_valid"] for tick in success_ticks)
        ),
        "every_valid_t247_observation_has_115_fields": all(
            len(tick["observation"]) == 115 for tick in success_ticks
        ),
        "exactly_250_calibration_then_8_locomotion_ticks": (
            all(
                tick["policy_host"]["stage"] == "calibration"
                for tick in success_ticks[:CALIBRATION_TICKS]
            )
            and len(locomotion_ticks) == 8
            and all(
                tick["policy_host"]["stage"] == "locomotion"
                for tick in locomotion_ticks
            )
        ),
        "valid_context_route_and_x080_after_handoff": all(
            tick["policy_host"]["selected_context_route"] in ROUTE_NAMES
            and tick["policy_host"]["selected_command_route"] == "x080"
            for tick in locomotion_ticks
        ),
        "host_commits_equal_successful_policy_writes": (
            success["before_close"]["committed_ticks"] == ACTIVE_TICKS
            and success["before_close"]["confirmed_calibration_ticks"]
            == CALIBRATION_TICKS
            and success["before_close"]["handoff_complete"]
            and not success["before_close"]["faulted"]
        ),
        "all_successful_writes_and_reads_ok": all(
            tick["bus"]["write_status"] == "ok"
            and all(status == "ok" for status in tick["bus"]["per_servo_status"])
            for tick in success_ticks
        ),
        "maximum_rate_excess_is_zero": not any(
            any(tick["over_3_75_rad_s"]) for tick in success_ticks
        ),
        "success_exit_torque_off_and_no_drops": (
            not success["before_close"]["torque_enabled_after_run"]
            and not success["torque_enabled_after_close"]
            and halt_event["torque_off_attempted"]
            and halt_event["torque_off_status"] == "ok"
            and halt_event["telemetry_records_dropped"] == 0
        ),
        "start_paused_holds_without_policy_progress": (
            len(paused_ticks) == 3
            and paused["committed_ticks"] == 0
            and all(tick["paused"] for tick in paused_ticks)
            and all(not tick["observation_valid"] for tick in paused_ticks)
            and all("policy_host" not in tick for tick in paused_ticks)
            and not paused["torque_enabled_after_close"]
        ),
        "failed_write_does_not_commit_recurrent_state": (
            failure["error_type"] == "SafetyError"
            and failure["committed_ticks"] == 0
            and not failure["pending"]
            and failure["faulted"]
            and failure["write_count"] == 3
        ),
        "failed_write_fault_path_torques_off": (
            failure["disable_count"] >= 2
            and not failure["torque_enabled_after_close"]
            and failure["events"][-1]["event"] == "runtime_halt"
            and failure["events"][-1]["torque_off_status"] == "ok"
        ),
        "all_control_records_validate_against_schema": True,
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    production_sources = [
        ROOT / "src" / "open_duck_x5" / "runtime.py",
        ROOT / "src" / "open_duck_x5" / "telemetry.py",
        ROOT / "src" / "open_duck_x5" / "t247_command_routes.py",
        ROOT / "schemas" / "control_tick.schema.json",
        Path(__file__).resolve(),
    ]
    result: dict[str, Any] = {
        "schema_version": "open_duck_x5.t247_runtime_opt_in_wiring_result.v1",
        "status": (
            "PASS_T247_RUNTIME_OPT_IN_WIRING"
            if not failed
            else "HOLD_T247_RUNTIME_OPT_IN_WIRING"
        ),
        "date": "2026-08-01",
        "git": {
            "commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "tracked_clean": not bool(tracked_status),
        },
        "preregistration": receipt(PREREGISTRATION),
        "production_sources": {
            str(path.relative_to(ROOT)).replace("\\", "/"): receipt(path)
            for path in production_sources
        },
        "asset_receipts": asset_receipts,
        "success_run": {
            "active_ticks": len(success_ticks),
            "calibration_ticks": CALIBRATION_TICKS,
            "locomotion_ticks": len(locomotion_ticks),
            "committed_ticks": success["before_close"]["committed_ticks"],
            "selected_context_route": success["before_close"][
                "selected_context_route"
            ],
            "selected_command_route": success["before_close"][
                "selected_command_route"
            ],
            "route_switches": success["before_close"]["route_switches"],
            "fallback_ticks": success["before_close"]["fallback_ticks"],
            "telemetry": receipt(output.parent / "success-control.jsonl"),
        },
        "paused_run": {
            "ticks": len(paused_ticks),
            "committed_ticks": paused["committed_ticks"],
            "telemetry": receipt(output.parent / "paused-control.jsonl"),
        },
        "failed_write_run": {
            key: value
            for key, value in failure.items()
            if key not in {"ticks", "events"}
        }
        | {"telemetry": receipt(output.parent / "failed-write-control.jsonl")},
        "checks": checks,
        "checks_passed": sum(bool(value) for value in checks.values()),
        "checks_total": len(checks),
        "failed_checks": failed,
        "decision": (
            "EARN_GATE5_READINESS_AUDIT_AND_COMMAND_PACKET"
            if not failed
            else "HOLD_RUNTIME_INTEGRATION_AND_FIX_ONLY_THE_DEFECT"
        ),
        "authority": {
            "offline_cpu_only": True,
            "mock_bus_only": True,
            "robot_access": False,
            "serial_bus": False,
            "servo_reads_or_writes": False,
            "sensors": False,
            "torque": False,
            "motion": False,
            "policy_deployed": False,
            "gate5": False,
        },
    }
    result["result_sha256"] = canonical_sha256(result)
    output.write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(result, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
