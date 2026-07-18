from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .bus.types import ServoSnapshot
from .constants import ACTION_DIM, SERVO_IDS, SERVO_SYNC_READ_IDS

_SCALAR_FIELDS = (
    "trace_bus_start_ns",
    "trace_bus_end_ns",
    "trace_write_start_ns",
    "trace_write_end_ns",
    "trace_group_start_ns",
    "trace_group_flush_start_ns",
    "trace_group_flush_end_ns",
    "trace_group_write_start_ns",
    "trace_group_write_end_ns",
    "trace_group_first_rx_ns",
    "trace_group_last_rx_ns",
    "trace_group_end_ns",
    "trace_extended_start_ns",
    "trace_extended_flush_start_ns",
    "trace_extended_flush_end_ns",
    "trace_extended_write_start_ns",
    "trace_extended_write_end_ns",
    "trace_extended_first_rx_ns",
    "trace_extended_last_rx_ns",
    "trace_extended_end_ns",
)


def _duration_us(start_ns: int, end_ns: int) -> float | None:
    if start_ns <= 0 or end_ns < start_ns:
        return None
    return (end_ns - start_ns) / 1e3


class TransactionTraceSeries:
    """Preallocated application-level serial stage timestamps.

    JSON construction and filesystem I/O happen only after the control loop has
    stopped and the final torque-off command has completed.
    """

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("transaction trace capacity must be positive")
        self.capacity = int(capacity)
        self.count = 0
        self.tick = np.zeros(capacity, dtype=np.int64)
        self.extended_servo_id = np.full(capacity, -1, dtype=np.int16)
        self.group_read_calls = np.zeros(capacity, dtype=np.int16)
        self.group_parse_calls = np.zeros(capacity, dtype=np.int16)
        self.group_first_parse_bytes = np.zeros(capacity, dtype=np.int16)
        self.extended_read_calls = np.zeros(capacity, dtype=np.int16)
        self.timestamps_ns = np.zeros((capacity, len(_SCALAR_FIELDS)), dtype=np.int64)
        self.group_response_complete_ns = np.zeros(
            (capacity, ACTION_DIM), dtype=np.int64
        )

    def append(self, tick: int, snapshot: ServoSnapshot) -> None:
        if not snapshot.instrumentation_enabled:
            raise ValueError("cannot append a snapshot with instrumentation disabled")
        if self.count >= self.capacity:
            raise IndexError("transaction trace capacity exceeded")
        index = self.count
        self.tick[index] = int(tick)
        self.extended_servo_id[index] = int(snapshot.extended_servo_id)
        self.group_read_calls[index] = int(snapshot.trace_group_read_calls)
        self.group_parse_calls[index] = int(snapshot.trace_group_parse_calls)
        self.group_first_parse_bytes[index] = int(snapshot.trace_group_first_parse_bytes)
        self.extended_read_calls[index] = int(snapshot.trace_extended_read_calls)
        row = self.timestamps_ns[index]
        for field_index, field_name in enumerate(_SCALAR_FIELDS):
            row[field_index] = int(getattr(snapshot, field_name))
        if snapshot.trace_group_response_complete_ns is None:
            raise ValueError("snapshot lacks the preallocated group response trace")
        np.copyto(
            self.group_response_complete_ns[index],
            snapshot.trace_group_response_complete_ns,
        )
        self.count += 1

    def write_jsonl(self, path: str | Path) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8", newline="\n") as handle:
            for index in range(self.count):
                values = {
                    field_name.removeprefix("trace_"): int(self.timestamps_ns[index, field])
                    for field, field_name in enumerate(_SCALAR_FIELDS)
                }
                response_times = self.group_response_complete_ns[index]
                record = {
                    "schema_version": "open_duck_x5.transaction_trace.v2",
                    "tick": int(self.tick[index]),
                    "clock": "time.perf_counter_ns",
                    "sync_marker": {
                        "extended_servo_id": int(self.extended_servo_id[index]),
                        "sync_read_wire_order": list(SERVO_SYNC_READ_IDS),
                    },
                    "timestamps_ns": values,
                    "group_response_complete_ns_logical_order": response_times.tolist(),
                    "logical_servo_ids": list(SERVO_IDS),
                    "read_calls": {
                        "group": int(self.group_read_calls[index]),
                        "extended": int(self.extended_read_calls[index]),
                    },
                    "group_collector": {
                        "mode": "exact_length_then_parse",
                        "expected_bytes": 140,
                        "parse_calls": int(self.group_parse_calls[index]),
                        "bytes_before_first_parse": int(
                            self.group_first_parse_bytes[index]
                        ),
                    },
                    "durations_us": {
                        "bus_total": _duration_us(
                            values["bus_start_ns"], values["bus_end_ns"]
                        ),
                        "sync_write_call": _duration_us(
                            values["write_start_ns"], values["write_end_ns"]
                        ),
                        "group_flush": _duration_us(
                            values["group_flush_start_ns"],
                            values["group_flush_end_ns"],
                        ),
                        "group_write_call": _duration_us(
                            values["group_write_start_ns"],
                            values["group_write_end_ns"],
                        ),
                        "group_tx_return_to_first_rx": _duration_us(
                            values["group_write_end_ns"],
                            values["group_first_rx_ns"],
                        ),
                        "group_rx_span": _duration_us(
                            values["group_first_rx_ns"],
                            values["group_last_rx_ns"],
                        ),
                        "group_parse_tail": _duration_us(
                            values["group_last_rx_ns"], values["group_end_ns"]
                        ),
                        "extended_flush": _duration_us(
                            values["extended_flush_start_ns"],
                            values["extended_flush_end_ns"],
                        ),
                        "extended_write_call": _duration_us(
                            values["extended_write_start_ns"],
                            values["extended_write_end_ns"],
                        ),
                        "extended_tx_return_to_first_rx": _duration_us(
                            values["extended_write_end_ns"],
                            values["extended_first_rx_ns"],
                        ),
                        "extended_rx_span": _duration_us(
                            values["extended_first_rx_ns"],
                            values["extended_last_rx_ns"],
                        ),
                        "extended_parse_tail": _duration_us(
                            values["extended_last_rx_ns"],
                            values["extended_end_ns"],
                        ),
                    },
                }
                handle.write(json.dumps(record, separators=(",", ":")) + "\n")
