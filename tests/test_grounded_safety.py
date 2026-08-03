from __future__ import annotations

import math

import numpy as np
import pytest

from open_duck_x5.bus import ErrorCode, ServoSnapshot
from open_duck_x5.controller import ControllerReadout
from open_duck_x5.grounded_safety import (
    CONSECUTIVE_FAULT_TICKS,
    GROUNDED_READINESS_SAMPLES,
    GroundedStabilityGuard,
)
from open_duck_x5.runtime import Runtime
from open_duck_x5.safety import SafetyError, TorqueGuard
from open_duck_x5.sensors import SensorReadout


def _sample(
    tick: int,
    *,
    acceleration: tuple[float, float, float] = (0.0, 0.0, 9.81),
    contacts: tuple[float, float] = (1.0, 1.0),
) -> SensorReadout:
    sample = SensorReadout()
    sample.acceleration_m_s2[:] = acceleration
    sample.contacts[:] = contacts
    sample.imu_timestamp_ns = tick * 10_000_000
    sample.contacts_timestamp_ns = tick * 10_000_000
    sample.imu_stale = False
    sample.contacts_stale = False
    return sample


def _ready(*, enforce_contacts: bool = True) -> GroundedStabilityGuard:
    guard = GroundedStabilityGuard(enforce_contacts=enforce_contacts)
    for tick in range(1, GROUNDED_READINESS_SAMPLES + 1):
        guard.add_readiness_sample(_sample(tick))
    assert guard.ready
    return guard


def test_readiness_requires_both_contacts_only_in_grounded_mode() -> None:
    with pytest.raises(SafetyError, match="both feet"):
        GroundedStabilityGuard(enforce_contacts=True).add_readiness_sample(
            _sample(1, contacts=(0.0, 0.0))
        )
    GroundedStabilityGuard(enforce_contacts=False).add_readiness_sample(
        _sample(1, contacts=(0.0, 0.0))
    )


def test_single_hard_tilt_trips_immediately() -> None:
    guard = _ready()
    angle = math.radians(33.0)
    with pytest.raises(SafetyError, match="single-tick tilt"):
        guard.observe(
            _sample(
                100,
                acceleration=(9.81 * math.sin(angle), 0.0, 9.81 * math.cos(angle)),
            )
        )


def test_sustained_tilt_trips_on_exact_third_tick() -> None:
    guard = _ready()
    angle = math.radians(17.0)
    acceleration = (9.81 * math.sin(angle), 0.0, 9.81 * math.cos(angle))
    for tick in range(CONSECUTIVE_FAULT_TICKS - 1):
        guard.observe(_sample(100 + tick, acceleration=acceleration))
    with pytest.raises(SafetyError, match="persisted for 3 ticks"):
        guard.observe(_sample(102, acceleration=acceleration))


def test_both_contacts_false_trips_on_exact_third_tick() -> None:
    guard = _ready()
    for tick in range(CONSECUTIVE_FAULT_TICKS - 1):
        guard.observe(_sample(100 + tick, contacts=(0.0, 0.0)))
    with pytest.raises(SafetyError, match="both foot contacts"):
        guard.observe(_sample(102, contacts=(0.0, 0.0)))


def test_invalid_acceleration_trips_on_exact_third_tick() -> None:
    guard = _ready()
    for tick in range(CONSECUTIVE_FAULT_TICKS - 1):
        guard.observe(_sample(100 + tick, acceleration=(0.0, 0.0, 0.0)))
    with pytest.raises(SafetyError, match="invalid acceleration"):
        guard.observe(_sample(102, acceleration=(0.0, 0.0, 0.0)))


def test_healthy_samples_reset_all_persistence_counters() -> None:
    guard = _ready()
    angle = math.radians(17.0)
    guard.observe(
        _sample(
            100,
            acceleration=(9.81 * math.sin(angle), 0.0, 9.81 * math.cos(angle)),
            contacts=(0.0, 0.0),
        )
    )
    guard.observe(_sample(101, acceleration=(0.0, 0.0, 0.0)))
    guard.observe(_sample(102))
    assert guard.sustained_tilt_ticks == 0
    assert guard.both_contacts_false_ticks == 0
    assert guard.invalid_acceleration_ticks == 0


def test_home_entry_fault_prevents_goal_write_and_torques_off(monkeypatch) -> None:
    events: list[str] = []

    class Bus:
        @staticmethod
        def set_gain_vectors(_gains):
            events.append("set_gains")
            return ErrorCode.OK

        @staticmethod
        def enable_torque():
            events.append("enable_torque")
            return ErrorCode.OK

        @staticmethod
        def disable_torque():
            events.append("disable_torque")
            return ErrorCode.OK

        @staticmethod
        def write_positions(_target):
            events.append("write_positions")
            return ErrorCode.OK

    class Controller:
        @staticmethod
        def read_into(output: ControllerReadout) -> None:
            output.connected = True
            output.timestamp_ns = 10**18
            output.pause_toggle = False
            output.emergency_stop = False

    class Sensors:
        @staticmethod
        def read_into(output: SensorReadout, now_ns: int) -> None:
            angle = math.radians(33.0)
            output.acceleration_m_s2[:] = (
                9.81 * math.sin(angle),
                0.0,
                9.81 * math.cos(angle),
            )
            output.contacts[:] = (1.0, 1.0)
            output.imu_timestamp_ns = now_ns
            output.contacts_timestamp_ns = now_ns
            output.imu_stale = False
            output.contacts_stale = False

    class Ticker:
        @staticmethod
        def wait():
            return 10**18, 0

    runtime = object.__new__(Runtime)
    runtime.args = type("Args", (), {"home_seconds": 0.02, "controller": "xbox"})()
    runtime.bus = Bus()
    runtime.controller = Controller()
    runtime.controller_readout = ControllerReadout()
    runtime.snapshot = ServoSnapshot.create()
    runtime.offsets = np.zeros(14, dtype=np.float64)
    runtime.logical_positions = np.zeros(14, dtype=np.float64)
    runtime.logical_velocities = np.zeros(14, dtype=np.float64)
    runtime.hold_physical_target = np.zeros(14, dtype=np.float64)
    runtime.sensor_hub = Sensors()
    runtime.sensors = SensorReadout()
    runtime.stability_guard = _ready()
    runtime.stop_requested = False
    runtime.watchdog = type("Watchdog", (), {"observe": staticmethod(lambda **_: None)})()
    monkeypatch.setattr("open_duck_x5.runtime.AbsoluteTicker", Ticker)

    with pytest.raises(SafetyError, match="single-tick tilt"), TorqueGuard(
        runtime.bus
    ) as torque_guard:
        runtime._move_home_slowly(torque_guard)

    assert "write_positions" not in events
    assert events == ["set_gains", "enable_torque", "disable_torque"]
