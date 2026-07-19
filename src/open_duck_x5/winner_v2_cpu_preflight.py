"""No-servo X5 CPU timing preflight for the frozen winner-v2 transaction.

This module deliberately imports no bus, serial, GPIO, I2C, controller, or
hardware-authorization code.  It verifies the complete handoff first and then
times the in-memory 115-D assembly -> stateful ONNX -> target/P30 transaction.
No sleep or file I/O occurs inside a measured transaction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import time
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

import numpy as np

from .config import DuckConfig
from .configuration_support import (
    ConfigurationSupportError,
    validate_supported_configuration_envelope_data,
)
from .constants import ACTION_DIM, CONTROL_PERIOD_NS, HOME_RAD
from .winner_v2 import (
    WINNER_V2_CONTRACT_ID,
    WINNER_V2_SELECTED_POLICY_SHA256,
    P30BridgeObserver,
    ProjectedReferenceTable,
    WinnerV2OnnxPolicy,
    WinnerV2TickTransaction,
)

SCHEMA_VERSION = "open_duck_x5.winner_v2_cpu_preflight.v1"
SAMPLE_SCHEMA_VERSION = "open_duck_x5.winner_v2_cpu_preflight_tick.v1"
COMMANDS = (0.0, 0.08)
GOLDEN_TICKS = 600
MINIMUM_TICKS_PER_COMMAND = 10_000
DEFAULT_TICKS_PER_COMMAND = 10_000
MAX_TRANSACTION_P99_MS = 5.0
MAX_TRANSACTION_P99_9_MS = 7.0
MAX_TRANSACTION_MAX_MS = 10.0
EXPECTED_RT_CPU = 7
EXPECTED_RT_PRIORITY = 80
_SHA256_LENGTH = 64


class WinnerV2CpuPreflightError(RuntimeError):
    """The no-servo CPU preflight contract was violated."""


@dataclass(frozen=True, slots=True)
class GoldenInputs:
    gyro_rad_s: np.ndarray
    acceleration_m_s2: np.ndarray
    commands: np.ndarray
    positions_rad: np.ndarray
    velocities_rad_s: np.ndarray
    foot_contacts: np.ndarray


@dataclass(frozen=True, slots=True)
class TimingCell:
    command_x: float
    stage_ns: np.ndarray
    commit_ns: np.ndarray
    transaction_ns: np.ndarray


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha256(value: str, label: str) -> str:
    if len(value) != _SHA256_LENGTH or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise WinnerV2CpuPreflightError(f"{label} must be a lowercase SHA-256")
    return value


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WinnerV2CpuPreflightError(f"could not read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise WinnerV2CpuPreflightError(f"{label} must be a JSON object")
    return value


def validate_preflight_inputs(
    *,
    envelope_path: Path,
    expected_envelope_sha256: str,
    config_path: Path,
    expected_config_sha256: str,
) -> tuple[dict[str, Any], DuckConfig]:
    """Validate policy/config identities before loading any ONNX asset."""
    envelope_path = envelope_path.resolve()
    config_path = config_path.resolve()
    expected_envelope = _require_sha256(
        expected_envelope_sha256, "expected envelope SHA-256"
    )
    expected_config = _require_sha256(expected_config_sha256, "expected config SHA-256")
    if _sha256(envelope_path) != expected_envelope:
        raise WinnerV2CpuPreflightError("policy envelope SHA-256 differs from preregistration")
    envelope = _load_json_object(envelope_path, "supported-configuration envelope")
    try:
        validate_supported_configuration_envelope_data(envelope)
    except ConfigurationSupportError as exc:
        raise WinnerV2CpuPreflightError(f"policy envelope is invalid: {exc}") from exc
    policy = envelope.get("policy", {})
    if not isinstance(policy, dict):
        raise WinnerV2CpuPreflightError("policy envelope policy entry must be an object")
    if policy.get("onnx_sha256") != WINNER_V2_SELECTED_POLICY_SHA256:
        raise WinnerV2CpuPreflightError(
            "policy envelope does not select the runtime's frozen winner-v2 ONNX"
        )
    if policy.get("contract_id") != WINNER_V2_CONTRACT_ID:
        raise WinnerV2CpuPreflightError("policy envelope contract_id is not winner-v2")
    if _sha256(config_path) != expected_config:
        raise WinnerV2CpuPreflightError("duck_config.json SHA-256 differs from preregistration")
    config = DuckConfig.load(config_path)
    if not config.start_paused:
        raise WinnerV2CpuPreflightError("winner-v2 preflight requires start_paused=true")
    if config.phase_frequency_factor_offset != 0.0:
        raise WinnerV2CpuPreflightError(
            "winner-v2 preflight requires phase_frequency_factor_offset=0.0"
        )
    return envelope, config


def run_formal_verification(
    handoff_root: Path, *, runtime_root: Path
) -> dict[str, object]:
    """Load the frozen verifier only after no-servo input identities pass."""
    from .winner_v2_verifier import verify_handoff  # noqa: PLC0415

    return verify_handoff(handoff_root, runtime_root=runtime_root)


def _load_golden_inputs(path: Path, expected_command_x: float) -> GoldenInputs:
    with np.load(path, allow_pickle=False) as pack:
        if pack["obs"].shape != (GOLDEN_TICKS, 115):
            raise WinnerV2CpuPreflightError(f"invalid golden observation shape: {path}")
        obs = np.asarray(pack["obs"], dtype=np.float32)
        command_x = np.asarray(pack["command_raw"], dtype=np.float32)
        if command_x.shape[0] != GOLDEN_TICKS or not bool(
            np.all(command_x[:, 0] == np.float32(expected_command_x))
        ):
            raise WinnerV2CpuPreflightError(
                f"golden pack command does not equal {expected_command_x}: {path}"
            )
        return GoldenInputs(
            gyro_rad_s=np.asarray(obs[:, 0:3], dtype=np.float64).copy(),
            acceleration_m_s2=np.asarray(obs[:, 3:6], dtype=np.float64).copy(),
            commands=np.asarray(obs[:, 6:13], dtype=np.float64).copy(),
            positions_rad=(
                HOME_RAD[np.newaxis, :] + np.asarray(obs[:, 13:27], dtype=np.float64)
            ),
            velocities_rad_s=np.asarray(obs[:, 27:41], dtype=np.float64).copy() / 0.05,
            foot_contacts=np.asarray(obs[:, 97:99], dtype=np.float64).copy(),
        )


def _transaction_factory(handoff_root: Path) -> WinnerV2TickTransaction:
    return WinnerV2TickTransaction(
        policy=WinnerV2OnnxPolicy(
            handoff_root / "policies" / "T2_EQUAL_512000.onnx",
            warmup_runs=100,
        ),
        observer=P30BridgeObserver(
            handoff_root / "observer" / "p30_actuator_fit.json"
        ),
        reference=ProjectedReferenceTable(
            handoff_root
            / "reference"
            / "ground_up_projected_reference_feature_table.npz"
        ),
    )


def benchmark_cell(
    *,
    command_x: float,
    inputs: GoldenInputs,
    soft_offsets_rad: np.ndarray,
    ticks: int,
    make_transaction: Callable[[], WinnerV2TickTransaction],
    clock_ns: Callable[[], int] = time.perf_counter_ns,
) -> TimingCell:
    if command_x not in COMMANDS:
        raise WinnerV2CpuPreflightError(f"unsupported preflight command: {command_x}")
    if ticks < 1:
        raise WinnerV2CpuPreflightError("ticks must be positive")
    if soft_offsets_rad.shape != (ACTION_DIM,) or not bool(
        np.isfinite(soft_offsets_rad).all()
    ):
        raise WinnerV2CpuPreflightError("soft offsets must be finite shape (14,)")
    stage_ns = np.empty(ticks, dtype=np.int64)
    commit_ns = np.empty(ticks, dtype=np.int64)
    transaction_ns = np.empty(ticks, dtype=np.int64)
    servo_stale = np.zeros(ACTION_DIM, dtype=np.bool_)

    completed = 0
    while completed < ticks:
        transaction = make_transaction()
        population = min(GOLDEN_TICKS, ticks - completed)
        for local_tick in range(population):
            started = clock_ns()
            transaction.stage_tick(
                tick_index=local_tick,
                logical_period_ns=CONTROL_PERIOD_NS,
                servo_sample_tick_index=local_tick,
                imu_sample_tick_index=local_tick,
                contacts_sample_tick_index=local_tick,
                gyro_rad_s=inputs.gyro_rad_s[local_tick],
                acceleration_m_s2=inputs.acceleration_m_s2[local_tick],
                commands=inputs.commands[local_tick],
                positions_rad=inputs.positions_rad[local_tick],
                velocities_rad_s=inputs.velocities_rad_s[local_tick],
                foot_contacts=inputs.foot_contacts[local_tick],
                servo_stale=servo_stale,
                imu_stale=False,
                contacts_stale=False,
                soft_offsets_rad=soft_offsets_rad,
            )
            staged = clock_ns()
            transaction.complete_send(write_succeeded=True)
            finished = clock_ns()
            index = completed + local_tick
            stage_ns[index] = staged - started
            commit_ns[index] = finished - staged
            transaction_ns[index] = finished - started
        completed += population
    return TimingCell(command_x, stage_ns, commit_ns, transaction_ns)


def _statistics(values_ns: np.ndarray) -> dict[str, float]:
    values_ms = values_ns.astype(np.float64) / 1e6
    return {
        "min": float(np.min(values_ms)),
        "mean": float(np.mean(values_ms)),
        "p95": float(np.percentile(values_ms, 95)),
        "p99": float(np.percentile(values_ms, 99)),
        "p99_9": float(np.percentile(values_ms, 99.9)),
        "max": float(np.max(values_ms)),
    }


def runtime_environment() -> dict[str, Any]:
    affinity: list[int] | None = None
    scheduler: int | None = None
    priority: int | None = None
    if hasattr(os, "sched_getaffinity"):
        affinity = sorted(os.sched_getaffinity(0))
    if hasattr(os, "sched_getscheduler") and hasattr(os, "sched_getparam"):
        scheduler = int(os.sched_getscheduler(0))
        priority = int(os.sched_getparam(0).sched_priority)
    governor_path = Path("/sys/devices/system/cpu/cpufreq/policy0/scaling_governor")
    isolated_path = Path("/sys/devices/system/cpu/isolated")
    return {
        "system": platform.system(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "onnxruntime": metadata.version("onnxruntime"),
        "affinity": affinity,
        "scheduler": scheduler,
        "sched_fifo_value": getattr(os, "SCHED_FIFO", None),
        "priority": priority,
        "governor": (
            governor_path.read_text(encoding="utf-8").strip()
            if governor_path.is_file()
            else None
        ),
        "isolated_cpus": (
            isolated_path.read_text(encoding="utf-8").strip()
            if isolated_path.is_file()
            else None
        ),
    }


def _parse_cpu_list(value: str) -> set[int]:
    members: set[int] = set()
    try:
        for raw_part in value.split(","):
            part = raw_part.strip()
            if not part:
                continue
            bounds = part.split("-")
            if len(bounds) == 1:
                members.add(int(bounds[0]))
            elif len(bounds) == 2:
                low, high = map(int, bounds)
                if low > high:
                    return set()
                members.update(range(low, high + 1))
            else:
                return set()
    except ValueError:
        return set()
    return members


def environment_gates(environment: dict[str, Any]) -> dict[str, bool]:
    isolated_members = _parse_cpu_list(str(environment.get("isolated_cpus") or ""))
    return {
        "linux": environment.get("system") == "Linux",
        "affinity_exact_cpu7": environment.get("affinity") == [EXPECTED_RT_CPU],
        "sched_fifo_80": (
            environment.get("scheduler") == environment.get("sched_fifo_value")
            and environment.get("priority") == EXPECTED_RT_PRIORITY
        ),
        "cpu7_isolated": EXPECTED_RT_CPU in isolated_members,
        "performance_governor": environment.get("governor") == "performance",
    }


def build_result(
    *,
    handoff_root: Path,
    envelope_path: Path,
    config_path: Path,
    formal_result: dict[str, Any],
    cells: list[TimingCell],
    environment: dict[str, Any],
) -> dict[str, Any]:
    timing_cells: list[dict[str, Any]] = []
    timing_pass = True
    population_pass = True
    for cell in cells:
        total = _statistics(cell.transaction_ns)
        cell_pass = bool(
            total["p99"] <= MAX_TRANSACTION_P99_MS
            and total["p99_9"] <= MAX_TRANSACTION_P99_9_MS
            and total["max"] <= MAX_TRANSACTION_MAX_MS
        )
        timing_pass = timing_pass and cell_pass
        population_pass = population_pass and len(cell.transaction_ns) >= MINIMUM_TICKS_PER_COMMAND
        timing_cells.append(
            {
                "command_x": cell.command_x,
                "ticks": len(cell.transaction_ns),
                "stage_ms": _statistics(cell.stage_ns),
                "commit_ms": _statistics(cell.commit_ns),
                "transaction_ms": total,
                "timing_gate_passed": cell_pass,
            }
        )
    system_gates = environment_gates(environment)
    formal_pass = str(formal_result.get("status", "")).startswith("PASS_")
    all_gates = {
        "formal_2400_tick_verification_passed": formal_pass,
        "exact_command_population": [cell.command_x for cell in cells] == list(COMMANDS),
        "minimum_10000_ticks_per_command": population_pass,
        "transaction_timing": timing_pass,
        **system_gates,
    }
    passed = all(all_gates.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "PASS_X5_CPU_ONLY_PREFLIGHT_CANDIDATE"
            if passed
            else "HOLD_X5_CPU_ONLY_PREFLIGHT"
        ),
        "review_status": "REVIEW_REQUIRED",
        "no_servo_access": True,
        "environment": environment,
        "inputs": {
            "handoff_root": str(handoff_root.resolve()),
            "handoff_manifest_sha256": formal_result.get("manifest_sha256"),
            "selected_onnx_sha256": WINNER_V2_SELECTED_POLICY_SHA256,
            "policy_envelope": {
                "path": str(envelope_path.resolve()),
                "sha256": _sha256(envelope_path.resolve()),
            },
            "config": {
                "path": str(config_path.resolve()),
                "sha256": _sha256(config_path.resolve()),
            },
        },
        "population": {
            "commands": list(COMMANDS),
            "minimum_ticks_per_command": MINIMUM_TICKS_PER_COMMAND,
            "golden_episode_ticks": GOLDEN_TICKS,
        },
        "thresholds_ms": {
            "transaction_p99_max": MAX_TRANSACTION_P99_MS,
            "transaction_p99_9_max": MAX_TRANSACTION_P99_9_MS,
            "transaction_max": MAX_TRANSACTION_MAX_MS,
        },
        "timing_cells": timing_cells,
        "gates": all_gates,
        "authority": {
            "robot_clearance": False,
            "gate5": False,
            "runtime_deployment": False,
            "motion": False,
            "serial": False,
            "torque": False,
        },
    }


def write_samples(path: Path, cells: list[TimingCell]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for cell in cells:
            for tick, (stage, commit, total) in enumerate(
                zip(cell.stage_ns, cell.commit_ns, cell.transaction_ns, strict=True)
            ):
                record = {
                    "schema_version": SAMPLE_SCHEMA_VERSION,
                    "command_x": cell.command_x,
                    "tick": tick,
                    "stage_ms": int(stage) / 1e6,
                    "commit_ms": int(commit) / 1e6,
                    "transaction_ms": int(total) / 1e6,
                }
                handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the winner-v2 CPU-only timing preflight without servo access"
    )
    parser.add_argument("--handoff-root", type=Path, required=True)
    parser.add_argument("--envelope", type=Path, required=True)
    parser.add_argument("--expected-envelope-sha256", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--expected-config-sha256", required=True)
    parser.add_argument(
        "--ticks-per-command", type=int, default=DEFAULT_TICKS_PER_COMMAND
    )
    parser.add_argument("--samples-output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    inputs = {
        args.handoff_root.resolve(),
        args.envelope.resolve(),
        args.config.resolve(),
    }
    samples_output = args.samples_output.resolve()
    summary_output = args.summary_output.resolve()
    if samples_output in inputs or summary_output in inputs or samples_output == summary_output:
        print("result=FAIL reason=output paths must be unique and must not overwrite inputs")
        return 2
    for output in (samples_output, summary_output):
        output.unlink(missing_ok=True)
    try:
        _envelope, config = validate_preflight_inputs(
            envelope_path=args.envelope,
            expected_envelope_sha256=args.expected_envelope_sha256,
            config_path=args.config,
            expected_config_sha256=args.expected_config_sha256,
        )
        formal_result = run_formal_verification(
            args.handoff_root.resolve(), runtime_root=Path.cwd()
        )
        if not str(formal_result.get("status", "")).startswith("PASS_"):
            raise WinnerV2CpuPreflightError("formal 2,400-tick verification did not pass")
        cells: list[TimingCell] = []
        for command_x in COMMANDS:
            pack_path = (
                args.handoff_root
                / "golden"
                / f"T2_EQUAL_512000_x{command_x:.3f}.npz"
            )
            golden = _load_golden_inputs(pack_path, command_x)
            cells.append(
                benchmark_cell(
                    command_x=command_x,
                    inputs=golden,
                    soft_offsets_rad=config.offsets_array,
                    ticks=args.ticks_per_command,
                    make_transaction=lambda: _transaction_factory(
                        args.handoff_root.resolve()
                    ),
                )
            )
        environment = runtime_environment()
        result = build_result(
            handoff_root=args.handoff_root,
            envelope_path=args.envelope,
            config_path=args.config,
            formal_result=formal_result,
            cells=cells,
            environment=environment,
        )
        write_samples(samples_output, cells)
        result["samples"] = {
            "path": str(samples_output),
            "sha256": _sha256(samples_output),
            "records": sum(len(cell.transaction_ns) for cell in cells),
        }
        summary_output.parent.mkdir(parents=True, exist_ok=True)
        summary_output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except (OSError, ValueError, RuntimeError, WinnerV2CpuPreflightError) as exc:
        for output in (samples_output, summary_output):
            output.unlink(missing_ok=True)
        print(f"result=FAIL reason={exc}")
        return 2
    print(
        f"result={result['status']} records={result['samples']['records']} "
        f"summary={summary_output}"
    )
    return 0 if result["status"].startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
