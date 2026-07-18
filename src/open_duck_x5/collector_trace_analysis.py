from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

TRACE_SCHEMA_V1 = "open_duck_x5.transaction_trace.v1"
TIMING_SCHEMA_V2 = "open_duck_x5.timing_tick.v2"
ANALYSIS_SCHEMA = "open_duck_x5.collector_trace_analysis.v1"
OLD_RESPONSE_TIMEOUT_US = 4_000.0

PHASE_FIELDS = (
    "bus_total",
    "sync_write_call",
    "group_flush",
    "group_write_call",
    "group_tx_return_to_first_rx",
    "group_rx_span",
    "group_parse_tail",
    "extended_flush",
    "extended_write_call",
    "extended_tx_return_to_first_rx",
    "extended_rx_span",
    "extended_parse_tail",
)


class TraceAnalysisError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_jsonl(path: Path, expected_schema: str) -> dict[int, dict[str, Any]]:
    records: dict[int, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TraceAnalysisError(
                    f"{path}:{line_number}: invalid JSON: {exc}"
                ) from exc
            if record.get("schema_version") != expected_schema:
                raise TraceAnalysisError(
                    f"{path}:{line_number}: expected schema {expected_schema}, "
                    f"got {record.get('schema_version')!r}"
                )
            tick = record.get("tick")
            if not isinstance(tick, int) or tick < 0:
                raise TraceAnalysisError(f"{path}:{line_number}: invalid tick {tick!r}")
            if tick in records:
                raise TraceAnalysisError(f"{path}:{line_number}: duplicate tick {tick}")
            records[tick] = record
    if not records:
        raise TraceAnalysisError(f"{path}: no records")
    return records


def _stats(values: list[float]) -> dict[str, float | int | None]:
    finite = np.asarray([value for value in values if math.isfinite(value)], dtype=np.float64)
    if finite.size == 0:
        return {
            "count": 0,
            "min": None,
            "mean": None,
            "p95": None,
            "p99": None,
            "p99_9": None,
            "max": None,
        }
    return {
        "count": int(finite.size),
        "min": float(np.min(finite)),
        "mean": float(np.mean(finite)),
        "p95": float(np.percentile(finite, 95)),
        "p99": float(np.percentile(finite, 99)),
        "p99_9": float(np.percentile(finite, 99.9)),
        "max": float(np.max(finite)),
    }


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_array = np.asarray(left, dtype=np.float64)
    right_array = np.asarray(right, dtype=np.float64)
    if not np.isfinite(left_array).all() or not np.isfinite(right_array).all():
        return None
    if float(np.std(left_array)) == 0.0 or float(np.std(right_array)) == 0.0:
        return None
    return float(np.corrcoef(left_array, right_array)[0, 1])


def _status_counts(timing_records: list[dict[str, Any]]) -> dict[str, Any]:
    logical_ids: list[int] | None = None
    per_id: dict[int, Counter[str]] = {}
    group_counter: Counter[str] = Counter()
    extended_counter: Counter[str] = Counter()
    write_counter: Counter[str] = Counter()
    failure_ticks: list[int] = []
    for record in timing_records:
        serial = record["serial"]
        statuses = serial["per_servo_status"]
        if logical_ids is None:
            logical_ids = list(range(len(statuses)))
        if len(statuses) != len(logical_ids):
            raise TraceAnalysisError("per-servo status width changed within timing stream")
        failed = False
        for index, status in enumerate(statuses):
            status_name = str(status)
            group_counter[status_name] += 1
            per_id.setdefault(index, Counter())[status_name] += 1
            failed = failed or status_name != "ok"
        extended_status = str(record["extended"]["status"])
        extended_counter[extended_status] += 1
        write_status = str(serial["write_status"])
        write_counter[write_status] += 1
        if failed:
            failure_ticks.append(int(record["tick"]))
    assert logical_ids is not None
    return {
        "group": dict(sorted(group_counter.items())),
        "extended": dict(sorted(extended_counter.items())),
        "write": dict(sorted(write_counter.items())),
        "failure_ticks": failure_ticks,
        "per_index": per_id,
    }


def _analyze_dataset(label: str, trace_path: Path, timing_path: Path) -> dict[str, Any]:
    trace_by_tick = _load_jsonl(trace_path, TRACE_SCHEMA_V1)
    timing_by_tick = _load_jsonl(timing_path, TIMING_SCHEMA_V2)
    trace_ticks = set(trace_by_tick)
    timing_ticks = set(timing_by_tick)
    if trace_ticks != timing_ticks:
        missing_trace = sorted(timing_ticks - trace_ticks)[:10]
        missing_timing = sorted(trace_ticks - timing_ticks)[:10]
        raise TraceAnalysisError(
            f"{label}: trace/timing ticks differ; missing trace={missing_trace}, "
            f"missing timing={missing_timing}"
        )
    ticks = sorted(trace_ticks)
    trace_records = [trace_by_tick[tick] for tick in ticks]
    timing_records = [timing_by_tick[tick] for tick in ticks]

    first_trace = trace_records[0]
    logical_ids = [int(value) for value in first_trace["logical_servo_ids"]]
    wire_order = [
        int(value) for value in first_trace["sync_marker"]["sync_read_wire_order"]
    ]
    if len(logical_ids) != 14 or sorted(logical_ids) != sorted(wire_order):
        raise TraceAnalysisError(f"{label}: invalid logical/wire servo ID sets")
    for record in trace_records:
        if record["logical_servo_ids"] != logical_ids:
            raise TraceAnalysisError(f"{label}: logical servo order changed")
        if record["sync_marker"]["sync_read_wire_order"] != wire_order:
            raise TraceAnalysisError(f"{label}: SyncRead wire order changed")

    status = _status_counts(timing_records)
    failure_tick_set = set(status["failure_ticks"])
    clean_ticks = [tick for tick in ticks if tick not in failure_tick_set]
    failed_ticks = [tick for tick in ticks if tick in failure_tick_set]

    phase_values: dict[str, list[float]] = {field: [] for field in PHASE_FIELDS}
    clean_phase: dict[str, list[float]] = {field: [] for field in PHASE_FIELDS}
    failed_phase: dict[str, list[float]] = {field: [] for field in PHASE_FIELDS}
    group_read_calls: list[float] = []
    clean_read_calls: list[float] = []
    failed_read_calls: list[float] = []
    completion_buckets: list[float] = []
    request_setup_us: list[float] = []
    old_deadline_margin_last_observed_us: list[float] = []
    group_end_after_old_deadline = 0
    response_offsets_by_id: dict[int, list[float]] = {servo_id: [] for servo_id in logical_ids}
    response_missing_by_id: Counter[int] = Counter()

    for tick, trace in zip(ticks, trace_records, strict=True):
        durations = trace["durations_us"]
        is_failure = tick in failure_tick_set
        for field in PHASE_FIELDS:
            value = float(durations[field])
            phase_values[field].append(value)
            (failed_phase if is_failure else clean_phase)[field].append(value)

        calls = float(trace["read_calls"]["group"])
        group_read_calls.append(calls)
        (failed_read_calls if is_failure else clean_read_calls).append(calls)

        timestamps = trace["timestamps_ns"]
        group_start_ns = int(timestamps["group_start_ns"])
        group_write_end_ns = int(timestamps["group_write_end_ns"])
        group_end_ns = int(timestamps["group_end_ns"])
        old_deadline_ns = group_start_ns + int(OLD_RESPONSE_TIMEOUT_US * 1_000)
        request_setup_us.append((group_write_end_ns - group_start_ns) / 1_000.0)
        if group_end_ns > old_deadline_ns:
            group_end_after_old_deadline += 1

        completions = [
            int(value) for value in trace["group_response_complete_ns_logical_order"]
        ]
        nonzero = [value for value in completions if value > 0]
        completion_buckets.append(float(len(set(nonzero))))
        if nonzero:
            old_deadline_margin_last_observed_us.append(
                (old_deadline_ns - max(nonzero)) / 1_000.0
            )
        for servo_id, completion_ns in zip(logical_ids, completions, strict=True):
            if completion_ns <= 0:
                response_missing_by_id[servo_id] += 1
                continue
            response_offsets_by_id[servo_id].append(
                (completion_ns - group_write_end_ns) / 1_000.0
            )

    group_failure_outcomes = sum(
        count for name, count in status["group"].items() if name != "ok"
    )
    total_group_outcomes = len(ticks) * len(logical_ids)
    per_servo = []
    for index, servo_id in enumerate(logical_ids):
        per_servo.append(
            {
                "servo_id": servo_id,
                "logical_index": index,
                "wire_index": wire_order.index(servo_id),
                "status_counts": dict(sorted(status["per_index"][index].items())),
                "missing_completion_count": int(response_missing_by_id[servo_id]),
                "completion_from_request_write_return_us": _stats(
                    response_offsets_by_id[servo_id]
                ),
            }
        )

    read_calls_by_tick = {
        tick: float(trace["read_calls"]["group"])
        for tick, trace in zip(ticks, trace_records, strict=True)
    }
    return {
        "label": label,
        "raw_inputs": {
            "transaction_trace_path": str(trace_path),
            "transaction_trace_sha256": _sha256(trace_path),
            "timing_path": str(timing_path),
            "timing_sha256": _sha256(timing_path),
        },
        "records": {
            "ticks": len(ticks),
            "first_tick": ticks[0],
            "last_tick": ticks[-1],
            "logical_servo_ids": logical_ids,
            "sync_read_wire_order": wire_order,
            "trace_schema": TRACE_SCHEMA_V1,
            "timing_schema": TIMING_SCHEMA_V2,
        },
        "group_failures": {
            "failed_outcomes": group_failure_outcomes,
            "expected_outcomes": total_group_outcomes,
            "failure_percent": 100.0 * group_failure_outcomes / total_group_outcomes,
            "failed_ticks": len(failed_ticks),
            "clean_ticks": len(clean_ticks),
            "status_counts": status["group"],
            "extended_status_counts": status["extended"],
            "write_status_counts": status["write"],
        },
        "collector_observation": {
            "instrumentation": "incremental collector transaction trace v1",
            "group_read_calls": _stats(group_read_calls),
            "group_read_call_histogram": {
                str(key): value
                for key, value in sorted(Counter(int(v) for v in group_read_calls).items())
            },
            "application_completion_buckets": _stats(completion_buckets),
            "clean_group_read_calls": _stats(clean_read_calls),
            "failed_group_read_calls": _stats(failed_read_calls),
        },
        "phase_us": {
            field: {
                "all": _stats(phase_values[field]),
                "clean_group_ticks": _stats(clean_phase[field]),
                "failed_group_ticks": _stats(failed_phase[field]),
            }
            for field in PHASE_FIELDS
        },
        "old_deadline": {
            "origin": "group_start_ns_before_flush_and_request_write",
            "timeout_us": OLD_RESPONSE_TIMEOUT_US,
            "request_setup_budget_consumed_us": _stats(request_setup_us),
            "last_observed_completion_margin_us": _stats(
                old_deadline_margin_last_observed_us
            ),
            "group_end_after_deadline_ticks": group_end_after_old_deadline,
        },
        "correlations": {
            "group_read_calls_vs_parse_tail": _correlation(
                group_read_calls, phase_values["group_parse_tail"]
            ),
            "group_read_calls_vs_group_rx_span": _correlation(
                group_read_calls, phase_values["group_rx_span"]
            ),
            "group_read_calls_vs_bus_total": _correlation(
                group_read_calls, phase_values["bus_total"]
            ),
            "group_read_calls_vs_group_failure_indicator": _correlation(
                [read_calls_by_tick[tick] for tick in ticks],
                [1.0 if tick in failure_tick_set else 0.0 for tick in ticks],
            ),
        },
        "per_servo": per_servo,
    }


def _delta(second: float | int | None, first: float | int | None) -> float | None:
    if second is None or first is None:
        return None
    return float(second) - float(first)


def _comparison(datasets: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(datasets) != 2:
        return None
    first, second = datasets
    phase_deltas: dict[str, dict[str, float | None]] = {}
    for field in PHASE_FIELDS:
        phase_deltas[field] = {
            statistic: _delta(
                second["phase_us"][field]["all"][statistic],
                first["phase_us"][field]["all"][statistic],
            )
            for statistic in ("mean", "p99_9", "max")
        }
    return {
        "operation": f"{second['label']} minus {first['label']}",
        "first_label": first["label"],
        "second_label": second["label"],
        "phase_delta_us": phase_deltas,
        "group_failure_percent_delta": _delta(
            second["group_failures"]["failure_percent"],
            first["group_failures"]["failure_percent"],
        ),
        "group_read_calls_mean_delta": _delta(
            second["collector_observation"]["group_read_calls"]["mean"],
            first["collector_observation"]["group_read_calls"]["mean"],
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze preserved transaction-trace v1 collector timing"
    )
    parser.add_argument(
        "--dataset",
        nargs=3,
        action="append",
        metavar=("LABEL", "TRACE_JSONL", "TIMING_JSONL"),
        required=True,
        help="Dataset label plus matching transaction trace and timing JSONL paths.",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if len(args.dataset) > 2:
        raise SystemExit("at most two datasets are supported")
    labels = [dataset[0] for dataset in args.dataset]
    if len(set(labels)) != len(labels):
        raise SystemExit("dataset labels must be unique")
    datasets = [
        _analyze_dataset(label, Path(trace_path), Path(timing_path))
        for label, trace_path, timing_path in args.dataset
    ]
    result = {
        "schema_version": ANALYSIS_SCHEMA,
        "quantile_method": "numpy.percentile default linear interpolation",
        "datasets": datasets,
        "comparison": _comparison(datasets),
    }
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes((json.dumps(result, indent=2, sort_keys=True) + "\n").encode())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
