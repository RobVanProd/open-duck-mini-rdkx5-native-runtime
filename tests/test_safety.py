from __future__ import annotations

import pytest

from open_duck_x5.bus.types import ErrorCode
from open_duck_x5.safety import TorqueGuard, Watchdog, WatchdogTrip


class FakeTorqueBus:
    def __init__(self) -> None:
        self.enabled = False
        self.disable_calls = 0

    def enable_torque(self) -> ErrorCode:
        self.enabled = True
        return ErrorCode.OK

    def disable_torque(self) -> ErrorCode:
        self.enabled = False
        self.disable_calls += 1
        return ErrorCode.OK


def test_torque_guard_disables_on_crash_path() -> None:
    bus = FakeTorqueBus()
    with pytest.raises(RuntimeError, match="simulated crash"), TorqueGuard(bus) as guard:
        guard.enable()
        raise RuntimeError("simulated crash")
    assert bus.enabled is False
    assert bus.disable_calls == 1


def test_watchdog_trips_on_hard_overrun_and_consecutive_bus_failures() -> None:
    watchdog = Watchdog(hard_overrun_ns=40, max_consecutive_bus_failures=2)
    with pytest.raises(WatchdogTrip, match="hard tick overrun"):
        watchdog.observe(tick_period_ns=20, tick_work_ns=41, bus_ok=True)
    with pytest.raises(WatchdogTrip, match="hard tick overrun"):
        watchdog.observe(tick_period_ns=41, tick_work_ns=20, bus_ok=True)

    watchdog.observe(tick_period_ns=20, tick_work_ns=20, bus_ok=False)
    with pytest.raises(WatchdogTrip, match="2 consecutive"):
        watchdog.observe(tick_period_ns=20, tick_work_ns=20, bus_ok=False)
