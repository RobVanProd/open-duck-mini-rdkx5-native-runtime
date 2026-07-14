from __future__ import annotations

import pytest

from open_duck_x5.bus.protocol import (
    ChecksumError,
    PartialPacketError,
    instruction_packet,
    parse_status_packet,
    sync_read_packet,
    sync_write_packet,
)


def test_known_instruction_packet_vectors() -> None:
    assert instruction_packet(1, 1) == bytes.fromhex("ff ff 01 02 01 fb")
    assert sync_read_packet((11, 12), 30, 2) == bytes.fromhex(
        "ff ff fe 06 82 1e 02 0b 0c 42"
    )
    assert sync_write_packet(42, 2, bytes.fromhex("01 34 12 02 78 56")) == bytes.fromhex(
        "ff ff fe 0a 83 2a 02 01 34 12 02 78 56 31"
    )


def test_status_packet_validation() -> None:
    packet = bytes.fromhex("ff ff 01 04 00 34 12 b4")
    parsed = parse_status_packet(packet)
    assert parsed.servo_id == 1
    assert parsed.device_error == 0
    assert parsed.parameters == bytes.fromhex("34 12")

    corrupted = packet[:-1] + bytes((packet[-1] ^ 0x01,))
    with pytest.raises(ChecksumError):
        parse_status_packet(corrupted)
    with pytest.raises(PartialPacketError):
        parse_status_packet(packet[:-1])


def test_packet_argument_validation() -> None:
    with pytest.raises(ValueError):
        instruction_packet(255, 1)
    with pytest.raises(ValueError):
        sync_read_packet((), 56, 4)
    with pytest.raises(ValueError):
        sync_write_packet(42, 2, b"\x01\x00")
