from __future__ import annotations

from open_duck_x5.bus.types import ErrorCode, ServoSnapshot
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
