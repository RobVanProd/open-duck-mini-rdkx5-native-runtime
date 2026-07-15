from __future__ import annotations

import numpy as np

from open_duck_x5.bus.types import ErrorCode, ServoSnapshot
from open_duck_x5.constants import ACTION_DIM
from open_duck_x5.timing import TimingSeries


def test_timing_summary_percentiles_failures_and_bursts() -> None:
    series = TimingSeries(5)
    snapshot = ServoSnapshot.create()
    start = 1_000_000_000
    for tick in range(5):
        snapshot.begin_tick()
        snapshot.stale.fill(False)
        snapshot.status.fill(int(ErrorCode.OK))
        snapshot.group_round_trip_ns = 1_000_000
        snapshot.extended_round_trip_ns = 200_000
        snapshot.bus_total_ns = 2_000_000
        snapshot.extended_status = ErrorCode.OK
        if tick in (1, 2):
            snapshot.stale[0] = True
            snapshot.status[0] = int(ErrorCode.TIMEOUT)
        series.append(start + tick * 20_000_000, 10_000, snapshot)

    summary = series.summary(backend="mock", informational_only=True)
    assert summary["tick_period_ms"]["p99"] == 20.0
    assert summary["bus_total_ms"]["max"] == 2.0
    assert summary["transactions_expected"] == 80
    assert summary["transactions_failed"] == 2
    assert summary["read_burst_count"] == 1
    assert summary["max_read_burst_ticks"] == 2
    assert summary["gates"]["zero_read_bursts"] is False
    assert summary["gates"]["transaction_failure_below_0_1_percent"] is False


def test_timing_summary_reports_each_failure_class_and_tracking_error() -> None:
    series = TimingSeries(1, tracking_joint_index=3)
    snapshot = ServoSnapshot.create()
    snapshot.begin_tick()
    snapshot.stale.fill(False)
    snapshot.status.fill(int(ErrorCode.OK))
    snapshot.status[0] = int(ErrorCode.CRC)
    snapshot.stale[0] = True
    snapshot.write_status = ErrorCode.IO
    snapshot.extended_status = ErrorCode.DEVICE
    snapshot.unexpected_packets = 2
    snapshot.partial_bytes = 5
    target = np.zeros(ACTION_DIM, dtype=np.float64)
    snapshot.positions_rad[3] = 0.005
    series.append(1_000_000_000, 0, snapshot, target)

    summary = series.summary(backend="mock", informational_only=True)
    assert summary["schema_version"] == "open_duck_x5.timing_summary.v2"
    assert summary["transactions_expected"] == 16
    assert summary["transactions_failed"] == 5
    assert summary["transaction_status_counts"]["ok"] == 13
    assert summary["transaction_failure_counts"] == {
        "timeout": 0,
        "crc": 1,
        "partial": 0,
        "device": 1,
        "unexpected_id": 0,
        "io": 1,
        "unexpected_packet": 2,
    }
    assert summary["partial_byte_count"] == 5
    assert summary["unexpected_packet_count"] == 2
    assert summary["tracking_absolute_error_rad"]["p95"] == 0.005
    assert summary["gates"]["tracking_p95_at_most_0_011_rad"] is True


def test_device_alarms_are_reported_without_becoming_transport_failures() -> None:
    series = TimingSeries(1)
    snapshot = ServoSnapshot.create()
    snapshot.begin_tick()
    snapshot.stale.fill(False)
    snapshot.status.fill(int(ErrorCode.OK))
    snapshot.device_status[0] = 0x01
    snapshot.write_status = ErrorCode.OK
    snapshot.extended_status = ErrorCode.OK
    snapshot.extended_device_status = 0x01

    series.append(1_000_000_000, 0, snapshot)
    summary = series.summary(backend="mock", informational_only=True)

    assert summary["transactions_failed"] == 0
    assert summary["transaction_status_counts"]["ok"] == 16
    assert summary["device_alarm_reply_count"] == 2
    assert summary["voltage_alarm_reply_count"] == 2
    assert summary["gates"]["zero_device_alarms"] is False
