from __future__ import annotations

import argparse
import gc
import signal
import sys
from contextlib import suppress
from pathlib import Path

import numpy as np

from .bus import ErrorCode, MockSTS3215Bus, ServoSnapshot, STS3215Bus
from .clock import clock_ns
from .config import ConfigError, DuckConfig
from .constants import ACTION_DIM, CONTROL_PERIOD_NS, HOME_RAD, SERVO_IDS
from .contract import ActionPipeline, ObservationAssembler, PhaseClock, StaleObservationError
from .controller import ControllerReadout, NullController, PygameController
from .hardware_guard import (
    HardwareAuthorizationError,
    add_hardware_ack_arguments,
    require_hardware_authorization,
)
from .policy import OnnxPolicy, PolicyContractError
from .realtime import RealtimeSetupError, configure_realtime
from .safety import SafetyError, TorqueGuard, Watchdog, WatchdogTrip
from .sensors import BNO055Smbus, MockSensorHub, SensorHub, SensorReadout, X5FootContacts
from .telemetry import AsyncControlWriter
from .timing import AbsoluteTicker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Open Duck Mini deterministic X5 runtime")
    parser.add_argument("--bus", choices=("mock", "serial"), default="mock")
    parser.add_argument("--device", default="/dev/ttyACM0")
    parser.add_argument("--baudrate", type=int, default=1_000_000)
    parser.add_argument("--timeout-ms", type=float, default=4.0)
    parser.add_argument("--config", type=Path, default=Path.home() / "duck_config.json")
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--controller", choices=("none", "xbox", "f710"), default="none")
    parser.add_argument("--fixed-command-x", type=float)
    parser.add_argument("--telemetry", type=Path, required=True)
    parser.add_argument("--max-ticks", type=int, default=0, help="0 runs until stopped")
    parser.add_argument("--home-seconds", type=float, default=2.0)
    parser.add_argument("--watchdog-failures", type=int, default=3)
    parser.add_argument("--imu-bus", type=int, default=5)
    parser.add_argument("--imu-address", type=lambda value: int(value, 0), default=0x28)
    parser.add_argument("--require-realtime", action="store_true")
    parser.add_argument("--rt-cpu", type=int, default=5)
    parser.add_argument("--rt-priority", type=int, default=80)
    add_hardware_ack_arguments(parser)
    return parser


class Runtime:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.config = DuckConfig.load(args.config)
        self.offsets = self.config.offsets_array
        self.logical_positions = np.zeros(ACTION_DIM, dtype=np.float64)
        self.logical_velocities = np.zeros(ACTION_DIM, dtype=np.float64)
        self.hold_physical_target = HOME_RAD + self.offsets
        self.snapshot = ServoSnapshot.create()
        self.sensors = SensorReadout()
        self.controller_readout = ControllerReadout()
        self.assembler = ObservationAssembler()
        self.action_pipeline = ActionPipeline()
        np.add(
            self.action_pipeline.sent_target_rad,
            self.offsets,
            out=self.action_pipeline.physical_target_rad,
        )
        self.phase = PhaseClock(self.config.phase_frequency_factor_offset)
        self.commands = np.zeros(7, dtype=np.float64)
        self.telemetry_action = np.zeros(ACTION_DIM, dtype=np.float32)
        self.paused = self.config.start_paused
        self.watchdog = Watchdog(
            hard_overrun_ns=2 * CONTROL_PERIOD_NS,
            max_consecutive_bus_failures=args.watchdog_failures,
        )
        self.stop_requested = False
        self.halt_reason = "startup_failure"
        self._previous_tick_start_ns = 0
        self.bus = None
        self.sensor_hub = None
        self.controller = None
        self.writer = None

        try:
            if args.bus == "serial":
                require_hardware_authorization(
                    hardware_authorized=args.hardware_authorized,
                    suspended_or_benched=args.suspended_or_benched,
                    operation="X5 runtime",
                )
                if not args.require_realtime:
                    raise RealtimeSetupError("serial runtime requires --require-realtime")
                self.bus = STS3215Bus(
                    args.device,
                    baudrate=args.baudrate,
                    transaction_timeout_s=args.timeout_ms / 1000.0,
                )
                contacts = X5FootContacts()
                try:
                    imu = BNO055Smbus(
                        bus_number=args.imu_bus,
                        address=args.imu_address,
                        upside_down=self.config.imu_upside_down,
                    )
                except BaseException:
                    contacts.close()
                    raise
                self.sensor_hub = SensorHub(imu, contacts)
            else:
                self.bus = MockSTS3215Bus()
                self.sensor_hub = MockSensorHub()

            self.policy = OnnxPolicy(args.policy) if args.policy else None
            if args.controller == "none":
                self.controller = NullController()
            else:
                self.controller = PygameController(args.controller)
            self.writer = AsyncControlWriter(args.telemetry)
            self.halt_reason = "normal_exit"
        except BaseException:
            with suppress(BaseException):
                self.close()
            raise

    def request_stop(self, signum=None, frame=None) -> None:
        del frame
        self.halt_reason = f"signal:{signum}" if signum is not None else "stop_requested"
        self.stop_requested = True

    def _verify_all_servos(self) -> None:
        self.snapshot.begin_tick()
        self.bus.read_state_into(self.snapshot)
        if not self.snapshot.all_fresh:
            failures = [
                f"{servo_id}:{ErrorCode(int(code)).name.lower()}"
                for servo_id, code in zip(SERVO_IDS, self.snapshot.status, strict=True)
                if int(code) != int(ErrorCode.OK)
            ]
            raise SafetyError("servo verification failed: " + ", ".join(failures))

    def _logical_from_snapshot(self) -> None:
        np.subtract(self.snapshot.positions_rad, self.offsets, out=self.logical_positions)
        np.copyto(self.logical_velocities, self.snapshot.velocities_rad_s)

    def _move_home_slowly(self, guard: TorqueGuard) -> None:
        self._logical_from_snapshot()
        start = self.logical_positions.copy()
        target = np.zeros(ACTION_DIM, dtype=np.float64)
        low_gains = [2] * ACTION_DIM
        if self.bus.set_gain_vectors(low_gains) is not ErrorCode.OK:
            raise SafetyError("failed to set low startup gains")
        guard.enable()
        steps = max(1, int(self.args.home_seconds * 50.0))
        ticker = AbsoluteTicker()
        for step in range(1, steps + 1):
            ticker.wait()
            fraction = step / steps
            np.multiply(start, 1.0 - fraction, out=target)
            target += HOME_RAD * fraction
            target += self.offsets
            if self.bus.write_positions(target) is not ErrorCode.OK:
                raise SafetyError("home move write failed")
            self.snapshot.begin_tick()
            self.bus.read_state_into(self.snapshot)
            if not self.snapshot.all_fresh:
                raise SafetyError("home move read failed")
        high_gains = [30] * ACTION_DIM
        high_gains[5:9] = [8, 8, 8, 8]
        if self.bus.set_gain_vectors(high_gains) is not ErrorCode.OK:
            raise SafetyError("failed to set operating gains")
        if self.bus.write_positions(self.hold_physical_target) is not ErrorCode.OK:
            raise SafetyError("failed to hold home target")

    def _update_controller(self, tick_start_ns: int) -> None:
        self.controller.read_into(self.controller_readout)
        np.copyto(self.commands, self.controller_readout.commands)
        if self.args.fixed_command_x is not None:
            self.commands[0] = float(self.args.fixed_command_x)
        if self.controller_readout.pause_toggle:
            if self.paused and self.policy is None:
                return
            self.paused = not self.paused
        if (
            not self.paused
            and self.args.controller != "none"
            and (
                not self.controller_readout.connected
                or tick_start_ns - self.controller_readout.timestamp_ns > 250_000_000
            )
        ):
            self.paused = True

    def run(self) -> None:
        if self.args.require_realtime:
            configure_realtime(
                cpu=self.args.rt_cpu,
                priority=self.args.rt_priority,
                require_isolated=True,
            )
        self._verify_all_servos()
        with TorqueGuard(self.bus) as guard:
            self._move_home_slowly(guard)
            ticker = AbsoluteTicker()
            gc.disable()
            tick = 0
            while not self.stop_requested and (
                not self.args.max_ticks or tick < self.args.max_ticks
            ):
                tick_start_ns, _ = ticker.wait()
                tick_period_ns = (
                    tick_start_ns - self._previous_tick_start_ns
                    if self._previous_tick_start_ns
                    else 0
                )
                self._previous_tick_start_ns = tick_start_ns
                self._update_controller(tick_start_ns)

                self.snapshot.begin_tick()
                self.bus.read_state_into(self.snapshot)
                self._logical_from_snapshot()
                self.sensor_hub.read_into(self.sensors, clock_ns())

                observation_valid = False
                if not self.paused and self.policy is not None:
                    try:
                        observation = self.assembler.build(
                            gyro_rad_s=self.sensors.gyro_rad_s,
                            acceleration_m_s2=self.sensors.acceleration_m_s2,
                            commands=self.commands,
                            positions_rad=self.logical_positions,
                            velocities_rad_s=self.logical_velocities,
                            previous_motor_target_rad=self.action_pipeline.previous_motor_target_rad,
                            foot_contacts=self.sensors.contacts,
                            phase=self.phase.value,
                            servo_stale=self.snapshot.stale,
                            imu_stale=self.sensors.imu_stale,
                            contacts_stale=self.sensors.contacts_stale,
                        )
                        # Preserve inherited real-runtime order: advance after obs construction.
                        self.phase.advance()
                        action = self.policy.infer(observation)
                        np.copyto(self.telemetry_action, action)
                        self.assembler.commit_action(action)
                        physical_target = self.action_pipeline.apply(
                            action, self.commands, self.offsets
                        )
                        observation_valid = True
                    except StaleObservationError:
                        physical_target = self.hold_physical_target
                else:
                    physical_target = self.hold_physical_target

                if observation_valid:
                    np.copyto(self.hold_physical_target, physical_target)

                write_start_ns = clock_ns()
                self.snapshot.write_status = self.bus.write_positions(physical_target)
                write_elapsed_ns = clock_ns() - write_start_ns
                self.bus.read_extended_into(self.snapshot, SERVO_IDS[tick % ACTION_DIM])
                self.snapshot.bus_total_ns = (
                    self.snapshot.group_round_trip_ns
                    + write_elapsed_ns
                    + self.snapshot.extended_round_trip_ns
                )
                tick_work_ns = clock_ns() - tick_start_ns
                bus_ok = (
                    self.snapshot.all_fresh
                    and self.snapshot.write_status is ErrorCode.OK
                    and self.snapshot.extended_status is ErrorCode.OK
                    and self.snapshot.partial_bytes == 0
                    and self.snapshot.unexpected_packets == 0
                )

                self.writer.publish(
                    tick,
                    tick_start_ns,
                    tick_period_ns,
                    tick_work_ns,
                    self.paused,
                    observation_valid,
                    self.sensors.imu_age_ns,
                    self.sensors.contacts_age_ns,
                    self.snapshot,
                    self.assembler.observation,
                    self.telemetry_action,
                    self.logical_positions,
                    self.action_pipeline.previous_motor_target_rad,
                    self.action_pipeline.implied_velocity_rad_s,
                    self.action_pipeline.over_envelope,
                )
                self.watchdog.observe(
                    tick_period_ns=tick_period_ns,
                    tick_work_ns=tick_work_ns,
                    bus_ok=bus_ok,
                )
                tick += 1

    def close(self) -> None:
        errors: list[BaseException] = []
        if self.writer is not None:
            try:
                self.writer.close(reason=self.halt_reason)
            except BaseException as exc:
                errors.append(exc)
        self.writer = None
        for resource in (self.controller, self.sensor_hub):
            if resource is None:
                continue
            try:
                resource.close()
            except BaseException as exc:
                errors.append(exc)
        self.controller = None
        self.sensor_hub = None
        if self.bus is not None:
            try:
                self.bus.disable_torque()
            except BaseException as exc:
                errors.append(exc)
            try:
                self.bus.close()
            except BaseException as exc:
                errors.append(exc)
            self.bus = None
        if errors:
            raise errors[0]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    runtime: Runtime | None = None
    try:
        runtime = Runtime(args)
        signal.signal(signal.SIGINT, runtime.request_stop)
        signal.signal(signal.SIGTERM, runtime.request_stop)
        runtime.run()
        return 0
    except (
        ConfigError,
        HardwareAuthorizationError,
        PolicyContractError,
        RealtimeSetupError,
        SafetyError,
        WatchdogTrip,
        ValueError,
    ) as exc:
        if runtime is not None:
            runtime.halt_reason = f"{type(exc).__name__}: {exc}"
        print(f"runtime halted: {exc}", file=sys.stderr)
        return 2
    finally:
        if runtime is not None:
            runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
