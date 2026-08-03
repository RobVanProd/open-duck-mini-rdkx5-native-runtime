from __future__ import annotations

import pytest

from open_duck_x5.hardware_guard import HardwareAuthorizationError, require_hardware_authorization


@pytest.mark.parametrize(
    ("authorized", "supported"),
    [(False, False), (True, False), (False, True)],
)
def test_hardware_requires_both_independent_assertions(
    authorized: bool, supported: bool
) -> None:
    with pytest.raises(HardwareAuthorizationError):
        require_hardware_authorization(
            hardware_authorized=authorized,
            suspended_or_benched=supported,
            operation="test gate",
        )


def test_hardware_guard_accepts_both_assertions() -> None:
    assert require_hardware_authorization(
        hardware_authorized=True,
        suspended_or_benched=True,
        operation="test gate",
    ) == "suspended-or-benched"


def test_grounded_x0_requires_all_three_assertions_and_rejects_suspended() -> None:
    with pytest.raises(HardwareAuthorizationError, match="requires"):
        require_hardware_authorization(
            hardware_authorized=True,
            suspended_or_benched=False,
            grounded_test_area_confirmed=True,
            grounded_x0_authorized=False,
            allow_grounded_x0=True,
            operation="test gate",
        )
    with pytest.raises(HardwareAuthorizationError, match="mutually exclusive"):
        require_hardware_authorization(
            hardware_authorized=True,
            suspended_or_benched=True,
            grounded_test_area_confirmed=True,
            grounded_x0_authorized=True,
            allow_grounded_x0=True,
            operation="test gate",
        )
    assert require_hardware_authorization(
        hardware_authorized=True,
        suspended_or_benched=False,
        grounded_test_area_confirmed=True,
        grounded_x0_authorized=True,
        allow_grounded_x0=True,
        operation="test gate",
    ) == "grounded-x0"


def test_other_hardware_commands_cannot_accept_grounded_assertions() -> None:
    with pytest.raises(HardwareAuthorizationError, match="not valid"):
        require_hardware_authorization(
            hardware_authorized=True,
            suspended_or_benched=False,
            grounded_test_area_confirmed=True,
            grounded_x0_authorized=True,
            operation="test gate",
        )
