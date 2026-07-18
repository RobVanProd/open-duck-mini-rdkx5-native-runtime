from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

import numpy as np

from ..constants import ACTION_DIM


class ErrorCode(IntEnum):
    OK = 0
    TIMEOUT = 1
    CRC = 2
    PARTIAL = 3
    DEVICE = 4
    UNEXPECTED_ID = 5
    IO = 6


ERROR_NAMES = tuple(code.name.lower() for code in ErrorCode)


@dataclass(slots=True)
class ServoSnapshot:
    positions_rad: np.ndarray
    velocities_rad_s: np.ndarray
    stale: np.ndarray
    status: np.ndarray
    device_status: np.ndarray
    sample_time_ns: int = 0
    group_round_trip_ns: int = 0
    extended_round_trip_ns: int = 0
    bus_total_ns: int = 0
    write_status: ErrorCode = ErrorCode.OK
    extended_status: ErrorCode = ErrorCode.TIMEOUT
    extended_device_status: int = 0
    extended_servo_id: int = -1
    present_current_raw: int = 0
    present_current_a: float = 0.0
    present_voltage_v: float = 0.0
    present_temperature_c: float = 0.0
    partial_bytes: int = 0
    unexpected_packets: int = 0
    instrumentation_enabled: bool = False
    trace_bus_start_ns: int = 0
    trace_bus_end_ns: int = 0
    trace_write_start_ns: int = 0
    trace_write_end_ns: int = 0
    trace_group_start_ns: int = 0
    trace_group_flush_start_ns: int = 0
    trace_group_flush_end_ns: int = 0
    trace_group_write_start_ns: int = 0
    trace_group_write_end_ns: int = 0
    trace_group_first_rx_ns: int = 0
    trace_group_last_rx_ns: int = 0
    trace_group_end_ns: int = 0
    trace_group_read_calls: int = 0
    trace_group_parse_calls: int = 0
    trace_group_first_parse_bytes: int = 0
    trace_group_response_complete_ns: np.ndarray | None = None
    trace_extended_start_ns: int = 0
    trace_extended_flush_start_ns: int = 0
    trace_extended_flush_end_ns: int = 0
    trace_extended_write_start_ns: int = 0
    trace_extended_write_end_ns: int = 0
    trace_extended_first_rx_ns: int = 0
    trace_extended_last_rx_ns: int = 0
    trace_extended_end_ns: int = 0
    trace_extended_read_calls: int = 0

    @classmethod
    def create(cls) -> ServoSnapshot:
        return cls(
            positions_rad=np.zeros(ACTION_DIM, dtype=np.float64),
            velocities_rad_s=np.zeros(ACTION_DIM, dtype=np.float64),
            stale=np.ones(ACTION_DIM, dtype=np.bool_),
            status=np.full(ACTION_DIM, int(ErrorCode.TIMEOUT), dtype=np.uint8),
            device_status=np.zeros(ACTION_DIM, dtype=np.uint8),
            trace_group_response_complete_ns=np.zeros(ACTION_DIM, dtype=np.int64),
        )

    def begin_tick(self) -> None:
        self.stale.fill(True)
        self.status.fill(int(ErrorCode.TIMEOUT))
        self.device_status.fill(0)
        self.group_round_trip_ns = 0
        self.extended_round_trip_ns = 0
        self.bus_total_ns = 0
        self.write_status = ErrorCode.OK
        self.extended_status = ErrorCode.TIMEOUT
        self.extended_device_status = 0
        self.extended_servo_id = -1
        self.partial_bytes = 0
        self.unexpected_packets = 0
        if self.instrumentation_enabled:
            self.trace_bus_start_ns = 0
            self.trace_bus_end_ns = 0
            self.trace_write_start_ns = 0
            self.trace_write_end_ns = 0
            self.trace_group_start_ns = 0
            self.trace_group_flush_start_ns = 0
            self.trace_group_flush_end_ns = 0
            self.trace_group_write_start_ns = 0
            self.trace_group_write_end_ns = 0
            self.trace_group_first_rx_ns = 0
            self.trace_group_last_rx_ns = 0
            self.trace_group_end_ns = 0
            self.trace_group_read_calls = 0
            self.trace_group_parse_calls = 0
            self.trace_group_first_parse_bytes = 0
            if self.trace_group_response_complete_ns is not None:
                self.trace_group_response_complete_ns.fill(0)
            self.trace_extended_start_ns = 0
            self.trace_extended_flush_start_ns = 0
            self.trace_extended_flush_end_ns = 0
            self.trace_extended_write_start_ns = 0
            self.trace_extended_write_end_ns = 0
            self.trace_extended_first_rx_ns = 0
            self.trace_extended_last_rx_ns = 0
            self.trace_extended_end_ns = 0
            self.trace_extended_read_calls = 0

    @property
    def all_fresh(self) -> bool:
        return not bool(self.stale.any())

    @property
    def failed_servo_count(self) -> int:
        return int(self.stale.sum())

    @property
    def device_alarm_count(self) -> int:
        return int(np.count_nonzero(self.device_status))

    @property
    def any_device_alarm(self) -> bool:
        return bool(self.device_status.any() or self.extended_device_status)

    def count(self, code: ErrorCode) -> int:
        return int(np.count_nonzero(self.status == int(code)))
