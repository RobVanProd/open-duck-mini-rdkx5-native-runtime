from __future__ import annotations

import math
import struct
import time

import numpy as np

from open_duck_x5.bus.protocol import checksum
from open_duck_x5.bus.sts3215 import (
    ADDR_PRESENT_LOAD,
    STS3215Bus,
    rad_to_raw_position,
    raw_position_to_rad,
    raw_speed_to_rad_s,
)
from open_duck_x5.bus.types import ErrorCode, ServoSnapshot
from open_duck_x5.constants import HOME_RAD, SERVO_IDS, SERVO_SYNC_READ_IDS


def _status_packet(servo_id: int, parameters: bytes, *, error: int = 0) -> bytes:
    body = bytes((servo_id, len(parameters) + 2, error)) + parameters
    return b"\xff\xff" + body + bytes((checksum(body),))


class FakeTransport:
    def __init__(
        self,
        *,
        corrupt_id: int | None = None,
        partial_id: int | None = None,
        include_unexpected: bool = False,
        device_error: int = 0,
        read_chunk_size: int = 23,
        response_order: tuple[int, ...] | None = None,
        omit_ids: tuple[int, ...] = (),
    ) -> None:
        self.corrupt_id = corrupt_id
        self.partial_id = partial_id
        self.include_unexpected = include_unexpected
        self.device_error = int(device_error)
        self.read_chunk_size = int(read_chunk_size)
        self.response_order = response_order
        self.omit_ids = omit_ids
        self.rx = bytearray()
        self.writes: list[bytes] = []
        self.sync_read_response_orders: list[tuple[int, ...]] = []
        self.read_calls = 0
        self.closed = False

    def write(self, data) -> None:
        frame = bytes(data)
        self.writes.append(frame)
        instruction = frame[4]
        if instruction == 0x82:
            requested_ids = tuple(frame[7:-1])
            self.sync_read_response_orders.append(requested_ids)
            packets: list[bytes] = []
            if self.include_unexpected:
                packets.append(_status_packet(99, b"\x00\x08\x00\x00"))
            partial = b""
            response_ids = requested_ids if self.response_order is None else self.response_order
            for servo_id in response_ids:
                if servo_id in self.omit_ids:
                    continue
                index = SERVO_IDS.index(servo_id)
                parameters = struct.pack("<HH", 2048 + index, 100)
                packet = _status_packet(servo_id, parameters, error=self.device_error)
                if servo_id == self.corrupt_id:
                    packet = packet[:-1] + bytes((packet[-1] ^ 1,))
                if servo_id == self.partial_id:
                    partial = packet[:4]
                else:
                    packets.append(packet)
            self.rx.extend(b"".join(packets) + partial)
        elif instruction == 0x02 and frame[5] == ADDR_PRESENT_LOAD:
            servo_id = frame[2]
            parameters = bytes((0, 0, 74, 28, 0, 0, 0, 0, 0, 18, 0))
            self.rx.extend(_status_packet(servo_id, parameters, error=self.device_error))
        elif instruction == 0x03 and frame[2] != 0xFE:
            self.rx.extend(_status_packet(frame[2], b"", error=self.device_error))

    def read_some_into(self, target, deadline_ns: int) -> int:
        del deadline_ns
        self.read_calls += 1
        if not self.rx:
            return 0
        count = min(len(target), len(self.rx), self.read_chunk_size)
        target[:count] = self.rx[:count]
        del self.rx[:count]
        return count

    def flush_input(self) -> None:
        self.rx.clear()

    def close(self) -> None:
        self.closed = True


def test_position_and_speed_conversions_match_inherited_binding() -> None:
    assert raw_position_to_rad(2048) == 0.0
    assert rad_to_raw_position(0.0) == 2048
    assert rad_to_raw_position(-math.pi) == 0
    assert rad_to_raw_position(math.pi) == 4096
    assert raw_speed_to_rad_s(0) == 0.0
    assert raw_speed_to_rad_s(32769) < 0.0


def test_direct_bus_group_read_sync_write_and_extended_telemetry() -> None:
    transport = FakeTransport()
    bus = STS3215Bus(transport=transport)
    snapshot = ServoSnapshot.create()
    snapshot.begin_tick()

    assert bus.write_positions(HOME_RAD) is ErrorCode.OK
    write_frame = transport.writes[-1]
    assert write_frame[:7] == bytes.fromhex("ff ff fe 2e 83 2a 02")
    assert checksum(write_frame[2:-1]) == write_frame[-1]

    bus.read_state_into(snapshot)
    read_frame = transport.writes[-1]
    assert read_frame[4] == 0x82
    assert tuple(read_frame[7:-1]) == SERVO_SYNC_READ_IDS
    assert transport.sync_read_response_orders[-1] == SERVO_SYNC_READ_IDS
    assert snapshot.all_fresh
    assert np.all(snapshot.status == int(ErrorCode.OK))
    assert snapshot.positions_rad[0] == 0.0
    assert snapshot.positions_rad[-1] > snapshot.positions_rad[0]
    assert np.all(snapshot.velocities_rad_s > 0.0)

    bus.read_extended_into(snapshot, SERVO_IDS[3])
    assert snapshot.extended_status is ErrorCode.OK
    assert snapshot.extended_servo_id == SERVO_IDS[3]
    assert snapshot.present_current_raw == 18
    assert snapshot.present_current_a == 18 * 0.0065
    assert snapshot.present_voltage_v == 7.4
    assert snapshot.present_temperature_c == 28.0
    assert bus.write_register(SERVO_IDS[0], 21, b"\x1e") is ErrorCode.OK


def test_instrumented_exchange_captures_preallocated_stage_boundaries() -> None:
    bus = STS3215Bus(transport=FakeTransport())
    snapshot = ServoSnapshot.create()
    snapshot.instrumentation_enabled = True

    bus.exchange_into(HOME_RAD, snapshot, 0)

    assert snapshot.trace_bus_start_ns <= snapshot.trace_write_start_ns
    assert snapshot.trace_write_start_ns <= snapshot.trace_write_end_ns
    assert snapshot.trace_write_end_ns <= snapshot.trace_group_start_ns
    assert snapshot.trace_group_write_end_ns <= snapshot.trace_group_first_rx_ns
    assert snapshot.trace_group_first_rx_ns <= snapshot.trace_group_last_rx_ns
    assert snapshot.trace_group_last_rx_ns <= snapshot.trace_group_end_ns
    assert snapshot.trace_group_end_ns <= snapshot.trace_extended_start_ns
    assert snapshot.trace_extended_write_end_ns <= snapshot.trace_extended_first_rx_ns
    assert snapshot.trace_extended_first_rx_ns <= snapshot.trace_extended_end_ns
    assert snapshot.trace_extended_end_ns <= snapshot.trace_bus_end_ns
    assert snapshot.trace_group_read_calls > 1
    assert snapshot.trace_extended_read_calls == 1
    assert snapshot.trace_group_response_complete_ns is not None
    assert np.all(snapshot.trace_group_response_complete_ns > 0)


def test_group_read_collects_one_byte_fragments_before_parsing() -> None:
    class ParseCountingBus(STS3215Bus):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            self.parse_rx_lengths: list[int] = []

        def _parse_available(self, **kwargs):
            self.parse_rx_lengths.append(self._rx_length)
            return super()._parse_available(**kwargs)

    transport = FakeTransport(read_chunk_size=1)
    bus = ParseCountingBus(transport=transport)
    snapshot = ServoSnapshot.create()
    snapshot.instrumentation_enabled = True
    snapshot.begin_tick()

    bus.read_state_into(snapshot)

    assert snapshot.all_fresh
    assert snapshot.trace_group_read_calls == 140
    assert snapshot.trace_group_parse_calls == 1
    assert snapshot.trace_group_first_parse_bytes == 140
    assert bus.parse_rx_lengths == []
    assert snapshot.trace_group_parser_mode == 1
    response_times = snapshot.trace_group_response_complete_ns
    assert response_times is not None
    wire_times = [response_times[SERVO_IDS.index(servo_id)] for servo_id in SERVO_SYNC_READ_IDS]
    assert wire_times == sorted(wire_times)


def test_group_response_deadline_starts_after_request_write() -> None:
    class SlowWriteTransport(FakeTransport):
        def write(self, data) -> None:
            super().write(data)
            if bytes(data)[4] == 0x82:
                time.sleep(0.002)

    bus = STS3215Bus(
        transport=SlowWriteTransport(read_chunk_size=140),
        transaction_timeout_s=0.001,
    )
    snapshot = ServoSnapshot.create()
    snapshot.instrumentation_enabled = True
    snapshot.begin_tick()

    bus.read_state_into(snapshot)

    assert snapshot.all_fresh


def test_group_read_routes_a_complete_out_of_order_train_by_servo_id() -> None:
    transport = FakeTransport(
        response_order=tuple(reversed(SERVO_SYNC_READ_IDS)),
        read_chunk_size=140,
    )
    bus = STS3215Bus(transport=transport)
    snapshot = ServoSnapshot.create()
    snapshot.instrumentation_enabled = True
    snapshot.begin_tick()

    bus.read_state_into(snapshot)

    assert snapshot.all_fresh
    assert snapshot.trace_group_parser_mode == 2
    np.testing.assert_array_less(snapshot.positions_rad[:-1], snapshot.positions_rad[1:])


def test_group_read_marks_only_an_omitted_id_stale() -> None:
    omitted_id = SERVO_SYNC_READ_IDS[6]
    bus = STS3215Bus(
        transport=FakeTransport(omit_ids=(omitted_id,), read_chunk_size=140),
        transaction_timeout_s=0.001,
    )
    snapshot = ServoSnapshot.create()
    snapshot.begin_tick()

    bus.read_state_into(snapshot)

    omitted_index = SERVO_IDS.index(omitted_id)
    assert snapshot.failed_servo_count == 1
    assert snapshot.stale[omitted_index]
    assert ErrorCode(int(snapshot.status[omitted_index])) is ErrorCode.TIMEOUT


def test_extended_read_preserves_requested_servo_id_when_write_fails() -> None:
    class FailingExtendedTransport(FakeTransport):
        def write(self, data) -> None:
            frame = bytes(data)
            if frame[4] == 0x02 and frame[5] == ADDR_PRESENT_LOAD:
                raise OSError("simulated serial write failure")
            super().write(data)

    bus = STS3215Bus(transport=FailingExtendedTransport())
    snapshot = ServoSnapshot.create()
    snapshot.begin_tick()
    bus.read_extended_into(snapshot, SERVO_IDS[4])

    assert snapshot.extended_servo_id == SERVO_IDS[4]
    assert snapshot.extended_status is ErrorCode.IO


def test_group_read_classifies_crc_and_partial_per_servo() -> None:
    for failing_id, expected in (
        (SERVO_IDS[2], ErrorCode.CRC),
        (SERVO_SYNC_READ_IDS[-1], ErrorCode.PARTIAL),
    ):
        transport = FakeTransport(
            corrupt_id=failing_id if expected is ErrorCode.CRC else None,
            partial_id=failing_id if expected is ErrorCode.PARTIAL else None,
        )
        bus = STS3215Bus(transport=transport, transaction_timeout_s=0.001)
        snapshot = ServoSnapshot.create()
        snapshot.begin_tick()
        bus.read_state_into(snapshot)
        index = SERVO_IDS.index(failing_id)
        assert snapshot.stale[index]
        assert ErrorCode(int(snapshot.status[index])) is expected
        assert snapshot.failed_servo_count == 1


def test_complete_crc_frame_does_not_wait_for_a_replacement_packet() -> None:
    transport = FakeTransport(corrupt_id=SERVO_IDS[2], read_chunk_size=140)
    bus = STS3215Bus(transport=transport, transaction_timeout_s=0.05)
    snapshot = ServoSnapshot.create()
    snapshot.begin_tick()

    bus.read_state_into(snapshot)

    assert transport.read_calls == 1
    assert ErrorCode(int(snapshot.status[2])) is ErrorCode.CRC


def test_group_read_counts_unexpected_packets_without_hiding_fresh_state() -> None:
    bus = STS3215Bus(transport=FakeTransport(include_unexpected=True))
    snapshot = ServoSnapshot.create()
    snapshot.begin_tick()
    bus.read_state_into(snapshot)
    assert snapshot.all_fresh
    assert snapshot.unexpected_packets == 1


def test_device_alarm_preserves_fresh_group_and_extended_payloads() -> None:
    bus = STS3215Bus(transport=FakeTransport(device_error=0x01))
    snapshot = ServoSnapshot.create()
    snapshot.begin_tick()

    bus.read_state_into(snapshot)

    assert snapshot.all_fresh
    assert np.all(snapshot.status == int(ErrorCode.OK))
    assert np.all(snapshot.device_status == 0x01)
    assert snapshot.device_alarm_count == len(SERVO_IDS)
    assert snapshot.positions_rad[0] == 0.0

    bus.read_extended_into(snapshot, SERVO_IDS[0])

    assert snapshot.extended_status is ErrorCode.OK
    assert snapshot.extended_device_status == 0x01
    assert snapshot.present_voltage_v == 7.4


def test_diagnostic_register_read_preserves_payload_but_normal_read_rejects_it() -> None:
    class VoltageErrorTransport(FakeTransport):
        def write(self, data) -> None:
            frame = bytes(data)
            if frame[4] == 0x02 and frame[5] == 62:
                self.writes.append(frame)
                self.rx.extend(_status_packet(frame[2], bytes((74,)), error=0x01))
                return
            super().write(data)

    bus = STS3215Bus(transport=VoltageErrorTransport())
    status, device_error, parameters = bus.read_register_with_device_status(SERVO_IDS[0], 62, 1)
    assert status is ErrorCode.OK
    assert device_error == 0x01
    assert parameters == bytes((74,))

    status, parameters = bus.read_register(SERVO_IDS[0], 62, 1)
    assert status is ErrorCode.DEVICE
    assert parameters == b""


def test_configuration_write_preserves_device_alarm_separately() -> None:
    transport = FakeTransport(device_error=0x01)
    bus = STS3215Bus(transport=transport)

    status, device_error = bus.write_register_with_device_status(SERVO_IDS[0], 14, b"\x54")

    assert status is ErrorCode.OK
    assert device_error == 0x01
    assert bus.write_register(SERVO_IDS[0], 14, b"\x54") is ErrorCode.DEVICE
