"""Independent validator for no-servo winner-v2 X5 CPU preflight evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

from .winner_v2_cpu_preflight import (
    COMMANDS,
    MAX_TRANSACTION_MAX_MS,
    MAX_TRANSACTION_P99_9_MS,
    MAX_TRANSACTION_P99_MS,
    MINIMUM_TICKS_PER_COMMAND,
    SAMPLE_SCHEMA_VERSION,
    SCHEMA_VERSION,
)

REVIEW_SCHEMA_VERSION = "open_duck_x5.winner_v2_cpu_preflight_review.v1"
RUNNER_SCHEMA_VERSION = "open_duck_x5.winner_v2_cpu_preflight_runner.v1"
EXPECTED_SOURCE_COMMIT = "de870de8cde29a3e645c73c6f6cdeaa48cd8ea46"
EXPECTED_SOURCE_ARCHIVE_SHA256 = (
    "9caefc209dfb85bd1ca28d998e37bcf0832c361468cec0d8d46c97cf6d7c9c17"
)
EXPECTED_PREFLIGHT_MODULE_SHA256 = (
    "473e4b9ff34e2d6d03350a59d8fc2b19749ffb29cba8023bd7dd8516e3a7f9b6"
)
EXPECTED_RUNNER_SHA256 = (
    "3fb3cffa8bf02481c584482dae1196a5412ec79a17c533d37a55792f6c10483d"
)
EXPECTED_CONFIG_SHA256 = (
    "131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b"
)
EXPECTED_HANDOFF_MANIFEST_SHA256 = (
    "d771d188218152c782c7d688440e2dd2083b47fd9b883749123f89226c6827c5"
)
EXPECTED_SELECTED_ONNX_SHA256 = (
    "99d3afce0dfac127816c6327665c35b3c403e005f25cd0a505dfcb37f01304de"
)
EXPECTED_EVIDENCE_FILES = {
    "governor-after.txt",
    "governor-before.txt",
    "governor-during.txt",
    "preflight-stderr.txt",
    "preflight-stdout.txt",
    "runner-metadata.json",
    "source-archive-sha256.txt",
    "source-commit.txt",
    "summary.json",
    "timing.jsonl",
}
EXPECTED_GATE_KEYS = {
    "formal_2400_tick_verification_passed",
    "exact_command_population",
    "minimum_10000_ticks_per_command",
    "transaction_timing",
    "linux",
    "affinity_exact_cpu7",
    "sched_fifo_80",
    "cpu7_isolated",
    "performance_governor",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SUMMARY_STAT_KEYS = {"min", "mean", "p95", "p99", "p99_9", "max"}
_SAMPLE_KEYS = {
    "schema_version",
    "command_x",
    "tick",
    "stage_ms",
    "commit_ms",
    "transaction_ms",
}


class WinnerV2CpuPreflightReviewError(RuntimeError):
    """The no-servo X5 CPU evidence is incomplete or inconsistent."""


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
        raise WinnerV2CpuPreflightReviewError(f"could not read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise WinnerV2CpuPreflightReviewError(f"{label} must be a JSON object")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise WinnerV2CpuPreflightReviewError(
            f"{label} keys differ: missing={missing}, extra={extra}"
        )


def _sha256_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise WinnerV2CpuPreflightReviewError(f"{label} must be a lowercase SHA-256")
    return value


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WinnerV2CpuPreflightReviewError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise WinnerV2CpuPreflightReviewError(f"{label} must be finite and nonnegative")
    return number


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


def _require_statistics_equal(
    supplied: Any, reproduced: dict[str, float], label: str
) -> None:
    if not isinstance(supplied, dict):
        raise WinnerV2CpuPreflightReviewError(f"{label} must be an object")
    _exact_keys(supplied, _SUMMARY_STAT_KEYS, label)
    for name, expected in reproduced.items():
        actual = _finite(supplied[name], f"{label}.{name}")
        if abs(actual - expected) > 1e-12:
            raise WinnerV2CpuPreflightReviewError(
                f"{label}.{name} differs from timing JSONL: {actual} != {expected}"
            )


def _load_samples(path: Path) -> dict[float, dict[str, np.ndarray]]:
    values: dict[float, dict[str, list[int]]] = {
        command: {"stage": [], "commit": [], "transaction": []}
        for command in COMMANDS
    }
    expected_command_index = 0
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise WinnerV2CpuPreflightReviewError(
                        f"invalid timing JSONL at line {line_number}: {exc}"
                    ) from exc
                if not isinstance(record, dict):
                    raise WinnerV2CpuPreflightReviewError(
                        f"timing line {line_number} must be an object"
                    )
                _exact_keys(record, _SAMPLE_KEYS, f"timing line {line_number}")
                if record["schema_version"] != SAMPLE_SCHEMA_VERSION:
                    raise WinnerV2CpuPreflightReviewError(
                        f"timing line {line_number} schema is unsupported"
                    )
                command = float(record["command_x"])
                if command not in values:
                    raise WinnerV2CpuPreflightReviewError(
                        f"timing line {line_number} has unsupported command {command}"
                    )
                expected_command = COMMANDS[expected_command_index]
                if command != expected_command:
                    raise WinnerV2CpuPreflightReviewError(
                        f"timing command order changed at line {line_number}"
                    )
                command_values = values[command]
                tick = record["tick"]
                if isinstance(tick, bool) or not isinstance(tick, int):
                    raise WinnerV2CpuPreflightReviewError(
                        f"timing line {line_number} tick must be integer"
                    )
                if tick != len(command_values["transaction"]):
                    raise WinnerV2CpuPreflightReviewError(
                        f"non-contiguous timing tick for command {command}: {tick}"
                    )
                stage_ns = int(round(_finite(record["stage_ms"], "stage_ms") * 1e6))
                commit_ns = int(round(_finite(record["commit_ms"], "commit_ms") * 1e6))
                transaction_ns = int(
                    round(_finite(record["transaction_ms"], "transaction_ms") * 1e6)
                )
                if transaction_ns != stage_ns + commit_ns:
                    raise WinnerV2CpuPreflightReviewError(
                        f"timing line {line_number} transaction is not stage+commit"
                    )
                command_values["stage"].append(stage_ns)
                command_values["commit"].append(commit_ns)
                command_values["transaction"].append(transaction_ns)
                if (
                    expected_command_index == 0
                    and len(command_values["transaction"])
                    == MINIMUM_TICKS_PER_COMMAND
                ):
                    expected_command_index = 1
    except OSError as exc:
        raise WinnerV2CpuPreflightReviewError(f"could not read timing JSONL: {exc}") from exc

    converted: dict[float, dict[str, np.ndarray]] = {}
    for command in COMMANDS:
        command_values = values[command]
        if len(command_values["transaction"]) != MINIMUM_TICKS_PER_COMMAND:
            raise WinnerV2CpuPreflightReviewError(
                f"command {command} timing population is "
                f"{len(command_values['transaction'])}, expected {MINIMUM_TICKS_PER_COMMAND}"
            )
        converted[command] = {
            name: np.asarray(samples, dtype=np.int64)
            for name, samples in command_values.items()
        }
    return converted


def _parse_sha256sums(path: Path, root: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise WinnerV2CpuPreflightReviewError(f"could not read sha256sums: {exc}") from exc
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([^/\\]+)", line)
        if match is None:
            raise WinnerV2CpuPreflightReviewError(f"invalid sha256sums line: {line!r}")
        digest, name = match.groups()
        if name in records:
            raise WinnerV2CpuPreflightReviewError(f"duplicate sha256sums entry: {name}")
        records[name] = digest
    if set(records) != EXPECTED_EVIDENCE_FILES:
        raise WinnerV2CpuPreflightReviewError(
            "sha256sums population differs: "
            f"missing={sorted(EXPECTED_EVIDENCE_FILES - set(records))}, "
            f"extra={sorted(set(records) - EXPECTED_EVIDENCE_FILES)}"
        )
    for name, expected in records.items():
        actual = _sha256(root / name)
        if actual != expected:
            raise WinnerV2CpuPreflightReviewError(
                f"evidence SHA-256 mismatch for {name}: {actual} != {expected}"
            )
    return records


def validate_preflight_evidence(
    *,
    evidence_dir: Path,
    expected_envelope_sha256: str,
) -> dict[str, Any]:
    root = evidence_dir.resolve()
    expected_envelope = _sha256_string(
        expected_envelope_sha256, "expected envelope SHA-256"
    )
    actual_files = {path.name for path in root.iterdir() if path.is_file()}
    if actual_files != EXPECTED_EVIDENCE_FILES | {"sha256sums.txt"}:
        raise WinnerV2CpuPreflightReviewError(
            "evidence directory population differs: "
            f"missing={sorted((EXPECTED_EVIDENCE_FILES | {'sha256sums.txt'}) - actual_files)}, "
            f"extra={sorted(actual_files - (EXPECTED_EVIDENCE_FILES | {'sha256sums.txt'}))}"
        )
    _parse_sha256sums(root / "sha256sums.txt", root)
    summary = _load_object(root / "summary.json", "preflight summary")
    metadata_value = _load_object(root / "runner-metadata.json", "runner metadata")
    samples = _load_samples(root / "timing.jsonl")

    if summary.get("schema_version") != SCHEMA_VERSION:
        raise WinnerV2CpuPreflightReviewError("preflight summary schema is unsupported")
    if summary.get("status") != "PASS_X5_CPU_ONLY_PREFLIGHT_CANDIDATE":
        raise WinnerV2CpuPreflightReviewError("preflight summary is not a pass candidate")
    if summary.get("review_status") != "REVIEW_REQUIRED":
        raise WinnerV2CpuPreflightReviewError("preflight summary review status changed")
    if summary.get("no_servo_access") is not True:
        raise WinnerV2CpuPreflightReviewError("preflight summary does not assert no-servo access")
    authority = summary.get("authority")
    expected_authority = {
        "robot_clearance": False,
        "gate5": False,
        "runtime_deployment": False,
        "motion": False,
        "serial": False,
        "torque": False,
    }
    if authority != expected_authority:
        raise WinnerV2CpuPreflightReviewError("preflight summary authority is not all false")

    inputs = summary.get("inputs")
    if not isinstance(inputs, dict):
        raise WinnerV2CpuPreflightReviewError("preflight summary inputs are missing")
    if inputs.get("handoff_manifest_sha256") != EXPECTED_HANDOFF_MANIFEST_SHA256:
        raise WinnerV2CpuPreflightReviewError("handoff manifest identity differs")
    if inputs.get("selected_onnx_sha256") != EXPECTED_SELECTED_ONNX_SHA256:
        raise WinnerV2CpuPreflightReviewError("selected ONNX identity differs")
    envelope = inputs.get("policy_envelope")
    config = inputs.get("config")
    if not isinstance(envelope, dict) or envelope.get("sha256") != expected_envelope:
        raise WinnerV2CpuPreflightReviewError("policy envelope identity differs")
    if not isinstance(config, dict) or config.get("sha256") != EXPECTED_CONFIG_SHA256:
        raise WinnerV2CpuPreflightReviewError("config identity differs")
    sample_record = summary.get("samples")
    if not isinstance(sample_record, dict):
        raise WinnerV2CpuPreflightReviewError("preflight summary sample record is missing")
    if sample_record.get("sha256") != _sha256(root / "timing.jsonl"):
        raise WinnerV2CpuPreflightReviewError("summary timing JSONL identity differs")
    if sample_record.get("records") != len(COMMANDS) * MINIMUM_TICKS_PER_COMMAND:
        raise WinnerV2CpuPreflightReviewError("summary timing record count differs")

    thresholds = summary.get("thresholds_ms")
    if thresholds != {
        "transaction_p99_max": MAX_TRANSACTION_P99_MS,
        "transaction_p99_9_max": MAX_TRANSACTION_P99_9_MS,
        "transaction_max": MAX_TRANSACTION_MAX_MS,
    }:
        raise WinnerV2CpuPreflightReviewError("preflight thresholds changed")
    gates = summary.get("gates")
    if not isinstance(gates, dict):
        raise WinnerV2CpuPreflightReviewError("preflight gates are missing")
    _exact_keys(gates, EXPECTED_GATE_KEYS, "preflight gates")
    if not all(value is True for value in gates.values()):
        raise WinnerV2CpuPreflightReviewError("one or more preflight gates failed")

    timing_cells = summary.get("timing_cells")
    if not isinstance(timing_cells, list) or len(timing_cells) != len(COMMANDS):
        raise WinnerV2CpuPreflightReviewError("preflight timing cells differ")
    reproduced_cells: list[dict[str, Any]] = []
    for index, command in enumerate(COMMANDS):
        cell = timing_cells[index]
        if not isinstance(cell, dict):
            raise WinnerV2CpuPreflightReviewError("preflight timing cell must be an object")
        if cell.get("command_x") != command or cell.get("ticks") != MINIMUM_TICKS_PER_COMMAND:
            raise WinnerV2CpuPreflightReviewError(f"timing cell {index} population differs")
        arrays = samples[command]
        stage_stats = _statistics(arrays["stage"])
        commit_stats = _statistics(arrays["commit"])
        transaction_stats = _statistics(arrays["transaction"])
        _require_statistics_equal(cell.get("stage_ms"), stage_stats, f"cell[{index}].stage")
        _require_statistics_equal(cell.get("commit_ms"), commit_stats, f"cell[{index}].commit")
        _require_statistics_equal(
            cell.get("transaction_ms"), transaction_stats, f"cell[{index}].transaction"
        )
        timing_pass = bool(
            transaction_stats["p99"] <= MAX_TRANSACTION_P99_MS
            and transaction_stats["p99_9"] <= MAX_TRANSACTION_P99_9_MS
            and transaction_stats["max"] <= MAX_TRANSACTION_MAX_MS
        )
        if cell.get("timing_gate_passed") is not timing_pass or not timing_pass:
            raise WinnerV2CpuPreflightReviewError(f"timing cell {index} does not pass")
        reproduced_cells.append(
            {"command_x": command, "ticks": MINIMUM_TICKS_PER_COMMAND, **transaction_stats}
        )

    if metadata_value.get("schema_version") != RUNNER_SCHEMA_VERSION:
        raise WinnerV2CpuPreflightReviewError("runner metadata schema is unsupported")
    expected_metadata = {
        "source_commit": EXPECTED_SOURCE_COMMIT,
        "source_archive_sha256": EXPECTED_SOURCE_ARCHIVE_SHA256,
        "preflight_module_sha256": EXPECTED_PREFLIGHT_MODULE_SHA256,
        "runner_sha256": EXPECTED_RUNNER_SHA256,
        "policy_envelope_sha256": expected_envelope,
        "config_sha256": EXPECTED_CONFIG_SHA256,
        "handoff_manifest_sha256": EXPECTED_HANDOFF_MANIFEST_SHA256,
        "selected_onnx_sha256": EXPECTED_SELECTED_ONNX_SHA256,
        "ticks_per_command": MINIMUM_TICKS_PER_COMMAND,
        "commands": list(COMMANDS),
        "rt_cpu": 7,
        "rt_priority": 80,
        "preflight_exit_status": 0,
        "governor_restore_status": 0,
        "review_status": "REVIEW_REQUIRED",
        "no_servo_access": True,
        "robot_clearance": False,
        "gate5": False,
        "motion": False,
        "torque": False,
    }
    metadata_without_schema = dict(metadata_value)
    metadata_without_schema.pop("schema_version", None)
    if metadata_without_schema != expected_metadata:
        raise WinnerV2CpuPreflightReviewError("runner metadata differs from preregistration")

    before = (root / "governor-before.txt").read_text(encoding="utf-8").strip()
    during = (root / "governor-during.txt").read_text(encoding="utf-8").strip()
    after = (root / "governor-after.txt").read_text(encoding="utf-8").strip()
    if not before or during != "performance" or after != before:
        raise WinnerV2CpuPreflightReviewError("governor provenance/restore differs")
    if (root / "source-commit.txt").read_text(encoding="utf-8").strip() != EXPECTED_SOURCE_COMMIT:
        raise WinnerV2CpuPreflightReviewError("source-commit evidence differs")
    archive_record = (root / "source-archive-sha256.txt").read_text(
        encoding="utf-8"
    ).strip()
    if archive_record != f"{EXPECTED_SOURCE_ARCHIVE_SHA256}  source.tar.gz":
        raise WinnerV2CpuPreflightReviewError("source-archive evidence differs")

    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "status": "PASS_X5_CPU_PREFLIGHT_EVIDENCE_VALIDATED",
        "review_status": "REVIEW_REQUIRED",
        "source": {
            "directory": str(root),
            "summary_sha256": _sha256(root / "summary.json"),
            "timing_sha256": _sha256(root / "timing.jsonl"),
            "runner_metadata_sha256": _sha256(root / "runner-metadata.json"),
            "sha256sums_sha256": _sha256(root / "sha256sums.txt"),
        },
        "recomputed_transaction_ms": reproduced_cells,
        "authority": expected_authority,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Independently validate winner-v2 no-servo X5 CPU evidence"
    )
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--expected-envelope-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = args.output.resolve()
    evidence = args.evidence_dir.resolve()
    if output == evidence or evidence in output.parents:
        print("result=FAIL reason=review output must be outside the immutable evidence directory")
        return 2
    output.unlink(missing_ok=True)
    try:
        result = validate_preflight_evidence(
            evidence_dir=evidence,
            expected_envelope_sha256=args.expected_envelope_sha256,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, ValueError, WinnerV2CpuPreflightReviewError) as exc:
        output.unlink(missing_ok=True)
        print(f"result=FAIL reason={exc}")
        return 2
    print(f"result={result['status']} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
