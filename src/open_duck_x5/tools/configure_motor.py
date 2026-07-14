from __future__ import annotations

import argparse
import json
import struct
import time

from ..bus.sts3215 import (
    ADDR_ACCELERATION,
    ADDR_ID,
    ADDR_LOCK,
    ADDR_MAXIMUM_ACCELERATION,
    ADDR_P_COEFFICIENT,
    ADDR_TORQUE_ENABLE,
    rad_to_raw_position,
)
from ..bus.types import ErrorCode
from .common import add_bus_arguments, open_bus

ADDR_MODE = 33
ADDR_D_COEFFICIENT = 22
ADDR_I_COEFFICIENT = 23
ADDR_GOAL_POSITION = 42


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Configure one STS3215 on the direct bus")
    parser.add_argument("--id", type=int, required=True, dest="target_id")
    parser.add_argument("--current-id", type=int, default=1)
    parser.add_argument("--scan", action="store_true")
    add_bus_arguments(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0 <= args.target_id <= 253:
        raise SystemExit("target id must be in 0..253")
    bus = open_bus(args, "configure motor")
    current_id = args.current_id
    write_acks: dict[str, str] = {}
    try:
        if args.scan or bus.ping(current_id) is not ErrorCode.OK:
            found = [servo_id for servo_id in range(254) if bus.ping(servo_id) is ErrorCode.OK]
            if len(found) != 1:
                raise RuntimeError(
                    f"expected exactly one servo on the configuration bus, found {found}"
                )
            current_id = found[0]
        writes = (
            (ADDR_LOCK, b"\x00"),
            (ADDR_MODE, b"\x00"),
            (ADDR_MAXIMUM_ACCELERATION, b"\x00"),
            (ADDR_ACCELERATION, b"\x00"),
            (ADDR_P_COEFFICIENT, b"\x20"),
            (ADDR_I_COEFFICIENT, b"\x00"),
            (ADDR_D_COEFFICIENT, b"\x00"),
        )
        for address, data in writes:
            status = bus.write_register(current_id, address, data)
            write_acks[str(address)] = status.name.lower()
            if status is ErrorCode.IO:
                raise RuntimeError(f"write address {address} failed: io")
            read_status, readback = bus.read_register(current_id, address, len(data))
            if read_status is not ErrorCode.OK or readback != data:
                raise RuntimeError(
                    f"write address {address} did not verify: "
                    f"ack={status.name.lower()} read={read_status.name.lower()} "
                    f"expected={data.hex()} actual={readback.hex()}"
                )
        if current_id != args.target_id:
            id_status = bus.write_register(current_id, ADDR_ID, bytes((args.target_id,)))
            write_acks[str(ADDR_ID)] = id_status.name.lower()
            if id_status is ErrorCode.IO:
                raise RuntimeError("ID write failed before transmission")
            current_id = args.target_id
            time.sleep(0.1)
        raw_mid = rad_to_raw_position(0.0)
        goal_status = bus.write_register(
            current_id,
            ADDR_GOAL_POSITION,
            struct.pack("<h", raw_mid),
        )
        write_acks[str(ADDR_GOAL_POSITION)] = goal_status.name.lower()
        if goal_status is ErrorCode.IO:
            raise RuntimeError("zero-position write failed before transmission")
        goal_read_status, goal_payload = bus.read_register(
            current_id,
            ADDR_GOAL_POSITION,
            2,
        )
        if goal_read_status is not ErrorCode.OK or goal_payload != struct.pack("<h", raw_mid):
            raise RuntimeError("zero-position goal did not verify by readback")
        status = bus.ping(current_id)
        if status is not ErrorCode.OK:
            raise RuntimeError(f"configured servo did not answer at ID {current_id}")
        id_read_status, id_payload = bus.read_register(current_id, ADDR_ID, 1)
        if (
            id_read_status is not ErrorCode.OK
            or not id_payload
            or id_payload[0] != current_id
        ):
            raise RuntimeError("configured servo ID did not verify by readback")
        print(
            json.dumps(
                {
                    "status": "configured",
                    "servo_id": current_id,
                    "p": 32,
                    "i": 0,
                    "d": 0,
                    "write_acknowledgements": write_acks,
                }
            )
        )
        return 0
    finally:
        try:
            bus.write_register(current_id, ADDR_TORQUE_ENABLE, b"\x00")
        finally:
            bus.close()


if __name__ == "__main__":
    raise SystemExit(main())
