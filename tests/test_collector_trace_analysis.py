from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from open_duck_x5.collector_trace_analysis import TraceAnalysisError, main
from open_duck_x5.constants import SERVO_IDS, SERVO_SYNC_READ_IDS


def _trace_record(
    tick: int,
    *,
    failure: bool,
    phase_add_us: float = 0.0,
    exact_length: bool = False,
) -> dict:
    group_start = 1_000_000_000 + tick * 20_000_000
    group_write_end = group_start + 100_000
    completions = [group_write_end + (index // 2 + 1) * 250_000 for index in range(14)]
    if failure:
        completions[12] = 0
    group_end = group_start + (4_100_000 if failure else 2_100_000)
    durations = {
        "bus_total": 4_000.0 + phase_add_us + (500.0 if failure else 0.0),
        "sync_write_call": 200.0 + phase_add_us,
        "group_flush": 20.0 + phase_add_us,
        "group_write_call": 60.0 + phase_add_us,
        "group_tx_return_to_first_rx": 900.0 + phase_add_us,
        "group_rx_span": 1_500.0 + phase_add_us + (200.0 if failure else 0.0),
        "group_parse_tail": 150.0 + phase_add_us + (100.0 if failure else 0.0),
        "extended_flush": 20.0 + phase_add_us,
        "extended_write_call": 60.0 + phase_add_us,
        "extended_tx_return_to_first_rx": 300.0 + phase_add_us,
        "extended_rx_span": 0.0,
        "extended_parse_tail": 90.0 + phase_add_us,
    }
    record = {
        "schema_version": (
            "open_duck_x5.transaction_trace.v2"
            if exact_length
            else "open_duck_x5.transaction_trace.v1"
        ),
        "tick": tick,
        "clock": "time.perf_counter_ns",
        "sync_marker": {
            "extended_servo_id": SERVO_IDS[tick % 14],
            "sync_read_wire_order": list(SERVO_SYNC_READ_IDS),
        },
        "timestamps_ns": {
            "group_start_ns": group_start,
            "group_write_end_ns": group_write_end,
            "group_end_ns": group_end,
            "extended_start_ns": group_end + 300_000,
            "extended_end_ns": group_end + 900_000,
        },
        "group_response_complete_ns_logical_order": completions,
        "logical_servo_ids": list(SERVO_IDS),
        "read_calls": {"group": 10 if failure else 7, "extended": 1},
        "durations_us": durations,
    }
    if exact_length:
        record["group_collector"] = {
            "mode": "exact_length_then_parse",
            "expected_bytes": 140,
            "parse_calls": 1,
            "bytes_before_first_parse": 140,
        }
    return record


def _timing_record(tick: int, *, failure: bool) -> dict:
    statuses = ["ok"] * 14
    if failure:
        statuses[12] = "timeout"
    return {
        "schema_version": "open_duck_x5.timing_tick.v2",
        "tick": tick,
        "serial": {
            "write_status": "ok",
            "per_servo_status": statuses,
        },
        "extended": {"status": "ok"},
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
    )


def _dataset(tmp_path: Path, label: str, phase_add_us: float = 0.0):
    trace = tmp_path / f"{label}-trace.jsonl"
    timing = tmp_path / f"{label}-timing.jsonl"
    _write_jsonl(
        trace,
        [
            _trace_record(tick, failure=tick == 2, phase_add_us=phase_add_us)
            for tick in range(4)
        ],
    )
    _write_jsonl(
        timing,
        [_timing_record(tick, failure=tick == 2) for tick in range(4)],
    )
    return trace, timing


def test_analysis_quantifies_failure_tail_and_comparison(tmp_path: Path) -> None:
    usb_trace, usb_timing = _dataset(tmp_path, "usb")
    uart_trace, uart_timing = _dataset(tmp_path, "uart", phase_add_us=10.0)
    output = tmp_path / "analysis.json"
    assert (
        main(
            [
                "--dataset",
                "usb",
                str(usb_trace),
                str(usb_timing),
                "--dataset",
                "uart",
                str(uart_trace),
                str(uart_timing),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    result = json.loads(output.read_text(encoding="utf-8"))
    schema = json.loads(
        (
            Path(__file__).parents[1]
            / "schemas"
            / "collector_trace_analysis.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(result)

    usb = result["datasets"][0]
    assert usb["records"]["ticks"] == 4
    assert usb["group_failures"]["failed_outcomes"] == 1
    assert usb["group_failures"]["failed_ticks"] == 1
    assert usb["collector_observation"]["clean_group_read_calls"]["mean"] == 7.0
    assert usb["collector_observation"]["failed_group_read_calls"]["mean"] == 10.0
    assert usb["response_deadline"]["request_setup_before_response_deadline_us"]["mean"] == 100.0
    assert usb["response_deadline"]["request_setup_charged_to_response_budget"]
    assert usb["response_deadline"]["group_end_after_deadline_ticks"] == 1
    servo_13 = next(row for row in usb["per_servo"] if row["servo_id"] == 13)
    assert servo_13["status_counts"] == {"ok": 3, "timeout": 1}
    assert servo_13["missing_completion_count"] == 1
    assert len(usb["raw_inputs"]["transaction_trace_sha256"]) == 64
    assert result["comparison"]["operation"] == "uart minus usb"
    assert result["comparison"]["phase_delta_us"]["group_parse_tail"]["mean"] == 10.0


def test_analysis_verifies_exact_length_contract(tmp_path: Path) -> None:
    trace = tmp_path / "exact-trace.jsonl"
    timing = tmp_path / "exact-timing.jsonl"
    _write_jsonl(
        trace,
        [_trace_record(tick, failure=False, exact_length=True) for tick in range(4)],
    )
    _write_jsonl(
        timing,
        [_timing_record(tick, failure=False) for tick in range(4)],
    )
    output = tmp_path / "analysis.json"
    assert (
        main(
            [
                "--dataset",
                "exact",
                str(trace),
                str(timing),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    result = json.loads(output.read_text(encoding="utf-8"))
    dataset = result["datasets"][0]
    contract = dataset["collector_observation"]["exact_length_contract"]
    assert contract["pass"]
    assert contract["parse_call_histogram"] == {"1": 4}
    assert contract["bytes_before_first_parse_histogram"] == {"140": 4}
    assert not dataset["response_deadline"][
        "request_setup_charged_to_response_budget"
    ]


def test_analysis_rejects_mismatched_tick_sets(tmp_path: Path) -> None:
    trace, timing = _dataset(tmp_path, "bad")
    lines = timing.read_text(encoding="utf-8").splitlines()
    timing.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(TraceAnalysisError, match="ticks differ"):
        main(
            [
                "--dataset",
                "bad",
                str(trace),
                str(timing),
                "--output",
                str(tmp_path / "never.json"),
            ]
        )
