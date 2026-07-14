from __future__ import annotations

import math
import struct
from collections.abc import Sequence

import numpy as np

from ..clock import clock_ns
from ..constants import ACTION_DIM, SERVO_IDS, TWO_PI
from .protocol import (
    BROADCAST_ID,
    PING,
    READ,
    WRITE,
    checksum,
    instruction_packet,
    sync_read_packet,
)
from .transport import ByteTransport, SerialTransport
from .types import ErrorCode, ServoSnapshot

ADDR_ID = 5
ADDR_P_COEFFICIENT = 21
ADDR_TORQUE_ENABLE = 40
ADDR_ACCELERATION = 41
ADDR_GOAL_POSITION = 42
ADDR_LOCK = 55
ADDR_PRESENT_POSITION = 56
ADDR_PRESENT_LOAD = 60
ADDR_MAXIMUM_ACCELERATION = 85


def raw_position_to_rad(raw: int) -> float:
    return (TWO_PI * float(raw) / 4096.0) - math.pi


def rad_to_raw_position(rad: float) -> int:
    raw = int(4096.0 * (math.pi + float(rad)) / TWO_PI)
    if not -32768 <= raw <= 32767:
        raise ValueError(f"position {rad} rad is outside STS3215 signed multi-turn range")
    return raw


def raw_speed_to_rad_s(raw: int) -> float:
    value = float(raw)
    if value > 32768.0:  # Preserve the conversion used by rustypot==0.1.0.
        value = -(value - 32768.0)
    return TWO_PI * value / 4095.0


class STS3215Bus:
    """Direct STS3215 protocol with preallocated hot-path frames and receive buffers."""

    def __init__(
        self,
        device: str = "/dev/ttyACM0",
        *,
        baudrate: int = 1_000_000,
        transaction_timeout_s: float = 0.004,
        transport: ByteTransport | None = None,
    ) -> None:
        self.device = device
        self.baudrate = int(baudrate)
        self.transaction_timeout_ns = int(transaction_timeout_s * 1e9)
        if self.transaction_timeout_ns <= 0:
            raise ValueError("transaction timeout must be positive")
        self.transport = transport or SerialTransport(device, baudrate)
        self.ids = SERVO_IDS
        self._id_to_index = np.full(254, -1, dtype=np.int16)
        for index, servo_id in enumerate(self.ids):
            self._id_to_index[servo_id] = index

        self._sync_read_state = sync_read_packet(self.ids, ADDR_PRESENT_POSITION, 4)
        self._extended_read_packets = tuple(
            instruction_packet(servo_id, READ, bytes((ADDR_PRESENT_LOAD, 11)))
            for servo_id in self.ids
        )
        self._sync_write_frame = bytearray(8 + ACTION_DIM * 3)
        self._sync_write_frame[0:2] = b"\xff\xff"
        self._sync_write_frame[2] = BROADCAST_ID
        self._sync_write_frame[3] = 4 + ACTION_DIM * 3
        self._sync_write_frame[4] = 0x83
        self._sync_write_frame[5] = ADDR_GOAL_POSITION
        self._sync_write_frame[6] = 2
        for index, servo_id in enumerate(self.ids):
            self._sync_write_frame[7 + index * 3] = servo_id
        self._sync_write_view = memoryview(self._sync_write_frame)

        self._rx = bytearray(1024)
        self._rx_view = memoryview(self._rx)
        self._rx_length = 0
        self._read_data = np.zeros((ACTION_DIM, 16), dtype=np.uint8)
        self._read_lengths = np.zeros(ACTION_DIM, dtype=np.uint8)
        self._read_seen = np.zeros(ACTION_DIM, dtype=np.bool_)
        self._read_codes = np.full(ACTION_DIM, int(ErrorCode.TIMEOUT), dtype=np.uint8)
        self._unexpected_packets = 0

    def close(self) -> None:
        self.transport.close()

    def _flush_before_transaction(self) -> None:
        self._rx_length = 0
        self.transport.flush_input()

    def write_positions(self, positions_rad: np.ndarray) -> ErrorCode:
        if positions_rad.shape != (ACTION_DIM,):
            raise ValueError(f"positions must have shape ({ACTION_DIM},)")
        for index, position in enumerate(positions_rad):
            raw = rad_to_raw_position(float(position))
            struct.pack_into("<h", self._sync_write_frame, 8 + index * 3, raw)
        self._sync_write_frame[-1] = checksum(self._sync_write_view[2:-1])
        try:
            self.transport.write(self._sync_write_view)
            return ErrorCode.OK
        except (OSError, TimeoutError):
            return ErrorCode.IO

    def read_state_into(self, snapshot: ServoSnapshot) -> None:
        start_ns = clock_ns()
        self._flush_before_transaction()
        try:
            self.transport.write(self._sync_read_state)
        except (OSError, TimeoutError):
            snapshot.status.fill(int(ErrorCode.IO))
            snapshot.stale.fill(True)
            snapshot.group_round_trip_ns = clock_ns() - start_ns
            return
        self._collect_packets(
            expected_param_length=4,
            deadline_ns=start_ns + self.transaction_timeout_ns,
        )
        now_ns = clock_ns()
        snapshot.group_round_trip_ns = now_ns - start_ns
        snapshot.sample_time_ns = now_ns
        snapshot.status[:] = self._read_codes
        snapshot.stale[:] = self._read_codes != int(ErrorCode.OK)
        snapshot.partial_bytes += self._rx_length
        snapshot.unexpected_packets += self._unexpected_packets
        for index in range(ACTION_DIM):
            if snapshot.stale[index]:
                continue
            raw_pos = int(self._read_data[index, 0]) | (int(self._read_data[index, 1]) << 8)
            if raw_pos >= 0x8000:
                raw_pos -= 0x10000
            raw_speed = int(self._read_data[index, 2]) | (int(self._read_data[index, 3]) << 8)
            snapshot.positions_rad[index] = raw_position_to_rad(raw_pos)
            snapshot.velocities_rad_s[index] = raw_speed_to_rad_s(raw_speed)

    def read_extended_into(self, snapshot: ServoSnapshot, servo_id: int) -> None:
        if servo_id not in self.ids:
            raise KeyError(f"unknown servo id: {servo_id}")
        start_ns = clock_ns()
        index = int(self._id_to_index[servo_id])
        request = self._extended_read_packets[index]
        self._flush_before_transaction()
        try:
            self.transport.write(request)
        except (OSError, TimeoutError):
            snapshot.extended_status = ErrorCode.IO
            snapshot.extended_round_trip_ns = clock_ns() - start_ns
            return
        self._collect_packets(
            expected_param_length=11,
            deadline_ns=start_ns + self.transaction_timeout_ns,
            only_servo_id=servo_id,
        )
        snapshot.partial_bytes += self._rx_length
        snapshot.unexpected_packets += self._unexpected_packets
        code = ErrorCode(int(self._read_codes[index]))
        snapshot.extended_status = code
        snapshot.extended_servo_id = servo_id
        snapshot.extended_round_trip_ns = clock_ns() - start_ns
        if code is not ErrorCode.OK:
            return
        row = self._read_data[index]
        current_raw = int(row[9]) | (int(row[10]) << 8)
        snapshot.present_current_raw = current_raw
        snapshot.present_current_a = current_raw * 0.0065
        snapshot.present_voltage_v = int(row[2]) * 0.1
        snapshot.present_temperature_c = float(row[3])

    def exchange_into(
        self, positions_rad: np.ndarray, snapshot: ServoSnapshot, tick_index: int
    ) -> None:
        snapshot.begin_tick()
        bus_start_ns = clock_ns()
        snapshot.write_status = self.write_positions(positions_rad)
        self.read_state_into(snapshot)
        self.read_extended_into(snapshot, self.ids[tick_index % ACTION_DIM])
        snapshot.bus_total_ns = clock_ns() - bus_start_ns

    def _reset_read_state(self, only_servo_id: int | None) -> None:
        self._read_lengths.fill(0)
        self._read_seen.fill(False)
        self._read_codes.fill(int(ErrorCode.TIMEOUT))
        if only_servo_id is not None:
            for index, servo_id in enumerate(self.ids):
                if servo_id != only_servo_id:
                    self._read_codes[index] = int(ErrorCode.UNEXPECTED_ID)

    def _collect_packets(
        self, *, expected_param_length: int, deadline_ns: int, only_servo_id: int | None = None
    ) -> None:
        self._reset_read_state(only_servo_id)
        expected_count = 1 if only_servo_id is not None else ACTION_DIM
        received_count = 0
        self._rx_length = 0
        self._unexpected_packets = 0
        while received_count < expected_count and clock_ns() < deadline_ns:
            if self._rx_length >= len(self._rx):
                break
            count = self.transport.read_some_into(
                self._rx_view[self._rx_length :], deadline_ns
            )
            if count <= 0:
                break
            self._rx_length += count
            consumed, newly_received = self._parse_available(
                expected_param_length=expected_param_length, only_servo_id=only_servo_id
            )
            received_count += newly_received
            if consumed:
                remaining = self._rx_length - consumed
                if remaining:
                    self._rx[:remaining] = self._rx[consumed : self._rx_length]
                self._rx_length = remaining

        if self._rx_length >= 4 and self._rx[0] == 0xFF and self._rx[1] == 0xFF:
            servo_id = int(self._rx[2])
            if servo_id < len(self._id_to_index):
                index = int(self._id_to_index[servo_id])
                if index >= 0 and not self._read_seen[index]:
                    self._read_codes[index] = int(ErrorCode.PARTIAL)

    def _parse_available(
        self, *, expected_param_length: int, only_servo_id: int | None
    ) -> tuple[int, int]:
        cursor = 0
        newly_received = 0
        while cursor + 4 <= self._rx_length:
            header = self._rx.find(b"\xff\xff", cursor, self._rx_length)
            if header < 0:
                return max(0, self._rx_length - 1), newly_received
            if header + 4 > self._rx_length:
                return header, newly_received
            packet_length = int(self._rx[header + 3])
            total_length = 4 + packet_length
            if packet_length < 2 or total_length > 64:
                cursor = header + 1
                continue
            if header + total_length > self._rx_length:
                return header, newly_received
            servo_id = int(self._rx[header + 2])
            index = int(self._id_to_index[servo_id]) if servo_id < 254 else -1
            frame = self._rx_view[header : header + total_length]
            if index < 0 or (only_servo_id is not None and servo_id != only_servo_id):
                self._unexpected_packets += 1
                cursor = header + total_length
                continue
            self._read_seen[index] = True
            if checksum(frame[2:-1]) != int(frame[-1]):
                self._read_codes[index] = int(ErrorCode.CRC)
            elif int(frame[4]) != 0:
                self._read_codes[index] = int(ErrorCode.DEVICE)
            elif total_length - 6 != expected_param_length:
                self._read_codes[index] = int(ErrorCode.PARTIAL)
            else:
                for data_index in range(expected_param_length):
                    self._read_data[index, data_index] = frame[5 + data_index]
                self._read_lengths[index] = expected_param_length
                if self._read_codes[index] != int(ErrorCode.OK):
                    newly_received += 1
                self._read_codes[index] = int(ErrorCode.OK)
            cursor = header + total_length
        return cursor, newly_received

    def ping(self, servo_id: int, *, timeout_s: float | None = None) -> ErrorCode:
        if not 0 <= servo_id <= 253:
            raise ValueError("servo id must be in 0..253")
        self._flush_before_transaction()
        try:
            self.transport.write(instruction_packet(servo_id, PING))
        except (OSError, TimeoutError):
            return ErrorCode.IO
        timeout_ns = self.transaction_timeout_ns if timeout_s is None else int(timeout_s * 1e9)
        code, _ = self._read_one_generic(servo_id, 0, clock_ns() + timeout_ns)
        return code

    def write_register(self, servo_id: int, address: int, data: bytes) -> ErrorCode:
        self._flush_before_transaction()
        try:
            self.transport.write(instruction_packet(servo_id, WRITE, bytes((address,)) + data))
        except (OSError, TimeoutError):
            return ErrorCode.IO
        status, _ = self._read_one_generic(
            servo_id,
            0,
            clock_ns() + self.transaction_timeout_ns,
        )
        return status

    def read_register(self, servo_id: int, address: int, length: int) -> tuple[ErrorCode, bytes]:
        self._flush_before_transaction()
        try:
            self.transport.write(instruction_packet(servo_id, READ, bytes((address, length))))
        except (OSError, TimeoutError):
            return ErrorCode.IO, b""
        return self._read_one_generic(
            servo_id, length, clock_ns() + self.transaction_timeout_ns
        )

    def _read_one_generic(
        self, servo_id: int, expected_param_length: int, deadline_ns: int
    ) -> tuple[ErrorCode, bytes]:
        buffer = bytearray(64)
        view = memoryview(buffer)
        received = 0
        while clock_ns() < deadline_ns:
            count = self.transport.read_some_into(view[received:], deadline_ns)
            if count <= 0:
                break
            received += count
            header = buffer.find(b"\xff\xff", 0, received)
            if header < 0:
                if received == len(buffer):
                    return ErrorCode.PARTIAL, b""
                continue
            if received < header + 4:
                continue
            packet_length = int(buffer[header + 3])
            total = 4 + packet_length
            if packet_length < 2 or total > len(buffer):
                return ErrorCode.PARTIAL, b""
            if received < header + total:
                continue
            frame = view[header : header + total]
            if int(frame[2]) != servo_id:
                return ErrorCode.UNEXPECTED_ID, b""
            if checksum(frame[2:-1]) != int(frame[-1]):
                return ErrorCode.CRC, b""
            if int(frame[4]) != 0:
                return ErrorCode.DEVICE, b""
            if total - 6 != expected_param_length:
                return ErrorCode.PARTIAL, b""
            return ErrorCode.OK, bytes(frame[5:-1])
        return (ErrorCode.PARTIAL if received else ErrorCode.TIMEOUT), b""

    def sync_write_bytes(self, address: int, values: Sequence[bytes]) -> ErrorCode:
        if len(values) != ACTION_DIM:
            raise ValueError(f"expected {ACTION_DIM} values")
        width = len(values[0])
        if width < 1 or any(len(value) != width for value in values):
            raise ValueError("all sync-write values must have the same nonzero width")
        payload = bytearray(ACTION_DIM * (width + 1))
        cursor = 0
        for servo_id, value in zip(self.ids, values, strict=True):
            payload[cursor] = servo_id
            payload[cursor + 1 : cursor + 1 + width] = value
            cursor += width + 1
        frame = instruction_packet(BROADCAST_ID, 0x83, bytes((address, width)) + payload)
        try:
            self.transport.write(frame)
            return ErrorCode.OK
        except (OSError, TimeoutError):
            return ErrorCode.IO

    def set_torque(self, enabled: bool) -> ErrorCode:
        value = bytes((1 if enabled else 0,))
        return self.sync_write_bytes(ADDR_TORQUE_ENABLE, [value] * ACTION_DIM)

    def disable_torque(self) -> ErrorCode:
        return self.set_torque(False)

    def enable_torque(self) -> ErrorCode:
        return self.set_torque(True)

    def set_gains(self, p: int, i: int = 0, d: int = 0) -> ErrorCode:
        for value, label in ((p, "p"), (i, "i"), (d, "d")):
            if not 0 <= value <= 255:
                raise ValueError(f"{label} coefficient must be in 0..255")
        # Register order is P, D, I at addresses 21, 22, 23.
        packed = bytes((p, d, i))
        return self.sync_write_bytes(ADDR_P_COEFFICIENT, [packed] * ACTION_DIM)

    def set_gain_vectors(
        self, p: Sequence[int], i: Sequence[int] | None = None, d: Sequence[int] | None = None
    ) -> ErrorCode:
        if len(p) != ACTION_DIM:
            raise ValueError(f"p must contain {ACTION_DIM} coefficients")
        i_values = (0,) * ACTION_DIM if i is None else i
        d_values = (0,) * ACTION_DIM if d is None else d
        if len(i_values) != ACTION_DIM or len(d_values) != ACTION_DIM:
            raise ValueError("i and d must contain 14 coefficients")
        packed: list[bytes] = []
        for p_value, i_value, d_value in zip(p, i_values, d_values, strict=True):
            if not all(0 <= int(value) <= 255 for value in (p_value, i_value, d_value)):
                raise ValueError("gain coefficients must be in 0..255")
            packed.append(bytes((int(p_value), int(d_value), int(i_value))))
        return self.sync_write_bytes(ADDR_P_COEFFICIENT, packed)
