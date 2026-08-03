from __future__ import annotations

import argparse


class HardwareAuthorizationError(RuntimeError):
    pass


def add_hardware_ack_arguments(
    parser: argparse.ArgumentParser, *, allow_grounded_x0: bool = False
) -> None:
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
    if allow_grounded_x0:
        parser.add_argument(
            "--grounded-test-area-confirmed",
            action="store_true",
            help="Assert the frozen G3 physical-area requirements are satisfied.",
        )
        parser.add_argument(
            "--grounded-x0-authorized",
            action="store_true",
            help="Assert Rob explicitly authorized this exact grounded x=0 gate.",
        )


def require_hardware_authorization(
    *,
    hardware_authorized: bool,
    suspended_or_benched: bool,
    operation: str,
    grounded_test_area_confirmed: bool = False,
    grounded_x0_authorized: bool = False,
    allow_grounded_x0: bool = False,
) -> str:
    grounded_assertion_present = grounded_test_area_confirmed or grounded_x0_authorized
    if grounded_assertion_present:
        if not allow_grounded_x0:
            raise HardwareAuthorizationError(
                f"{operation} is blocked: grounded authorization is not valid for this command"
            )
        if suspended_or_benched:
            raise HardwareAuthorizationError(
                f"{operation} is blocked: grounded G3 assertions are mutually exclusive "
                "with --suspended-or-benched"
            )
        if not (
            hardware_authorized
            and grounded_test_area_confirmed
            and grounded_x0_authorized
        ):
            raise HardwareAuthorizationError(
                f"{operation} is blocked: grounded G3 requires --hardware-authorized, "
                "--grounded-test-area-confirmed, and --grounded-x0-authorized after "
                "explicit authorization for this exact grounded x=0 gate"
            )
        return "grounded-x0"
    if not hardware_authorized or not suspended_or_benched:
        raise HardwareAuthorizationError(
            f"{operation} is blocked: pass both --hardware-authorized and "
            "--suspended-or-benched only after explicit authorization for this exact gate"
        )
    return "suspended-or-benched"
