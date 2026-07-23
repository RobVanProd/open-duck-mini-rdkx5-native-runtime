from __future__ import annotations

import argparse

from ..bus import MockSTS3215Bus, STS3215Bus
from ..hardware_guard import add_hardware_ack_arguments, require_hardware_authorization


def add_bus_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bus", choices=("mock", "serial"), default="mock")
    parser.add_argument("--device", default="/dev/ttyS1")
    parser.add_argument("--baudrate", type=int, default=1_000_000)
    parser.add_argument("--timeout-ms", type=float, default=4.0)
    add_hardware_ack_arguments(parser)


def open_bus(args: argparse.Namespace, operation: str):
    if args.bus == "serial":
        require_hardware_authorization(
            hardware_authorized=args.hardware_authorized,
            suspended_or_benched=args.suspended_or_benched,
            operation=operation,
        )
        return STS3215Bus(
            args.device,
            baudrate=args.baudrate,
            transaction_timeout_s=args.timeout_ms / 1000.0,
        )
    return MockSTS3215Bus()
