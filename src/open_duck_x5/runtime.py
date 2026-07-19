from __future__ import annotations

import argparse
import gc
import hashlib
import signal
import sys
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .bus import ErrorCode, MockSTS3215Bus, ServoSnapshot, STS3215Bus
from .clock import clock_ns
from .config import ConfigError, DuckConfig
from .constants import (
    ACTION_DIM,
    CONTRACT_ID,
    CONTROL_FREQUENCY_HZ,
    CONTROL_PERIOD_NS,
    HOME_RAD,
    JOINT_NAMES,
    SERVO_IDS,
)
from .contract import ActionPipeline, ObservationAssembler, PhaseClock, StaleObservationError
from .controller import ControllerReadout, NullController, PygameController
from .hardware_guard import (
    HardwareAuthorizationError,
    add_hardware_ack_arguments,
    require_hardware_authorization,
)
from .policy import ONNX_SESSION_CONTRACT, OnnxPolicy, PolicyContractError
from .realtime import RealtimeSetupError, configure_realtime, prepare_realtime
from .safety import SafetyError, TorqueGuard, Watchdog, WatchdogTrip
from .sensors import BNO055Smbus, MockSensorHub, SensorHub, SensorReadout, X5FootContacts
from .telemetry import AsyncControlWriter, TelemetryError
from .timing import AbsoluteTicker


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _device_alarm_details(snapshot: ServoSnapshot) -> str:
    return ", ".join(
        f"{servo_id}:0x{int(device_status):02x}"
        for servo_id, device_status in zip(
            SERVO_IDS, snapshot.device_status, strict=True
        )
        if int(device_status) != 0
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Open Duck Mini deterministic X5 runtime")
    parser.add_argument("--bus", choices=("mock", "serial"), default="mock")
    parser.add_argument("--device", default="/dev/ttyS1")
    parser.add_argument("--baudrate", type=int, default=1_000_000)
    parser.add_argument("--timeout-ms", type=float, default=4.0)
    parser.add_argument("--config", type=Path, default=Path.home() / "duck_config.json")
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--controller", choices=("none", "xbox", "f710"), default="none")
    parser.add_argument("--fixed-command-x", type=float)
    parser.add_argument("--telemetry", type=Path, required=True)
    parser.add_argument("--max-ticks", type=int, default=0, help="0 runs until stopped")
    parser.add_argument(
        "--max-active-ticks",
        type=int,
        default=0,
        help="stop after this many valid policy ticks; 0 disables the active-tick target",
    )
    parser.add_argument("--home-seconds", type=float, default=2.0)
    parser.add_argument("--watchdog-failures", type=int, default=3)
    parser.add_argument("--imu-bus", type=int, default=5)
    parser.add_argument("--imu-address", type=lambda value: int(value, 0), default=0x28)
    parser.add_argument("--require-realtime", action="store_true")
    parser.add_argument("--rt-cpu", type=int, default=7)
    parser.add_argument("--rt-priority", type=int, default=80)
    parser.add_argument(
        "--gate5-authorized",
        action="store_true",
        help="assert that this exact suspended Gate 5 policy replay is authorized",
    )
    add_hardware_ack_arguments(parser)
    return parser


def validate_runtime_args(args: argparse.Namespace) -> None:
    if args.baudrate <= 0:
        raise ValueError("--baudrate must be positive")
    if not np.isfinite(args.timeout_ms) or args.timeout_ms <= 0:
        raise ValueError("--timeout-ms must be finite and positive")
    if not np.isfinite(args.home_seconds) or args.home_seconds <= 0:
        raise ValueError("--home-seconds must be finite and positive")
    if args.watchdog_failures < 1:
        raise ValueError("--watchdog-failures must be positive")
    if args.max_ticks < 0:
        raise ValueError("--max-ticks must be nonnegative")
    if args.max_active_ticks < 0:
        raise ValueError("--max-active-ticks must be nonnegative")
    if args.imu_bus < 0:
        raise ValueError("--imu-bus must be nonnegative")
    if not 0 <= args.imu_address <= 0x7F:
        raise ValueError("--imu-address must be a 7-bit I2C address")
    if args.rt_cpu < 0:
        raise ValueError("--rt-cpu must be nonnegative")
    if not 1 <= args.rt_priority <= 99:
        raise ValueError("--rt-priority must be in 1..99 for SCHED_FIFO")
    if args.fixed_command_x is not None and not np.isfinite(args.fixed_command_x):
        raise ValueError("--fixed-command-x must be finite")
    telemetry_path = args.telemetry.expanduser().resolve()
    protected_paths = {args.config.expanduser().resolve()}
    if args.policy is not None:
        protected_paths.add(args.policy.expanduser().resolve())
    if args.bus == "serial":
        protected_paths.add(Path(args.device).expanduser().resolve())
    if telemetry_path in protected_paths:
        raise ValueError("--telemetry must not overwrite config, policy, or serial device")


class Runtime:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        validate_runtime_args(args)
        self.config_path = args.config.expanduser().resolve()
        self.config = DuckConfig.load(self.config_path)
        self.config_sha256 = _sha256(self.config_path)
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
        self.realtime_preparation = None
        self.realtime_state = None
        self._gc_was_enabled = gc.isenabled()

        try:
            if args.bus == "serial":
                require_hardware_authorization(
                    hardware_authorized=args.hardware_authorized,
                    suspended_or_benched=args.suspended_or_benched,
                    operation="X5 runtime",
                )
                if not args.gate5_authorized:
                    raise HardwareAuthorizationError(
                        "serial runtime is reserved for Gate 5: pass --gate5-authorized "
                        "only after this exact command/duration is explicitly authorized"
                    )
                if args.policy is None:
                    raise ValueError("Gate 5 serial runtime requires --policy")
                if args.max_ticks < 1:
                    raise ValueError("Gate 5 serial runtime requires finite --max-ticks")
                if args.fixed_command_x not in (0.0, 0.08):
                    raise ValueError(
                        "Gate 5 serial runtime requires --fixed-command-x 0 or 0.08"
                    )
                if args.max_active_ticks < 1:
                    raise ValueError(
                        "Gate 5 serial runtime requires finite --max-active-ticks"
                    )
                if args.max_ticks <= args.max_active_ticks:
                    raise ValueError(
                        "Gate 5 --max-ticks must exceed --max-active-ticks "
                        "to bound paused startup time"
                    )
                if args.controller == "none":
                    raise ValueError(
                        "Gate 5 serial runtime requires --controller xbox or f710 "
                        "for preserved unpause control"
                    )
                if not self.config.start_paused:
                    raise SafetyError(
                        "Gate 5 serial runtime requires start_paused=true in duck_config.json"
                    )
                if not args.require_realtime:
                    raise RealtimeSetupError("serial runtime requires --require-realtime")
            if args.require_realtime:
                # This must happen before ONNX, sensors, controller, or writer
                # create threads. They then inherit housekeeping affinity.
                self.realtime_preparation = prepare_realtime(
                    cpu=args.rt_cpu,
                    require_isolated=True,
                )
            if args.bus == "serial":
                self.bus = STS3215Bus(
                    args.device,
                    baudrate=args.baudrate,
                    transaction_timeout_s=args.timeout_ms / 1000.0,
                )
                if self.bus.disable_torque() is not ErrorCode.OK:
                    raise SafetyError("failed to establish torque-off before startup")
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
            self.policy_path = (
                args.policy.expanduser().resolve() if args.policy is not None else None
            )
            self.policy_sha256 = (
                _sha256(self.policy_path) if self.policy_path is not None else None
            )
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
        if self.snapshot.device_alarm_count:
            raise SafetyError(
                "servo verification reported device alarm: "
                + _device_alarm_details(self.snapshot)
            )

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
        previous_tick_start_ns = 0
        for step in range(1, steps + 1):
            if self.stop_requested:
                raise SafetyError("stop requested during home move")
            tick_start_ns, _ = ticker.wait()
            if self.stop_requested:
                raise SafetyError("stop requested during home move")
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
            if self.snapshot.device_alarm_count:
                raise SafetyError(
                    "home move device alarm: "
                    + _device_alarm_details(self.snapshot)
                )
            tick_period_ns = (
                tick_start_ns - previous_tick_start_ns if previous_tick_start_ns else 0
            )
            previous_tick_start_ns = tick_start_ns
            self.watchdog.observe(
                tick_period_ns=tick_period_ns,
                tick_work_ns=clock_ns() - tick_start_ns,
                bus_ok=True,
            )
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
            getattr(self.args, "bus", None) == "serial"
            and getattr(self.args, "gate5_authorized", False)
        ):
            # Gate 5 is an exact fixed-command replay. The physical controller
            # remains the reviewed pause/unpause surface, but joystick/head/LB
            # state cannot silently change commands or phase speed.
            self.commands.fill(0.0)
            self.commands[0] = float(self.args.fixed_command_x)
            self.controller_readout.phase_frequency_factor = 1.0
        if (
            not self.paused
            and self.args.controller != "none"
            and (
                not self.controller_readout.connected
                or tick_start_ns - self.controller_readout.timestamp_ns > 250_000_000
            )
        ):
            raise SafetyError("physical controller state is disconnected or stale")

    def _runtime_start_details(self) -> dict[str, object]:
        return {
            "contract_id": CONTRACT_ID,
            "control_frequency_hz": CONTROL_FREQUENCY_HZ,
            "control_period_ns": CONTROL_PERIOD_NS,
            "bus": {
                "backend": self.args.bus,
                "device": self.args.device if self.args.bus == "serial" else "mock://sts3215",
                "baudrate": self.args.baudrate,
                "timeout_ms": self.args.timeout_ms,
            },
            "config": {
                "path": str(self.config_path),
                "sha256": self.config_sha256,
                "start_paused": self.config.start_paused,
                "imu_upside_down": self.config.imu_upside_down,
                "phase_frequency_factor_offset": (
                    self.config.phase_frequency_factor_offset
                ),
            },
            "policy": (
                {
                    "path": str(self.policy_path),
                    "sha256": self.policy_sha256,
                    "input": {"name": "obs", "shape": [1, 101], "type": "tensor(float)"},
                    "output": {
                        "name": "continuous_actions",
                        "shape": [1, 14],
                        "type": "tensor(float)",
                    },
                    "session": dict(ONNX_SESSION_CONTRACT),
                }
                if self.policy_path is not None
                else None
            ),
            "joint_names": list(JOINT_NAMES),
            "servo_ids": list(SERVO_IDS),
            "controller": self.args.controller,
            "fixed_command_x": self.args.fixed_command_x,
            "max_ticks": self.args.max_ticks,
            "max_active_ticks": self.args.max_active_ticks,
            "home_seconds": self.args.home_seconds,
            "watchdog_consecutive_failures": self.args.watchdog_failures,
            "realtime_required": self.args.require_realtime,
            "gate5_authorized": self.args.gate5_authorized,
            "hardware_authorized": self.args.hardware_authorized,
            "suspended_or_benched": self.args.suspended_or_benched,
        }

    def run(self) -> None:
        self.writer.publish_event(
            "runtime_start",
            details=self._runtime_start_details(),
        )
        if self.args.require_realtime:
            if self.realtime_preparation is None:
                raise RealtimeSetupError("real-time thread partition was not prepared")
            self.realtime_state = configure_realtime(
                preparation=self.realtime_preparation,
                priority=self.args.rt_priority,
            )
            self.writer.publish_event(
                "realtime_verified",
                details=asdict(self.realtime_state),
            )
        self._verify_all_servos()
        if self.stop_requested:
            return
        with TorqueGuard(self.bus) as guard:
            self._move_home_slowly(guard)
            ticker = AbsoluteTicker()
            gc.disable()
            tick = 0
            active_tick = 0
            while not self.stop_requested and (
                not self.args.max_ticks or tick < self.args.max_ticks
            ) and (
                not self.args.max_active_ticks
                or active_tick < self.args.max_active_ticks
            ):
                tick_start_ns, _ = ticker.wait()
                if self.stop_requested:
                    break
                tick_period_ns = (
                    tick_start_ns - self._previous_tick_start_ns
                    if self._previous_tick_start_ns
                    else 0
                )
                self._previous_tick_start_ns = tick_start_ns
                self._update_controller(tick_start_ns)

                self.snapshot.begin_tick()
                self.bus.read_state_into(self.snapshot)
                if self.snapshot.device_alarm_count:
                    raise SafetyError(
                        "control-loop device alarm: "
                        + _device_alarm_details(self.snapshot)
                    )
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
                        self.phase.advance(
                            base_factor=self.controller_readout.phase_frequency_factor
                        )
                        action = self.policy.infer(observation)
                        np.copyto(self.telemetry_action, action)
                        self.assembler.commit_action(action)
                        physical_target = self.action_pipeline.apply(
                            action, self.commands, self.offsets
                        )
                        observation_valid = True
                    except StaleObservationError as exc:
                        sources: list[str] = []
                        if bool(self.snapshot.stale.any()):
                            stale_ids = [
                                str(servo_id)
                                for servo_id, stale in zip(
                                    SERVO_IDS, self.snapshot.stale, strict=True
                                )
                                if bool(stale)
                            ]
                            sources.append("servos=" + ",".join(stale_ids))
                        if self.sensors.imu_stale:
                            sources.append("imu")
                        if self.sensors.contacts_stale:
                            sources.append("contacts")
                        detail = "; ".join(sources) if sources else "unknown input"
                        raise SafetyError(
                            f"required policy observation became stale: {detail}"
                        ) from exc
                else:
                    physical_target = self.hold_physical_target
                    self.action_pipeline.implied_velocity_rad_s.fill(0.0)
                    self.action_pipeline.over_envelope.fill(False)

                if observation_valid:
                    np.copyto(self.hold_physical_target, physical_target)

                write_start_ns = clock_ns()
                self.snapshot.write_status = self.bus.write_positions(physical_target)
                write_elapsed_ns = clock_ns() - write_start_ns
                self.bus.read_extended_into(self.snapshot, SERVO_IDS[tick % ACTION_DIM])
                if self.snapshot.extended_device_status:
                    raise SafetyError(
                        "extended telemetry device alarm: "
                        f"{self.snapshot.extended_servo_id}:"
                        f"0x{self.snapshot.extended_device_status:02x}"
                    )
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
                # Include record capture/queue publication in the safety deadline.
                # The record itself carries pre-publication work so logging remains
                # a bounded one-way handoff from the hot loop.
                watchdog_work_ns = clock_ns() - tick_start_ns
                self.watchdog.observe(
                    tick_period_ns=tick_period_ns,
                    tick_work_ns=watchdog_work_ns,
                    bus_ok=bus_ok,
                )
                active_tick += int(observation_valid)
                tick += 1
            if (
                not self.stop_requested
                and self.args.max_active_ticks
                and active_tick < self.args.max_active_ticks
            ):
                raise SafetyError(
                    "total tick cap reached before active policy target: "
                    f"{active_tick}/{self.args.max_active_ticks}"
                )

    def close(self) -> None:
        errors: list[BaseException] = []
        torque_off_attempted = False
        torque_off_status = "not_attempted"
        torque_off_error: str | None = None
        # Cut power first. Writer/resource shutdown can block, and none of it is
        # more important than issuing the final redundant torque-off command.
        if self.bus is not None:
            torque_off_attempted = True
            try:
                status = self.bus.disable_torque()
                torque_off_status = status.name.lower()
                if status is not ErrorCode.OK:
                    cutoff_error = SafetyError(
                        f"cleanup torque-off failed: {status.name.lower()}"
                    )
                    torque_off_error = str(cutoff_error)
                    errors.append(cutoff_error)
            except BaseException as exc:
                torque_off_status = "exception"
                torque_off_error = f"{type(exc).__name__}: {exc}"
                errors.append(exc)

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
                self.bus.close()
            except BaseException as exc:
                errors.append(exc)
            self.bus = None
        if self._gc_was_enabled and not gc.isenabled():
            gc.enable()
        if errors and self.halt_reason == "normal_exit":
            self.halt_reason = f"{type(errors[0]).__name__}: {errors[0]}"
        if self.writer is not None:
            try:
                self.writer.close(
                    reason=self.halt_reason,
                    torque_off_attempted=torque_off_attempted,
                    torque_off_status=torque_off_status,
                    torque_off_error=torque_off_error,
                )
            except BaseException as exc:
                errors.append(exc)
        self.writer = None
        if errors:
            raise errors[0]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    runtime: Runtime | None = None
    exit_code = 0
    try:
        runtime = Runtime(args)
        signal.signal(signal.SIGINT, runtime.request_stop)
        signal.signal(signal.SIGTERM, runtime.request_stop)
        runtime.run()
    except (
        ConfigError,
        HardwareAuthorizationError,
        OSError,
        PolicyContractError,
        RealtimeSetupError,
        RuntimeError,
        SafetyError,
        TelemetryError,
        WatchdogTrip,
        ValueError,
    ) as exc:
        if runtime is not None and not runtime.stop_requested:
            runtime.halt_reason = f"{type(exc).__name__}: {exc}"
        print(f"runtime halted: {exc}", file=sys.stderr)
        exit_code = 2
    finally:
        if runtime is not None:
            try:
                runtime.close()
            except BaseException as exc:
                print(f"runtime cleanup failed: {exc}", file=sys.stderr)
                exit_code = 2
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
