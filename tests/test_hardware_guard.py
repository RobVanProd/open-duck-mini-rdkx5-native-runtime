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
    require_hardware_authorization(
        hardware_authorized=True,
        suspended_or_benched=True,
        operation="test gate",
    )
