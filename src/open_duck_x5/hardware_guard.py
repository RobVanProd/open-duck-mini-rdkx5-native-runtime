from __future__ import annotations

import argparse


class HardwareAuthorizationError(RuntimeError):
    pass


def add_hardware_ack_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--hardware-authorized",
        action="store_true",
        help="Assert Rob explicitly authorized this exact hardware gate.",
    )
    parser.add_argument(
        "--suspended-or-benched",
        action="store_true",
        help="Assert the robot is physically suspended or safely benched.",
    )


def require_hardware_authorization(
    *, hardware_authorized: bool, suspended_or_benched: bool, operation: str
) -> None:
    if not hardware_authorized or not suspended_or_benched:
        raise HardwareAuthorizationError(
            f"{operation} is blocked: pass both --hardware-authorized and "
            "--suspended-or-benched only after explicit authorization for this exact gate"
        )
