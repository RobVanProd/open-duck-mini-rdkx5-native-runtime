from __future__ import annotations

import argparse
import json
import time

from ..bus import ErrorCode, ServoSnapshot
from ..constants import ACTION_DIM, JOINT_NAMES, SERVO_IDS
from .common import add_bus_arguments, open_bus


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify the frozen 14-servo map")
    parser.add_argument(
        "--move",
        action="store_true",
        help="Run a separately authorized 0.03 rad one-joint-at-a-time movement check.",
    )
    parser.add_argument("--step-rad", type=float, default=0.03)
    add_bus_arguments(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    bus = open_bus(args, "check motors")
    snapshot = ServoSnapshot.create()
    try:
        snapshot.begin_tick()
        bus.read_state_into(snapshot)
        rows = []
        for index, (name, servo_id) in enumerate(zip(JOINT_NAMES, SERVO_IDS, strict=True)):
            rows.append(
                {
                    "index": index,
                    "joint": name,
                    "servo_id": servo_id,
                    "status": ErrorCode(int(snapshot.status[index])).name.lower(),
                    "device_status_raw": int(snapshot.device_status[index]),
                    "position_rad": None
                    if snapshot.stale[index]
                    else float(snapshot.positions_rad[index]),
                }
            )
        print(json.dumps({"servos": rows}, indent=2))
        if not snapshot.all_fresh:
            return 2
        if snapshot.device_alarm_count:
            return 2
        if not args.move:
            return 0

        baseline = snapshot.positions_rad.copy()
        target = baseline.copy()
        if bus.set_gain_vectors([2] * ACTION_DIM) is not ErrorCode.OK:
            raise RuntimeError("failed to set low gains")
        if bus.enable_torque() is not ErrorCode.OK:
            raise RuntimeError("failed to enable torque")
        for index, name in enumerate(JOINT_NAMES):
            target[:] = baseline
            target[index] += args.step_rad
            if bus.write_positions(target) is not ErrorCode.OK:
                raise RuntimeError(f"write failed while testing {name}")
            time.sleep(0.4)
            snapshot.begin_tick()
            bus.read_state_into(snapshot)
            delta = float(snapshot.positions_rad[index] - baseline[index])
            print(
                json.dumps(
                    {
                        "joint": name,
                        "servo_id": SERVO_IDS[index],
                        "measured_delta_rad": delta,
                    }
                )
            )
            if bus.write_positions(baseline) is not ErrorCode.OK:
                raise RuntimeError(f"return write failed for {name}")
            time.sleep(0.4)
        return 0
    finally:
        try:
            bus.disable_torque()
        finally:
            bus.close()


if __name__ == "__main__":
    raise SystemExit(main())
