from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

from ..bus.sts3215 import ADDR_PRESENT_POSITION, ADDR_TORQUE_ENABLE, raw_position_to_rad
from ..bus.types import ErrorCode
from ..config import DuckConfig
from ..constants import JOINT_NAMES, SERVO_IDS
from .common import add_bus_arguments, open_bus


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture soft joint offsets without auto-motion")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--joints", nargs="*", choices=JOINT_NAMES, default=list(JOINT_NAMES))
    add_bus_arguments(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = DuckConfig.load(args.config)
    candidate = dict(config.joints_offsets)
    bus = open_bus(args, "find soft offsets")
    try:
        for name in args.joints:
            index = JOINT_NAMES.index(name)
            servo_id = SERVO_IDS[index]
            torque_status = bus.write_register(servo_id, ADDR_TORQUE_ENABLE, b"\x00")
            if torque_status is not ErrorCode.OK:
                raise RuntimeError(
                    f"torque-off failed for {name}: {torque_status.name.lower()}"
                )
            if args.bus == "serial":
                input(
                    f"Move {name} (ID {servo_id}) by hand to its desired logical zero, "
                    "then press Enter. Ctrl+C aborts without writing. "
                )
            status, payload = bus.read_register(servo_id, ADDR_PRESENT_POSITION, 2)
            if status is not ErrorCode.OK:
                raise RuntimeError(f"read failed for {name}: {status.name.lower()}")
            raw = struct.unpack("<h", payload)[0]
            candidate[name] = raw_position_to_rad(raw)
            print(f"{name}: {candidate[name]:.9f} rad")
        output = config.with_offsets(candidate)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        output_bytes = (json.dumps(output, indent=2) + "\n").encode("utf-8")
        args.output.write_bytes(output_bytes)
        print(f"wrote candidate config: {args.output}")
        return 0
    finally:
        try:
            bus.disable_torque()
        finally:
            bus.close()


if __name__ == "__main__":
    raise SystemExit(main())
