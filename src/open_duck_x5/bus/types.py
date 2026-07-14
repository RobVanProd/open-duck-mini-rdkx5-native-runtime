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
    sample_time_ns: int = 0
    group_round_trip_ns: int = 0
    extended_round_trip_ns: int = 0
    bus_total_ns: int = 0
    write_status: ErrorCode = ErrorCode.OK
    extended_status: ErrorCode = ErrorCode.TIMEOUT
    extended_servo_id: int = -1
    present_current_raw: int = 0
    present_current_a: float = 0.0
    present_voltage_v: float = 0.0
    present_temperature_c: float = 0.0
    partial_bytes: int = 0
    unexpected_packets: int = 0

    @classmethod
    def create(cls) -> ServoSnapshot:
        return cls(
            positions_rad=np.zeros(ACTION_DIM, dtype=np.float64),
            velocities_rad_s=np.zeros(ACTION_DIM, dtype=np.float64),
            stale=np.ones(ACTION_DIM, dtype=np.bool_),
            status=np.full(ACTION_DIM, int(ErrorCode.TIMEOUT), dtype=np.uint8),
        )

    def begin_tick(self) -> None:
        self.stale.fill(True)
        self.status.fill(int(ErrorCode.TIMEOUT))
        self.group_round_trip_ns = 0
        self.extended_round_trip_ns = 0
        self.bus_total_ns = 0
        self.write_status = ErrorCode.OK
        self.extended_status = ErrorCode.TIMEOUT
        self.extended_servo_id = -1
        self.partial_bytes = 0
        self.unexpected_packets = 0

    @property
    def all_fresh(self) -> bool:
        return not bool(self.stale.any())

    @property
    def failed_servo_count(self) -> int:
        return int(self.stale.sum())

    def count(self, code: ErrorCode) -> int:
        return int(np.count_nonzero(self.status == int(code)))
