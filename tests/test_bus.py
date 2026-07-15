from __future__ import annotations

import math
import struct

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
    ) -> None:
        self.corrupt_id = corrupt_id
        self.partial_id = partial_id
        self.include_unexpected = include_unexpected
        self.rx = bytearray()
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data) -> None:
        frame = bytes(data)
        self.writes.append(frame)
        instruction = frame[4]
        if instruction == 0x82:
            packets: list[bytes] = []
            if self.include_unexpected:
                packets.append(_status_packet(99, b"\x00\x08\x00\x00"))
            partial = b""
            for index, servo_id in enumerate(SERVO_IDS):
                parameters = struct.pack("<HH", 2048 + index, 100)
                packet = _status_packet(servo_id, parameters)
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
            self.rx.extend(_status_packet(servo_id, parameters))
        elif instruction == 0x03 and frame[2] != 0xFE:
            self.rx.extend(_status_packet(frame[2], b""))

    def read_some_into(self, target, deadline_ns: int) -> int:
        del deadline_ns
        if not self.rx:
            return 0
        count = min(len(target), len(self.rx), 23)
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
    for failing_id, expected in ((SERVO_IDS[2], ErrorCode.CRC), (SERVO_IDS[-1], ErrorCode.PARTIAL)):
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


def test_group_read_counts_unexpected_packets_without_hiding_fresh_state() -> None:
    bus = STS3215Bus(transport=FakeTransport(include_unexpected=True))
    snapshot = ServoSnapshot.create()
    snapshot.begin_tick()
    bus.read_state_into(snapshot)
    assert snapshot.all_fresh
    assert snapshot.unexpected_packets == 1
