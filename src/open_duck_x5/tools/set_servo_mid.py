from __future__ import annotations

import argparse
import struct

from ..bus.sts3215 import ADDR_PRESENT_POSITION, ADDR_TORQUE_ENABLE, raw_position_to_rad
from ..bus.types import ErrorCode
from .common import add_bus_arguments, open_bus


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply the STS3215 one-key midpoint calibration at register 40 value 128"
    )
    parser.add_argument("--id", type=int, required=True, dest="servo_id")
    parser.add_argument(
        "--confirm-at-midpoint",
        action="store_true",
        help="Assert the unpowered servo is physically at the intended midpoint.",
    )
    add_bus_arguments(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.confirm_at_midpoint:
        raise SystemExit("blocked: pass --confirm-at-midpoint only after manually setting midpoint")
    bus = open_bus(args, "set servo midpoint")
    try:
        torque_status = bus.write_register(args.servo_id, ADDR_TORQUE_ENABLE, b"\x00")
        if torque_status is not ErrorCode.OK:
            raise RuntimeError(f"torque-off failed: {torque_status.name.lower()}")
        status = bus.write_register(args.servo_id, ADDR_TORQUE_ENABLE, b"\x80")
        if status is not ErrorCode.OK:
            raise RuntimeError(f"midpoint command failed: {status.name.lower()}")
        status, payload = bus.read_register(args.servo_id, ADDR_PRESENT_POSITION, 2)
        if status is not ErrorCode.OK:
            raise RuntimeError(f"midpoint verification read failed: {status.name.lower()}")
        raw = struct.unpack("<h", payload)[0]
        position_rad = raw_position_to_rad(raw)
        print(
            f"servo {args.servo_id} present position after calibration: "
            f"{position_rad:.6f} rad"
        )
        return 0
    finally:
        try:
            bus.write_register(args.servo_id, ADDR_TORQUE_ENABLE, b"\x00")
        finally:
            bus.close()


if __name__ == "__main__":
    raise SystemExit(main())
