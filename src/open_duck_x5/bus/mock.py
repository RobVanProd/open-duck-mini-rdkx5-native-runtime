from __future__ import annotations

import math
import struct
import time
from dataclasses import dataclass

import numpy as np

from ..clock import clock_ns
from ..constants import ACTION_DIM, HOME_RAD, SERVO_IDS, TWO_PI
from .types import ErrorCode, ServoSnapshot


@dataclass(slots=True)
class MockFault:
    tick: int
    code: ErrorCode
    servo_indices: tuple[int, ...]


class MockSTS3215Bus:
    """Deterministic loopback bus with optional per-tick fault injection."""

    def __init__(
        self,
        *,
        latency_s: float = 0.0008,
        response_alpha: float = 0.35,
        faults: tuple[MockFault, ...] = (),
    ) -> None:
        self.device = "mock://sts3215"
        self.baudrate = 1_000_000
        self.ids = SERVO_IDS
        self.latency_s = max(0.0, float(latency_s))
        self.response_alpha = float(response_alpha)
        self.positions = HOME_RAD.copy()
        self._previous_positions = HOME_RAD.copy()
        self.velocities = np.zeros(ACTION_DIM, dtype=np.float64)
        self.targets = HOME_RAD.copy()
        self.torque_enabled = False
        self.faults = faults
        self._registers = {servo_id: bytearray(256) for servo_id in SERVO_IDS}
        for servo_id, registers in self._registers.items():
            registers[5] = servo_id
        self._last_update_ns = clock_ns()
        self._active_tick = 0

    def close(self) -> None:
        return None

    def set_torque(self, enabled: bool) -> ErrorCode:
        self.torque_enabled = bool(enabled)
        return ErrorCode.OK

    def enable_torque(self) -> ErrorCode:
        return self.set_torque(True)

    def disable_torque(self) -> ErrorCode:
        return self.set_torque(False)

    def set_gains(self, p: int, i: int = 0, d: int = 0) -> ErrorCode:
        del p, i, d
        return ErrorCode.OK

    def set_gain_vectors(self, p, i=None, d=None) -> ErrorCode:
        del p, i, d
        return ErrorCode.OK

    def write_positions(self, positions_rad: np.ndarray) -> ErrorCode:
        np.copyto(self.targets, positions_rad)
        return ErrorCode.OK

    def _advance(self) -> None:
        now_ns = clock_ns()
        dt = max((now_ns - self._last_update_ns) / 1e9, 1e-6)
        np.copyto(self._previous_positions, self.positions)
        self.positions += self.response_alpha * (self.targets - self.positions)
        np.subtract(self.positions, self._previous_positions, out=self.velocities)
        self.velocities /= dt
        self._last_update_ns = now_ns

    def _sleep_latency(self) -> None:
        if self.latency_s:
            time.sleep(self.latency_s)

    def _apply_faults(self, snapshot: ServoSnapshot) -> None:
        for fault in self.faults:
            if fault.tick != self._active_tick:
                continue
            for index in fault.servo_indices:
                snapshot.status[index] = int(fault.code)
                snapshot.stale[index] = True

    def read_state_into(self, snapshot: ServoSnapshot) -> None:
        start_ns = clock_ns()
        self._sleep_latency()
        self._advance()
        np.copyto(snapshot.positions_rad, self.positions)
        np.copyto(snapshot.velocities_rad_s, self.velocities)
        snapshot.status.fill(int(ErrorCode.OK))
        snapshot.stale.fill(False)
        self._apply_faults(snapshot)
        snapshot.sample_time_ns = clock_ns()
        snapshot.group_round_trip_ns = snapshot.sample_time_ns - start_ns

    def read_extended_into(self, snapshot: ServoSnapshot, servo_id: int) -> None:
        start_ns = clock_ns()
        snapshot.extended_servo_id = servo_id
        snapshot.present_current_raw = 18
        snapshot.present_current_a = 18 * 0.0065
        snapshot.present_voltage_v = 7.4
        snapshot.present_temperature_c = 28.0
        snapshot.extended_status = ErrorCode.OK
        snapshot.extended_round_trip_ns = clock_ns() - start_ns

    def exchange_into(
        self, positions_rad: np.ndarray, snapshot: ServoSnapshot, tick_index: int
    ) -> None:
        snapshot.begin_tick()
        self._active_tick = int(tick_index)
        start_ns = clock_ns()
        snapshot.write_status = self.write_positions(positions_rad)
        self.read_state_into(snapshot)
        self.read_extended_into(snapshot, self.ids[tick_index % ACTION_DIM])
        snapshot.bus_total_ns = clock_ns() - start_ns

    def ping(self, servo_id: int, *, timeout_s: float | None = None) -> ErrorCode:
        del timeout_s
        return ErrorCode.OK if servo_id in self.ids else ErrorCode.TIMEOUT

    def read_register(self, servo_id: int, address: int, length: int) -> tuple[ErrorCode, bytes]:
        if servo_id not in self.ids:
            return ErrorCode.TIMEOUT, b""
        if address == 56 and length == 2:
            index = self.ids.index(servo_id)
            raw = int(4096.0 * (math.pi + float(self.positions[index])) / TWO_PI)
            return ErrorCode.OK, struct.pack("<h", raw)
        return ErrorCode.OK, bytes(self._registers[servo_id][address : address + length])

    def write_register(self, servo_id: int, address: int, data: bytes) -> ErrorCode:
        if servo_id not in self.ids:
            return ErrorCode.TIMEOUT
        self._registers[servo_id][address : address + len(data)] = data
        return ErrorCode.OK
