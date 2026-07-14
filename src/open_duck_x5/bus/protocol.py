from __future__ import annotations

from dataclasses import dataclass

HEADER = b"\xff\xff"
BROADCAST_ID = 0xFE
PING = 0x01
READ = 0x02
WRITE = 0x03
SYNC_READ = 0x82
SYNC_WRITE = 0x83


class PacketError(ValueError):
    pass


class ChecksumError(PacketError):
    pass


class PartialPacketError(PacketError):
    pass


@dataclass(frozen=True, slots=True)
class StatusPacket:
    servo_id: int
    device_error: int
    parameters: bytes


def checksum(body: bytes | bytearray | memoryview) -> int:
    return (~sum(body)) & 0xFF


def instruction_packet(servo_id: int, instruction: int, parameters: bytes = b"") -> bytes:
    if not 0 <= servo_id <= 0xFE:
        raise ValueError("servo id must be in 0..254")
    if len(parameters) > 253:
        raise ValueError("too many packet parameters")
    length = len(parameters) + 2
    body = bytes((servo_id, length, instruction)) + parameters
    return HEADER + body + bytes((checksum(body),))


def sync_read_packet(ids: tuple[int, ...], address: int, length: int) -> bytes:
    if not ids:
        raise ValueError("sync read needs at least one id")
    return instruction_packet(BROADCAST_ID, SYNC_READ, bytes((address, length, *ids)))


def sync_write_packet(address: int, data_length: int, id_payload: bytes) -> bytes:
    stride = data_length + 1
    if data_length < 1 or not id_payload or len(id_payload) % stride:
        raise ValueError("sync write payload must contain id plus fixed-width data records")
    return instruction_packet(
        BROADCAST_ID, SYNC_WRITE, bytes((address, data_length)) + id_payload
    )


def parse_status_packet(packet: bytes | bytearray | memoryview) -> StatusPacket:
    view = memoryview(packet)
    if len(view) < 6:
        raise PartialPacketError("status packet shorter than six bytes")
    if view[0] != 0xFF or view[1] != 0xFF:
        raise PacketError("invalid status header")
    expected = 4 + int(view[3])
    if len(view) < expected:
        raise PartialPacketError(f"status packet needs {expected} bytes, got {len(view)}")
    if len(view) != expected:
        raise PacketError(f"status packet has trailing bytes: expected {expected}, got {len(view)}")
    if checksum(view[2:-1]) != int(view[-1]):
        raise ChecksumError("status checksum mismatch")
    return StatusPacket(int(view[2]), int(view[4]), bytes(view[5:-1]))
