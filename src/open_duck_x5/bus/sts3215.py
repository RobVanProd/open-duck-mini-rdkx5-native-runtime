from __future__ import annotations

import math
import struct
from collections.abc import Sequence

import numpy as np

from ..clock import clock_ns
from ..constants import ACTION_DIM, SERVO_IDS, SERVO_SYNC_READ_IDS, TWO_PI
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

ADDR_MODEL = 3
ADDR_ID = 5
ADDR_MAX_INPUT_VOLTAGE = 14
ADDR_MIN_INPUT_VOLTAGE = 15
ADDR_P_COEFFICIENT = 21
ADDR_TORQUE_ENABLE = 40
ADDR_ACCELERATION = 41
ADDR_GOAL_POSITION = 42
ADDR_LOCK = 55
ADDR_PRESENT_POSITION = 56
ADDR_PRESENT_LOAD = 60
ADDR_PRESENT_VOLTAGE = 62
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
        device: str = "/dev/ttyS1",
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
        self._sync_read_wire_indices = tuple(
            self.ids.index(servo_id) for servo_id in SERVO_SYNC_READ_IDS
        )

        self._sync_read_state = sync_read_packet(SERVO_SYNC_READ_IDS, ADDR_PRESENT_POSITION, 4)
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
        self._read_device_status = np.zeros(ACTION_DIM, dtype=np.uint8)
        self._unexpected_packets = 0
        # A four-byte all-servo SyncRead returns fourteen fixed ten-byte status
        # packets.  Keep receive-chunk boundaries preallocated so the common
        # path can collect the complete response train before parsing it while
        # still retaining per-response instrumentation timestamps.
        self._rx_chunk_end = np.zeros(len(self._rx), dtype=np.int64)
        self._rx_chunk_time_ns = np.zeros(len(self._rx), dtype=np.int64)
        self._rx_chunk_count = 0
        self._group_state_decoded = False

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
        self._group_state_decoded = False
        if snapshot.instrumentation_enabled:
            snapshot.trace_group_start_ns = start_ns
            snapshot.trace_group_flush_start_ns = start_ns
        self._flush_before_transaction()
        if snapshot.instrumentation_enabled:
            snapshot.trace_group_flush_end_ns = clock_ns()
            snapshot.trace_group_write_start_ns = clock_ns()
        try:
            self.transport.write(self._sync_read_state)
        except (OSError, TimeoutError):
            now_ns = clock_ns()
            if snapshot.instrumentation_enabled:
                snapshot.trace_group_write_end_ns = now_ns
                snapshot.trace_group_end_ns = now_ns
            snapshot.status.fill(int(ErrorCode.IO))
            snapshot.device_status.fill(0)
            snapshot.stale.fill(True)
            snapshot.group_round_trip_ns = now_ns - start_ns
            return
        write_end_ns = clock_ns()
        if snapshot.instrumentation_enabled:
            snapshot.trace_group_write_end_ns = write_end_ns
        self._collect_sync_read_burst(
            expected_param_length=4,
            # The response timeout governs response collection.  Starting it
            # before reset_input_buffer() and request transmission silently
            # stole part of the four-millisecond receive budget from late IDs.
            deadline_ns=write_end_ns + self.transaction_timeout_ns,
            snapshot=snapshot,
        )
        now_ns = clock_ns()
        if snapshot.instrumentation_enabled:
            snapshot.trace_group_end_ns = now_ns
        snapshot.group_round_trip_ns = now_ns - start_ns
        snapshot.sample_time_ns = now_ns
        snapshot.status[:] = self._read_codes
        snapshot.device_status[:] = self._read_device_status
        snapshot.stale[:] = self._read_codes != int(ErrorCode.OK)
        snapshot.partial_bytes += self._rx_length
        snapshot.unexpected_packets += self._unexpected_packets
        if not self._group_state_decoded:
            self._decode_group_state(snapshot)

    def _decode_group_state(self, snapshot: ServoSnapshot) -> None:
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
        if snapshot.instrumentation_enabled:
            snapshot.trace_extended_start_ns = start_ns
            snapshot.trace_extended_flush_start_ns = start_ns
        index = int(self._id_to_index[servo_id])
        snapshot.extended_servo_id = servo_id
        request = self._extended_read_packets[index]
        self._flush_before_transaction()
        if snapshot.instrumentation_enabled:
            snapshot.trace_extended_flush_end_ns = clock_ns()
            snapshot.trace_extended_write_start_ns = clock_ns()
        try:
            self.transport.write(request)
        except (OSError, TimeoutError):
            now_ns = clock_ns()
            if snapshot.instrumentation_enabled:
                snapshot.trace_extended_write_end_ns = now_ns
                snapshot.trace_extended_end_ns = now_ns
            snapshot.extended_status = ErrorCode.IO
            snapshot.extended_device_status = 0
            snapshot.extended_round_trip_ns = now_ns - start_ns
            return
        write_end_ns = clock_ns()
        if snapshot.instrumentation_enabled:
            snapshot.trace_extended_write_end_ns = write_end_ns
        self._collect_packets(
            expected_param_length=11,
            deadline_ns=write_end_ns + self.transaction_timeout_ns,
            only_servo_id=servo_id,
            snapshot=snapshot,
        )
        now_ns = clock_ns()
        snapshot.partial_bytes += self._rx_length
        snapshot.unexpected_packets += self._unexpected_packets
        code = ErrorCode(int(self._read_codes[index]))
        snapshot.extended_status = code
        snapshot.extended_device_status = int(self._read_device_status[index])
        snapshot.extended_round_trip_ns = now_ns - start_ns
        if snapshot.instrumentation_enabled:
            snapshot.trace_extended_end_ns = now_ns
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
        if snapshot.instrumentation_enabled:
            snapshot.trace_bus_start_ns = bus_start_ns
            snapshot.trace_write_start_ns = clock_ns()
        snapshot.write_status = self.write_positions(positions_rad)
        if snapshot.instrumentation_enabled:
            snapshot.trace_write_end_ns = clock_ns()
        self.read_state_into(snapshot)
        self.read_extended_into(snapshot, self.ids[tick_index % ACTION_DIM])
        bus_end_ns = clock_ns()
        snapshot.bus_total_ns = bus_end_ns - bus_start_ns
        if snapshot.instrumentation_enabled:
            snapshot.trace_bus_end_ns = bus_end_ns

    def _reset_read_state(self, only_servo_id: int | None) -> None:
        self._read_lengths.fill(0)
        self._read_seen.fill(False)
        self._read_codes.fill(int(ErrorCode.TIMEOUT))
        self._read_device_status.fill(0)
        if only_servo_id is not None:
            for index, servo_id in enumerate(self.ids):
                if servo_id != only_servo_id:
                    self._read_codes[index] = int(ErrorCode.UNEXPECTED_ID)

    def _collect_packets(
        self,
        *,
        expected_param_length: int,
        deadline_ns: int,
        snapshot: ServoSnapshot,
        only_servo_id: int | None = None,
    ) -> None:
        self._reset_read_state(only_servo_id)
        expected_count = 1 if only_servo_id is not None else ACTION_DIM
        received_count = 0
        self._rx_length = 0
        self._unexpected_packets = 0
        while received_count < expected_count and clock_ns() < deadline_ns:
            if self._rx_length >= len(self._rx):
                break
            count = self.transport.read_some_into(self._rx_view[self._rx_length :], deadline_ns)
            if count <= 0:
                break
            completed_ns = clock_ns()
            if completed_ns >= deadline_ns:
                break
            receive_ns = completed_ns if snapshot.instrumentation_enabled else 0
            if snapshot.instrumentation_enabled:
                if only_servo_id is None:
                    if snapshot.trace_group_first_rx_ns == 0:
                        snapshot.trace_group_first_rx_ns = receive_ns
                    snapshot.trace_group_last_rx_ns = receive_ns
                    snapshot.trace_group_read_calls += 1
                else:
                    if snapshot.trace_extended_first_rx_ns == 0:
                        snapshot.trace_extended_first_rx_ns = receive_ns
                    snapshot.trace_extended_last_rx_ns = receive_ns
                    snapshot.trace_extended_read_calls += 1
            self._rx_length += count
            consumed, newly_seen = self._parse_available(
                expected_param_length=expected_param_length,
                only_servo_id=only_servo_id,
                completion_ns=receive_ns,
                response_complete_ns=(
                    snapshot.trace_group_response_complete_ns
                    if snapshot.instrumentation_enabled and only_servo_id is None
                    else None
                ),
            )
            received_count += newly_seen
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

    def _collect_sync_read_burst(
        self,
        *,
        expected_param_length: int,
        deadline_ns: int,
        snapshot: ServoSnapshot,
    ) -> None:
        """Collect one fixed-size SyncRead response train, then parse it once.

        Feetech SyncRead returns one fixed-length status packet for every ID in
        request order.  The normal path therefore knows the exact byte count in
        advance.  Parsing and compacting after every short nonblocking read made
        Python processing part of the inter-servo receive timing and consumed
        the deadline while later responses were already arriving.

        The common path below performs no packet parsing until the complete
        expected train has reached the preallocated buffer.  Only an anomalous
        train (unexpected/duplicate bytes or a missing requested ID) enters the
        bounded incremental recovery path.
        """

        self._reset_read_state(None)
        expected_packet_length = expected_param_length + 6
        expected_bytes = expected_packet_length * ACTION_DIM
        self._rx_length = 0
        self._unexpected_packets = 0
        self._rx_chunk_count = 0
        stream_received = 0
        stream_base_offset = 0

        while stream_received < expected_bytes and clock_ns() < deadline_ns:
            count = self.transport.read_some_into(
                self._rx_view[self._rx_length : expected_bytes], deadline_ns
            )
            if count <= 0:
                break
            completed_ns = clock_ns()
            if completed_ns >= deadline_ns:
                break
            receive_ns = completed_ns if snapshot.instrumentation_enabled else 0
            self._rx_length += count
            stream_received += count
            self._record_group_receive(snapshot, stream_received, receive_ns)

        self._record_group_parse(snapshot)
        exact_train = self._parse_exact_sync_read_train(snapshot)
        if exact_train:
            consumed, seen_count = expected_bytes, ACTION_DIM
            if snapshot.instrumentation_enabled:
                snapshot.trace_group_parser_mode = 1
        else:
            if snapshot.instrumentation_enabled:
                snapshot.trace_group_parser_mode = 2
            consumed, seen_count = self._parse_available(
                expected_param_length=expected_param_length,
                only_servo_id=None,
                response_complete_ns=(
                    snapshot.trace_group_response_complete_ns
                    if snapshot.instrumentation_enabled
                    else None
                ),
                stream_base_offset=stream_base_offset,
            )
        if consumed:
            remaining = self._rx_length - consumed
            if remaining:
                self._rx[:remaining] = self._rx[consumed : self._rx_length]
            self._rx_length = remaining
            stream_base_offset += consumed

        # Rare bounded recovery: an unexpected or duplicate packet can occupy
        # part of the expected-length prefix.  Continue only until every
        # requested ID has been seen or the same absolute deadline expires.
        while seen_count < ACTION_DIM and clock_ns() < deadline_ns:
            if self._rx_length >= len(self._rx):
                break
            count = self.transport.read_some_into(self._rx_view[self._rx_length :], deadline_ns)
            if count <= 0:
                break
            completed_ns = clock_ns()
            if completed_ns >= deadline_ns:
                break
            receive_ns = completed_ns if snapshot.instrumentation_enabled else 0
            self._rx_length += count
            stream_received += count
            self._record_group_receive(snapshot, stream_received, receive_ns)
            self._record_group_parse(snapshot)
            consumed, newly_seen = self._parse_available(
                expected_param_length=expected_param_length,
                only_servo_id=None,
                response_complete_ns=(
                    snapshot.trace_group_response_complete_ns
                    if snapshot.instrumentation_enabled
                    else None
                ),
                stream_base_offset=stream_base_offset,
            )
            seen_count += newly_seen
            if consumed:
                remaining = self._rx_length - consumed
                if remaining:
                    self._rx[:remaining] = self._rx[consumed : self._rx_length]
                self._rx_length = remaining
                stream_base_offset += consumed

        if self._rx_length >= 4 and self._rx[0] == 0xFF and self._rx[1] == 0xFF:
            servo_id = int(self._rx[2])
            if servo_id < len(self._id_to_index):
                index = int(self._id_to_index[servo_id])
                if index >= 0 and not self._read_seen[index]:
                    self._read_codes[index] = int(ErrorCode.PARTIAL)

    def _parse_exact_sync_read_train(self, snapshot: ServoSnapshot) -> bool:
        """Parse the normal ordered 14 x 10-byte state train without scanning.

        Structure is validated before state is mutated. Any order, header, or
        length anomaly falls back to the generic ID-routing parser. A
        structurally valid train retains per-servo CRC classification while
        decoding fresh position and speed directly into the snapshot.
        """

        if self._rx_length != ACTION_DIM * 10:
            return False
        for wire_index, servo_id in enumerate(SERVO_SYNC_READ_IDS):
            offset = wire_index * 10
            if (
                self._rx[offset] != 0xFF
                or self._rx[offset + 1] != 0xFF
                or self._rx[offset + 2] != servo_id
                or self._rx[offset + 3] != 6
            ):
                return False

        completion_times = (
            snapshot.trace_group_response_complete_ns if snapshot.instrumentation_enabled else None
        )
        for wire_index, logical_index in enumerate(self._sync_read_wire_indices):
            offset = wire_index * 10
            self._read_seen[logical_index] = True
            if completion_times is not None:
                completion_times[logical_index] = self._completion_time_for_stream_offset(
                    offset + 10
                )
            expected_checksum = (
                ~(
                    self._rx[offset + 2]
                    + self._rx[offset + 3]
                    + self._rx[offset + 4]
                    + self._rx[offset + 5]
                    + self._rx[offset + 6]
                    + self._rx[offset + 7]
                    + self._rx[offset + 8]
                )
            ) & 0xFF
            if expected_checksum != self._rx[offset + 9]:
                self._read_codes[logical_index] = int(ErrorCode.CRC)
                continue

            self._read_lengths[logical_index] = 4
            self._read_device_status[logical_index] = self._rx[offset + 4]
            self._read_codes[logical_index] = int(ErrorCode.OK)
            raw_position = self._rx[offset + 5] | (self._rx[offset + 6] << 8)
            if raw_position >= 0x8000:
                raw_position -= 0x10000
            raw_speed = self._rx[offset + 7] | (self._rx[offset + 8] << 8)
            snapshot.positions_rad[logical_index] = raw_position_to_rad(raw_position)
            snapshot.velocities_rad_s[logical_index] = raw_speed_to_rad_s(raw_speed)

        self._group_state_decoded = True
        return True

    def _record_group_receive(
        self, snapshot: ServoSnapshot, stream_end_offset: int, receive_ns: int
    ) -> None:
        if not snapshot.instrumentation_enabled:
            return
        if snapshot.trace_group_first_rx_ns == 0:
            snapshot.trace_group_first_rx_ns = receive_ns
        snapshot.trace_group_last_rx_ns = receive_ns
        snapshot.trace_group_read_calls += 1
        if self._rx_chunk_count < len(self._rx_chunk_end):
            self._rx_chunk_end[self._rx_chunk_count] = stream_end_offset
            self._rx_chunk_time_ns[self._rx_chunk_count] = receive_ns
            self._rx_chunk_count += 1

    def _record_group_parse(self, snapshot: ServoSnapshot) -> None:
        if not snapshot.instrumentation_enabled:
            return
        snapshot.trace_group_parse_calls += 1
        if snapshot.trace_group_parse_calls == 1:
            snapshot.trace_group_first_parse_bytes = self._rx_length

    def _completion_time_for_stream_offset(self, stream_end_offset: int) -> int:
        for index in range(self._rx_chunk_count):
            if int(self._rx_chunk_end[index]) >= stream_end_offset:
                return int(self._rx_chunk_time_ns[index])
        return 0

    def _parse_available(
        self,
        *,
        expected_param_length: int,
        only_servo_id: int | None,
        completion_ns: int = 0,
        response_complete_ns: np.ndarray | None = None,
        stream_base_offset: int = 0,
    ) -> tuple[int, int]:
        cursor = 0
        newly_seen = 0
        while cursor + 4 <= self._rx_length:
            header = self._rx.find(b"\xff\xff", cursor, self._rx_length)
            if header < 0:
                return max(0, self._rx_length - 1), newly_seen
            if header + 4 > self._rx_length:
                return header, newly_seen
            packet_length = int(self._rx[header + 3])
            total_length = 4 + packet_length
            if packet_length < 2 or total_length > 64:
                cursor = header + 1
                continue
            if header + total_length > self._rx_length:
                return header, newly_seen
            servo_id = int(self._rx[header + 2])
            index = int(self._id_to_index[servo_id]) if servo_id < 254 else -1
            frame = self._rx_view[header : header + total_length]
            if index < 0 or (only_servo_id is not None and servo_id != only_servo_id):
                self._unexpected_packets += 1
                cursor = header + total_length
                continue
            first_seen = not bool(self._read_seen[index])
            self._read_seen[index] = True
            if first_seen and response_complete_ns is not None:
                frame_end_offset = stream_base_offset + header + total_length
                response_complete_ns[index] = (
                    completion_ns
                    if completion_ns
                    else self._completion_time_for_stream_offset(frame_end_offset)
                )
            if first_seen:
                newly_seen += 1
            if checksum(frame[2:-1]) != int(frame[-1]):
                self._read_codes[index] = int(ErrorCode.CRC)
            elif total_length - 6 != expected_param_length:
                self._read_codes[index] = int(ErrorCode.PARTIAL)
            else:
                for data_index in range(expected_param_length):
                    self._read_data[index, data_index] = frame[5 + data_index]
                self._read_lengths[index] = expected_param_length
                self._read_device_status[index] = int(frame[4])
                self._read_codes[index] = int(ErrorCode.OK)
            cursor = header + total_length
        return cursor, newly_seen

    def ping(self, servo_id: int, *, timeout_s: float | None = None) -> ErrorCode:
        code, device_status = self.ping_with_device_status(servo_id, timeout_s=timeout_s)
        if code is ErrorCode.OK and device_status:
            return ErrorCode.DEVICE
        return code

    def ping_with_device_status(
        self, servo_id: int, *, timeout_s: float | None = None
    ) -> tuple[ErrorCode, int | None]:
        if not 0 <= servo_id <= 253:
            raise ValueError("servo id must be in 0..253")
        self._flush_before_transaction()
        try:
            self.transport.write(instruction_packet(servo_id, PING))
        except (OSError, TimeoutError):
            return ErrorCode.IO, None
        timeout_ns = self.transaction_timeout_ns if timeout_s is None else int(timeout_s * 1e9)
        code, device_status, _ = self._read_one_generic_with_device_status(
            servo_id, 0, clock_ns() + timeout_ns
        )
        return code, device_status

    def write_register(self, servo_id: int, address: int, data: bytes) -> ErrorCode:
        status, device_status = self.write_register_with_device_status(servo_id, address, data)
        if status is ErrorCode.OK and device_status:
            return ErrorCode.DEVICE
        return status

    def write_register_with_device_status(
        self, servo_id: int, address: int, data: bytes
    ) -> tuple[ErrorCode, int | None]:
        """Write a register while keeping transport and device status separate.

        Configuration writes sometimes need to clear the condition currently
        asserted in the device-status byte.  Treating that alarm as a transport
        failure makes a verified, fail-closed repair impossible.  This method
        still requires a checksum-valid, correctly sized acknowledgement; it
        merely returns the alarm byte to the caller instead of collapsing it
        into :class:`ErrorCode.DEVICE`.
        """

        self._flush_before_transaction()
        try:
            self.transport.write(instruction_packet(servo_id, WRITE, bytes((address,)) + data))
        except (OSError, TimeoutError):
            return ErrorCode.IO, None
        status, device_status, _ = self._read_one_generic_with_device_status(
            servo_id,
            0,
            clock_ns() + self.transaction_timeout_ns,
        )
        return status, device_status

    def read_register(self, servo_id: int, address: int, length: int) -> tuple[ErrorCode, bytes]:
        self._flush_before_transaction()
        try:
            self.transport.write(instruction_packet(servo_id, READ, bytes((address, length))))
        except (OSError, TimeoutError):
            return ErrorCode.IO, b""
        return self._read_one_generic(servo_id, length, clock_ns() + self.transaction_timeout_ns)

    def read_register_with_device_status(
        self, servo_id: int, address: int, length: int
    ) -> tuple[ErrorCode, int | None, bytes]:
        """Read a register and report transport status separately from device alarms.

        A checksum-valid, correctly sized response is ``OK`` even when its device
        status byte is nonzero. Callers must handle that byte explicitly. The
        normal ``read_register`` path remains fail-closed and maps a nonzero
        device status to ``DEVICE`` while discarding its parameters.
        """
        self._flush_before_transaction()
        try:
            self.transport.write(instruction_packet(servo_id, READ, bytes((address, length))))
        except (OSError, TimeoutError):
            return ErrorCode.IO, None, b""
        return self._read_one_generic_with_device_status(
            servo_id, length, clock_ns() + self.transaction_timeout_ns
        )

    def _read_one_generic(
        self, servo_id: int, expected_param_length: int, deadline_ns: int
    ) -> tuple[ErrorCode, bytes]:
        code, device_status, parameters = self._read_one_generic_with_device_status(
            servo_id, expected_param_length, deadline_ns
        )
        if code is not ErrorCode.OK:
            return code, b""
        if device_status:
            return ErrorCode.DEVICE, b""
        return ErrorCode.OK, parameters

    def _read_one_generic_with_device_status(
        self, servo_id: int, expected_param_length: int, deadline_ns: int
    ) -> tuple[ErrorCode, int | None, bytes]:
        buffer = bytearray(64)
        view = memoryview(buffer)
        received = 0
        while clock_ns() < deadline_ns:
            count = self.transport.read_some_into(view[received:], deadline_ns)
            if count <= 0:
                break
            if clock_ns() >= deadline_ns:
                break
            received += count
            header = buffer.find(b"\xff\xff", 0, received)
            if header < 0:
                if received == len(buffer):
                    return ErrorCode.PARTIAL, None, b""
                continue
            if received < header + 4:
                continue
            packet_length = int(buffer[header + 3])
            total = 4 + packet_length
            if packet_length < 2 or total > len(buffer):
                return ErrorCode.PARTIAL, None, b""
            if received < header + total:
                continue
            frame = view[header : header + total]
            if int(frame[2]) != servo_id:
                return ErrorCode.UNEXPECTED_ID, None, b""
            if checksum(frame[2:-1]) != int(frame[-1]):
                return ErrorCode.CRC, None, b""
            device_error = int(frame[4])
            parameters = bytes(frame[5:-1])
            if total - 6 != expected_param_length:
                return ErrorCode.PARTIAL, 0, b""
            return ErrorCode.OK, device_error, parameters
        return (ErrorCode.PARTIAL if received else ErrorCode.TIMEOUT), None, b""

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
