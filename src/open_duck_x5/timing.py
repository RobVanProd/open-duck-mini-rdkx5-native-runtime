from __future__ import annotations

from dataclasses import dataclass
from time import sleep

import numpy as np

from .bus.types import ErrorCode, ServoSnapshot
from .clock import clock_ns
from .constants import CONTROL_PERIOD_NS


class AbsoluteTicker:
    def __init__(self, period_ns: int = CONTROL_PERIOD_NS, *, spin_ns: int = 50_000) -> None:
        if period_ns <= 0:
            raise ValueError("period must be positive")
        self.period_ns = int(period_ns)
        self.spin_ns = max(0, int(spin_ns))
        self.next_release_ns = clock_ns()

    def wait(self) -> tuple[int, int]:
        target = self.next_release_ns
        while True:
            now = clock_ns()
            remaining = target - now
            if remaining <= 0:
                break
            if remaining > self.spin_ns:
                sleep((remaining - self.spin_ns) / 1e9)
            else:
                # Deliberate bounded spin only for the final tens of microseconds.
                pass
        actual = clock_ns()
        self.next_release_ns += self.period_ns
        return actual, actual - target


@dataclass(slots=True)
class BurstSummary:
    burst_count: int
    max_burst_ticks: int


class TimingSeries:
    def __init__(self, capacity: int) -> None:
        self.capacity = int(capacity)
        self.count = 0
        self.tick_period_ns = np.zeros(capacity, dtype=np.int64)
        self.release_lateness_ns = np.zeros(capacity, dtype=np.int64)
        self.group_round_trip_ns = np.zeros(capacity, dtype=np.int64)
        self.extended_round_trip_ns = np.zeros(capacity, dtype=np.int64)
        self.bus_total_ns = np.zeros(capacity, dtype=np.int64)
        self.failed_group_replies = np.zeros(capacity, dtype=np.int16)
        self.failed_transactions = np.zeros(capacity, dtype=np.int16)
        self._last_tick_start_ns = 0

    def append(self, tick_start_ns: int, release_lateness_ns: int, snapshot: ServoSnapshot) -> None:
        if self.count >= self.capacity:
            raise IndexError("timing series capacity exceeded")
        index = self.count
        if self._last_tick_start_ns:
            self.tick_period_ns[index] = tick_start_ns - self._last_tick_start_ns
        self._last_tick_start_ns = tick_start_ns
        self.release_lateness_ns[index] = release_lateness_ns
        self.group_round_trip_ns[index] = snapshot.group_round_trip_ns
        self.extended_round_trip_ns[index] = snapshot.extended_round_trip_ns
        self.bus_total_ns[index] = snapshot.bus_total_ns
        group_failures = snapshot.failed_servo_count
        self.failed_group_replies[index] = group_failures
        self.failed_transactions[index] = (
            group_failures
            + int(snapshot.write_status is not ErrorCode.OK)
            + int(snapshot.extended_status is not ErrorCode.OK)
            + snapshot.unexpected_packets
        )
        self.count += 1

    @staticmethod
    def _stats(values_ns: np.ndarray) -> dict[str, float | None]:
        if values_ns.size == 0:
            return {key: None for key in ("min", "mean", "p95", "p99", "p99_9", "max")}
        values_ms = values_ns.astype(np.float64) / 1e6
        return {
            "min": float(np.min(values_ms)),
            "mean": float(np.mean(values_ms)),
            "p95": float(np.percentile(values_ms, 95)),
            "p99": float(np.percentile(values_ms, 99)),
            "p99_9": float(np.percentile(values_ms, 99.9)),
            "max": float(np.max(values_ms)),
        }

    def burst_summary(self) -> BurstSummary:
        burst_count = 0
        max_burst = 0
        current = 0
        for failed in self.failed_group_replies[: self.count] > 0:
            if failed:
                current += 1
                max_burst = max(max_burst, current)
            else:
                if current >= 2:
                    burst_count += 1
                current = 0
        if current >= 2:
            burst_count += 1
        return BurstSummary(burst_count=burst_count, max_burst_ticks=max_burst)

    def summary(self, *, backend: str, informational_only: bool) -> dict[str, object]:
        tick_values = self.tick_period_ns[1 : self.count]
        expected_transactions = self.count * 16  # write + 14 grouped replies + one extended read
        failures = int(self.failed_transactions[: self.count].sum())
        burst = self.burst_summary()
        tick = self._stats(tick_values)
        bus = self._stats(self.bus_total_ns[: self.count])
        failure_rate = failures / expected_transactions if expected_transactions else 0.0
        return {
            "schema_version": "open_duck_x5.timing_summary.v1",
            "backend": backend,
            "informational_only": informational_only,
            "ticks": self.count,
            "tick_period_ms": tick,
            "release_lateness_ms": self._stats(self.release_lateness_ns[: self.count]),
            "group_round_trip_ms": self._stats(self.group_round_trip_ns[: self.count]),
            "extended_round_trip_ms": self._stats(self.extended_round_trip_ns[: self.count]),
            "bus_total_ms": bus,
            "transactions_expected": expected_transactions,
            "transactions_failed": failures,
            "transaction_failure_rate": failure_rate,
            "transaction_failure_percent": failure_rate * 100.0,
            "read_burst_count": burst.burst_count,
            "max_read_burst_ticks": burst.max_burst_ticks,
            "gates": {
                "tick_p99_at_most_21_ms": tick["p99"] is not None and tick["p99"] <= 21.0,
                "tick_p99_9_at_most_22_ms": tick["p99_9"] is not None
                and tick["p99_9"] <= 22.0,
                "zero_read_bursts": burst.burst_count == 0,
                "transaction_failure_below_0_1_percent": failure_rate < 0.001,
                "bus_max_under_5_ms": bus["max"] is not None and bus["max"] < 5.0,
            },
        }
