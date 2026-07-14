from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .bus.types import ErrorCode


class TorqueBus(Protocol):
    def enable_torque(self) -> ErrorCode: ...

    def disable_torque(self) -> ErrorCode: ...


class SafetyError(RuntimeError):
    pass


class WatchdogTrip(SafetyError):
    pass


class TorqueGuard:
    def __init__(self, bus: TorqueBus) -> None:
        self.bus = bus
        self.enabled = False

    def enable(self) -> None:
        status = self.bus.enable_torque()
        if status is not ErrorCode.OK:
            raise SafetyError(f"failed to enable torque: {status.name.lower()}")
        self.enabled = True

    def disable(self) -> None:
        status = self.bus.disable_torque()
        self.enabled = False
        if status is not ErrorCode.OK:
            raise SafetyError(f"failed to disable torque: {status.name.lower()}")

    def __enter__(self) -> TorqueGuard:
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        try:
            self.disable()
        except Exception:
            if exc is None:
                raise
        return False


@dataclass(slots=True)
class Watchdog:
    hard_overrun_ns: int = 40_000_000
    max_consecutive_bus_failures: int = 3
    consecutive_bus_failures: int = 0

    def observe(self, *, tick_period_ns: int, tick_work_ns: int, bus_ok: bool) -> None:
        overrun_ns = max(tick_period_ns, tick_work_ns)
        if overrun_ns > self.hard_overrun_ns:
            raise WatchdogTrip(
                f"hard tick overrun: {overrun_ns / 1e6:.3f} ms > "
                f"{self.hard_overrun_ns / 1e6:.3f} ms"
            )
        if bus_ok:
            self.consecutive_bus_failures = 0
        else:
            self.consecutive_bus_failures += 1
            if self.consecutive_bus_failures >= self.max_consecutive_bus_failures:
                raise WatchdogTrip(
                    f"bus failed {self.consecutive_bus_failures} consecutive ticks"
                )
