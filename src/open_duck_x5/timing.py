from __future__ import annotations

from dataclasses import dataclass
from time import sleep

import numpy as np

from .bus.types import ERROR_NAMES, ErrorCode, ServoSnapshot
from .clock import clock_ns
from .constants import ACTION_DIM, CONTROL_PERIOD_NS


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
    def __init__(self, capacity: int, *, tracking_joint_index: int = 0) -> None:
        if not 0 <= tracking_joint_index < ACTION_DIM:
            raise ValueError(f"tracking joint index must be in 0..{ACTION_DIM - 1}")
        self.capacity = int(capacity)
        self.tracking_joint_index = int(tracking_joint_index)
        self.count = 0
        self.tick_period_ns = np.zeros(capacity, dtype=np.int64)
        self.release_lateness_ns = np.zeros(capacity, dtype=np.int64)
        self.group_round_trip_ns = np.zeros(capacity, dtype=np.int64)
        self.extended_round_trip_ns = np.zeros(capacity, dtype=np.int64)
        self.bus_total_ns = np.zeros(capacity, dtype=np.int64)
        self.failed_group_replies = np.zeros(capacity, dtype=np.int16)
        self.failed_transactions = np.zeros(capacity, dtype=np.int16)
        self.transaction_status_counts = np.zeros(
            (capacity, len(ErrorCode)), dtype=np.int16
        )
        self.device_alarm_replies = np.zeros(capacity, dtype=np.int16)
        self.voltage_alarm_replies = np.zeros(capacity, dtype=np.int16)
        self.partial_bytes = np.zeros(capacity, dtype=np.int16)
        self.unexpected_packets = np.zeros(capacity, dtype=np.int16)
        self.tracking_error_rad = np.zeros(capacity, dtype=np.float64)
        self.tracking_valid = np.zeros(capacity, dtype=np.bool_)
        self._last_tick_start_ns = 0

    def append(
        self,
        tick_start_ns: int,
        release_lateness_ns: int,
        snapshot: ServoSnapshot,
        target_positions_rad: np.ndarray | None = None,
    ) -> None:
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
        counts = self.transaction_status_counts[index]
        for code in ErrorCode:
            counts[int(code)] = int(np.count_nonzero(snapshot.status == int(code)))
        counts[int(snapshot.write_status)] += 1
        counts[int(snapshot.extended_status)] += 1
        group_device_status = snapshot.device_status
        self.device_alarm_replies[index] = int(
            np.count_nonzero(group_device_status)
            + int(snapshot.extended_device_status != 0)
        )
        self.voltage_alarm_replies[index] = int(
            np.count_nonzero(group_device_status & 0x01)
            + int(bool(snapshot.extended_device_status & 0x01))
        )
        self.partial_bytes[index] = snapshot.partial_bytes
        self.unexpected_packets[index] = snapshot.unexpected_packets
        self.failed_transactions[index] = (
            ACTION_DIM + 2 - int(counts[int(ErrorCode.OK)]) + snapshot.unexpected_packets
        )
        if target_positions_rad is not None:
            if target_positions_rad.shape != (ACTION_DIM,):
                raise ValueError(f"target positions must have shape ({ACTION_DIM},)")
            joint = self.tracking_joint_index
            if not snapshot.stale[joint]:
                self.tracking_error_rad[index] = abs(
                    float(snapshot.positions_rad[joint] - target_positions_rad[joint])
                )
                self.tracking_valid[index] = True
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
        status_counts_array = self.transaction_status_counts[: self.count].sum(axis=0)
        status_counts = {
            ERROR_NAMES[int(code)]: int(status_counts_array[int(code)]) for code in ErrorCode
        }
        unexpected_count = int(self.unexpected_packets[: self.count].sum())
        device_alarm_count = int(self.device_alarm_replies[: self.count].sum())
        voltage_alarm_count = int(self.voltage_alarm_replies[: self.count].sum())
        failure_counts = {
            name: count for name, count in status_counts.items() if name != "ok"
        }
        failure_counts["unexpected_packet"] = unexpected_count
        burst = self.burst_summary()
        tick = self._stats(tick_values)
        bus = self._stats(self.bus_total_ns[: self.count])
        failure_rate = failures / expected_transactions if expected_transactions else 0.0
        tracking_values = self.tracking_error_rad[: self.count][
            self.tracking_valid[: self.count]
        ]
        tracking = (
            {
                "samples": int(tracking_values.size),
                "min": float(np.min(tracking_values)),
                "mean": float(np.mean(tracking_values)),
                "p95": float(np.percentile(tracking_values, 95)),
                "p99": float(np.percentile(tracking_values, 99)),
                "p99_9": float(np.percentile(tracking_values, 99.9)),
                "max": float(np.max(tracking_values)),
            }
            if tracking_values.size
            else {
                key: 0 if key == "samples" else None
                for key in ("samples", "min", "mean", "p95", "p99", "p99_9", "max")
            }
        )
        return {
            "schema_version": "open_duck_x5.timing_summary.v2",
            "backend": backend,
            "informational_only": informational_only,
            "ticks": self.count,
            "bus_total_population": {
                "observation": "complete_tick_sweep",
                "observations": self.count,
                "statistic": "sample_max_over_completed_ticks",
                "components": [
                    "goal_sync_write_all_14",
                    "state_sync_read_0x82_all_14",
                    "extended_read_one_servo",
                ],
            },
            "group_round_trip_population": {
                "observation": "one_0x82_request_plus_14_response_burst",
                "observations": self.count,
                "statistic": "sample_max_over_completed_ticks",
            },
            "tick_period_ms": tick,
            "release_lateness_ms": self._stats(self.release_lateness_ns[: self.count]),
            "group_round_trip_ms": self._stats(self.group_round_trip_ns[: self.count]),
            "extended_round_trip_ms": self._stats(self.extended_round_trip_ns[: self.count]),
            "bus_total_ms": bus,
            "transactions_expected": expected_transactions,
            "transactions_failed": failures,
            "transaction_status_counts": status_counts,
            "transaction_failure_counts": failure_counts,
            "transaction_failure_rate": failure_rate,
            "transaction_failure_percent": failure_rate * 100.0,
            "device_alarm_reply_count": device_alarm_count,
            "voltage_alarm_reply_count": voltage_alarm_count,
            "partial_byte_count": int(self.partial_bytes[: self.count].sum()),
            "unexpected_packet_count": unexpected_count,
            "read_burst_count": burst.burst_count,
            "max_read_burst_ticks": burst.max_burst_ticks,
            "tracking_joint_index": self.tracking_joint_index,
            "tracking_absolute_error_rad": tracking,
            "gates": {
                "tick_p99_at_most_21_ms": tick["p99"] is not None and tick["p99"] <= 21.0,
                "tick_p99_9_at_most_22_ms": tick["p99_9"] is not None
                and tick["p99_9"] <= 22.0,
                "zero_read_bursts": burst.burst_count == 0,
                "transaction_failure_below_0_1_percent": failure_rate < 0.001,
                "zero_device_alarms": device_alarm_count == 0,
                "bus_max_under_5_ms": bus["max"] is not None and bus["max"] < 5.0,
                "tracking_p95_at_most_0_011_rad": tracking["p95"] is not None
                and tracking["p95"] <= 0.011,
            },
        }
