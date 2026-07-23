from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


class ComparisonError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_summary(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ComparisonError(f"invalid timing summary JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ComparisonError("timing summary must be a JSON object")
    if value.get("schema_version") != "open_duck_x5.timing_summary.v2":
        raise ComparisonError("input is not a timing summary v2 artifact")
    backend = value.get("backend")
    if backend not in ("mock", "serial"):
        raise ComparisonError("timing summary backend is invalid")
    if value.get("run_status") != "COMPLETE":
        raise ComparisonError("cannot compare a halted or incomplete timing run")
    if value.get("ticks") != value.get("ticks_requested"):
        raise ComparisonError("timing summary did not complete its requested duration")
    jsonl_sha256 = value.get("jsonl_sha256")
    if not isinstance(jsonl_sha256, str) or len(jsonl_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in jsonl_sha256
    ):
        raise ComparisonError("timing summary is not bound to a raw JSONL SHA-256")
    gates = value.get("gates")
    if not isinstance(gates, dict):
        raise ComparisonError("timing summary gates are missing")
    for gate in ("complete_record_stream", "torque_off_confirmed"):
        if gates.get(gate) is not True:
            raise ComparisonError(f"timing summary gate {gate} is not proven")
    environment = value.get("environment")
    if not isinstance(environment, dict):
        raise ComparisonError("timing summary environment is missing")
    if backend == "mock":
        if (
            value.get("informational_only") is not True
            or value.get("review_status") != "INFORMATIONAL_ONLY"
            or value.get("hardware_gate_status") != "NOT_APPLICABLE_MOCK"
        ):
            raise ComparisonError("mock timing provenance is inconsistent")
    else:
        if (
            value.get("informational_only") is not False
            or value.get("review_status") != "REVIEW_REQUIRED"
            or value.get("hardware_gate_status") != "REVIEW_REQUIRED"
            or environment.get("hardware_authorized") is not True
            or environment.get("suspended_or_benched") is not True
            or not isinstance(environment.get("realtime"), dict)
        ):
            raise ComparisonError("serial timing provenance is incomplete")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a baseline-vs-new timing comparison")
    parser.add_argument("--new-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    summary_path = args.new_summary.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    if summary_path == output_path:
        parser.error("--new-summary and --output must be different files")
    try:
        new = _validated_summary(summary_path)
    except (ComparisonError, OSError) as exc:
        parser.error(str(exc))
    result = {
        "schema_version": "open_duck_x5.baseline_comparison.v1",
        "status": (
            "INFORMATIONAL_MOCK"
            if new.get("informational_only")
            else "REVIEW_REQUIRED"
        ),
        "new_summary_source": {
            "path": args.new_summary.as_posix(),
            "sha256": _sha256(summary_path),
        },
        "legacy": {
            "x0_read_failure_percent": 1.07,
            "x008_read_failure_percent": 2.68,
            "tick_max_ms": 26.0,
            "read_bursts_observed": True,
            "phase_1_full_timing_artifact": None,
        },
        "new": new,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_bytes = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output_path.write_bytes(output_bytes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
