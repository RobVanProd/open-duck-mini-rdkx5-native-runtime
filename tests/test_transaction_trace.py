from __future__ import annotations

import json
from pathlib import Path

from open_duck_x5.bus.mock import MockSTS3215Bus
from open_duck_x5.bus.types import ServoSnapshot
from open_duck_x5.constants import HOME_RAD, SERVO_IDS, SERVO_SYNC_READ_IDS
from open_duck_x5.transaction_trace import TransactionTraceSeries


def test_transaction_trace_is_captured_in_loop_and_serialized_afterward(
    tmp_path: Path,
) -> None:
    snapshot = ServoSnapshot.create()
    snapshot.instrumentation_enabled = True
    bus = MockSTS3215Bus(latency_s=0.0)
    series = TransactionTraceSeries(1)

    bus.exchange_into(HOME_RAD, snapshot, 0)
    series.append(0, snapshot)
    output = tmp_path / "trace.jsonl"
    series.write_jsonl(output)

    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["schema_version"] == "open_duck_x5.transaction_trace.v1"
    assert record["tick"] == 0
    assert record["clock"] == "time.perf_counter_ns"
    assert record["sync_marker"]["extended_servo_id"] == SERVO_IDS[0]
    assert record["sync_marker"]["sync_read_wire_order"] == list(SERVO_SYNC_READ_IDS)
    assert record["logical_servo_ids"] == list(SERVO_IDS)
    assert len(record["group_response_complete_ns_logical_order"]) == 14
    assert record["durations_us"]["bus_total"] is not None
