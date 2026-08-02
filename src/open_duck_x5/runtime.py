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
from .controller import ControllerReadout, NullController, create_controller
from .hardware_guard import (
    HardwareAuthorizationError,
    add_hardware_ack_arguments,
    require_hardware_authorization,
)
from .imu_calibration import BNO055Calibration
from .policy import ONNX_SESSION_CONTRACT, OnnxPolicy, PolicyContractError
from .realtime import RealtimeSetupError, configure_realtime, prepare_realtime
from .safety import SafetyError, TorqueGuard, Watchdog, WatchdogTrip
from .sensors import (
    INITIAL_SENSOR_READY_TIMEOUT_S,
    BNO055Smbus,
    MockSensorHub,
    SensorHub,
    SensorReadout,
    X5FootContacts,
)
from .t247_command_routes import (
    T247_CALIBRATOR_SHA256,
    T247_COMMAND_MANIFEST_SHA256,
    T247_CONTEXT_ROUTER_SHA256,
    T247_OBSERVATION_DIM,
    T247_P30_SHA256,
    T247_POLICY_CONTRACT,
    T247_POLICY_SHA256,
    T247_REFERENCE_SHA256,
    T247_RUNTIME_CONTRACT_ID,
    T247CommandRouteCatalog,
    T247CommandRouteTransaction,
)
from .t247_command_routes import (
    calibrator_spec as t247_calibrator_spec,
)
from .telemetry import AsyncControlWriter, TelemetryError
from .timing import AbsoluteTicker
from .winner_v2 import WinnerV2ContractError
from .winner_v13_state_coherent import (
    CALIBRATION_TICKS as T247_CALIBRATION_TICKS,
)
from .winner_v13_state_coherent import (
    GraphAsset as T247GraphAsset,
)
from .winner_v13_state_coherent import (
    P30FitAsset as T247P30FitAsset,
)
from .winner_v13_state_coherent import (
    WinnerV13ContractError,
)

POLICY_CONTRACT_V1 = "v1-101"
POLICY_CONTRACT_T247 = T247_POLICY_CONTRACT
T247_GATE5_ACTIVE_TICKS = T247_CALIBRATION_TICKS + 600


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
    parser.add_argument(
        "--policy-contract",
        choices=(POLICY_CONTRACT_V1, POLICY_CONTRACT_T247),
        default=POLICY_CONTRACT_V1,
    )
    parser.add_argument("--calibrator", type=Path)
    parser.add_argument("--context-route-root", type=Path)
    parser.add_argument("--command-route-root", type=Path)
    parser.add_argument("--command-route-manifest", type=Path)
    parser.add_argument("--p30-fit", type=Path)
    parser.add_argument("--reference-table", type=Path)
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
    parser.add_argument(
        "--imu-calibration",
        type=Path,
        default=Path.home() / "imu_calibration.json",
        help="strict BNO055 calibration JSON; required by the serial Gate 5 runtime",
    )
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
    policy_contract = getattr(args, "policy_contract", POLICY_CONTRACT_V1)
    if policy_contract not in {POLICY_CONTRACT_V1, POLICY_CONTRACT_T247}:
        raise ValueError(f"unknown --policy-contract: {policy_contract}")
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
    t247_asset_names = (
        "calibrator",
        "context_route_root",
        "command_route_root",
        "command_route_manifest",
        "p30_fit",
        "reference_table",
    )
    t247_assets = {
        name: getattr(args, name, None) for name in t247_asset_names
    }
    if policy_contract == POLICY_CONTRACT_T247:
        missing = [name for name, value in t247_assets.items() if value is None]
        if args.policy is None:
            missing.insert(0, "policy")
        if missing:
            flags = ", ".join("--" + name.replace("_", "-") for name in missing)
            raise ValueError(f"T247 policy contract requires {flags}")
    elif any(value is not None for value in t247_assets.values()):
        raise ValueError(
            "T247 asset arguments require --policy-contract "
            f"{POLICY_CONTRACT_T247}"
        )
    telemetry_path = args.telemetry.expanduser().resolve()
    protected_paths = {args.config.expanduser().resolve()}
    protected_paths.add(args.imu_calibration.expanduser().resolve())
    if args.policy is not None:
        protected_paths.add(args.policy.expanduser().resolve())
    for value in t247_assets.values():
        if value is not None:
            protected_paths.add(value.expanduser().resolve())
    if args.bus == "serial":
        protected_paths.add(Path(args.device).expanduser().resolve())
    if telemetry_path in protected_paths:
        raise ValueError(
            "--telemetry must not overwrite config, IMU calibration, policy, or serial device"
        )


class Runtime:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        validate_runtime_args(args)
        self.policy_contract = getattr(
            args,
            "policy_contract",
            POLICY_CONTRACT_V1,
        )
        self.config_path = args.config.expanduser().resolve()
        self.config = DuckConfig.load(self.config_path)
        self.config_sha256 = _sha256(self.config_path)
        self.imu_calibration: BNO055Calibration | None = None
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
        self.t247_over_envelope = np.zeros(ACTION_DIM, dtype=np.bool_)
        self.t247_host: T247CommandRouteTransaction | None = None
        self.policy = None
        self.policy_path: Path | None = None
        self.policy_sha256: str | None = None
        self.t247_asset_paths: dict[str, Path] = {}
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
                if args.max_active_ticks <= T247_CALIBRATION_TICKS:
                    raise ValueError(
                        "Gate 5 T247 runtime requires more than 250 active ticks "
                        "so locomotion is actually exercised"
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
                self.imu_calibration = BNO055Calibration.load(args.imu_calibration)
                if self.policy_contract != POLICY_CONTRACT_T247:
                    raise PolicyContractError(
                        "serial Gate 5 requires --policy-contract "
                        f"{POLICY_CONTRACT_T247}"
                    )
                if args.max_active_ticks != T247_GATE5_ACTIVE_TICKS:
                    raise ValueError(
                        "serial T247 Gate 5 requires exactly 850 active ticks "
                        "(250 calibration + 600 locomotion)"
                    )
            if args.require_realtime:
                # This must happen before ONNX, sensors, controller, or writer
                # create threads. They then inherit housekeeping affinity.
                self.realtime_preparation = prepare_realtime(
                    cpu=args.rt_cpu,
                    require_isolated=True,
                )
            if args.controller == "none":
                self.controller = NullController()
            else:
                self.controller = create_controller(args.controller)
            # Drain the bounded joydev initialization batch before serial is
            # opened. Opening a Linux UHID consumer can trigger BlueZ/GATT work;
            # none of that belongs in the first servo transaction.
            self._require_controller_ready(reject_toggle=False)
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
                        calibration=self.imu_calibration,
                    )
                except BaseException:
                    contacts.close()
                    raise
                self.sensor_hub = SensorHub(imu, contacts)
            else:
                self.bus = MockSTS3215Bus()
                self.sensor_hub = MockSensorHub()

            self.policy_path = (
                args.policy.expanduser().resolve() if args.policy is not None else None
            )
            self.policy_sha256 = (
                _sha256(self.policy_path) if self.policy_path is not None else None
            )
            if self.policy_contract == POLICY_CONTRACT_V1:
                self.policy = OnnxPolicy(args.policy) if args.policy else None
            else:
                if self.policy_path is None or self.policy_sha256 != T247_POLICY_SHA256:
                    raise PolicyContractError(
                        "T247 provenance policy SHA-256 differs: "
                        f"{self.policy_sha256}"
                    )
                self.t247_asset_paths = {
                    "calibrator": args.calibrator.expanduser().resolve(),
                    "context_route_root": args.context_route_root.expanduser().resolve(),
                    "command_route_root": args.command_route_root.expanduser().resolve(),
                    "command_route_manifest": (
                        args.command_route_manifest.expanduser().resolve()
                    ),
                    "p30_fit": args.p30_fit.expanduser().resolve(),
                    "reference_table": args.reference_table.expanduser().resolve(),
                }
                if (
                    _sha256(self.t247_asset_paths["reference_table"])
                    != T247_REFERENCE_SHA256
                ):
                    raise PolicyContractError("T247 reference-table SHA-256 differs")
                catalog = T247CommandRouteCatalog(
                    context_root=self.t247_asset_paths["context_route_root"],
                    command_root=self.t247_asset_paths["command_route_root"],
                    command_manifest_path=self.t247_asset_paths[
                        "command_route_manifest"
                    ],
                    command_manifest_sha256=T247_COMMAND_MANIFEST_SHA256,
                    context_router_sha256=T247_CONTEXT_ROUTER_SHA256,
                )
                self.t247_host = T247CommandRouteTransaction(
                    calibrator=T247GraphAsset(
                        self.t247_asset_paths["calibrator"],
                        t247_calibrator_spec(),
                        frozenset({T247_CALIBRATOR_SHA256}),
                    ),
                    catalog=catalog,
                    p30_fit=T247P30FitAsset(
                        self.t247_asset_paths["p30_fit"],
                        frozenset({T247_P30_SHA256}),
                    ),
                    reference_table_path=self.t247_asset_paths["reference_table"],
                    enabled=True,
                    warmup_runs=3,
                    phase_frequency_factor_offset=(
                        self.config.phase_frequency_factor_offset
                    ),
                )
                self.t247_host.bind_soft_offsets(self.offsets)
            self.writer = AsyncControlWriter(
                args.telemetry,
                observation_dim=(
                    T247_OBSERVATION_DIM
                    if self.t247_host is not None
                    else self.assembler.observation.size
                ),
            )
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
        self._require_controller_ready(reject_toggle=True)
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
            self._require_controller_ready(reject_toggle=True)
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
        self._require_controller_ready(reject_toggle=True)
        if self.bus.set_gain_vectors(high_gains) is not ErrorCode.OK:
            raise SafetyError("failed to set operating gains")
        if self.bus.write_positions(self.hold_physical_target) is not ErrorCode.OK:
            raise SafetyError("failed to hold home target")

    def _run_startup_readiness(self, ticker: AbsoluteTicker) -> None:
        """Require one paused-loop-shaped transaction before policy ticks.

        This is a separately recorded AND-conjunct, not a discarded warmup. It
        is attempted once. Any controller, sensor, serial, alarm, or five-ms
        bus-budget failure exits the TorqueGuard before a policy transaction can
        be staged or committed.
        """

        tick_start_ns, release_lateness_ns = ticker.wait()
        if self.stop_requested:
            raise SafetyError("stop requested during startup readiness")
        self._require_controller_ready(reject_toggle=True)
        self.snapshot.begin_tick()
        self.bus.read_state_into(self.snapshot)
        self.sensor_hub.read_into(self.sensors, clock_ns())
        write_start_ns = clock_ns()
        self.snapshot.write_status = self.bus.write_positions(self.hold_physical_target)
        write_elapsed_ns = clock_ns() - write_start_ns
        self.bus.read_extended_into(self.snapshot, SERVO_IDS[0])
        self.snapshot.bus_total_ns = (
            self.snapshot.group_round_trip_ns
            + write_elapsed_ns
            + self.snapshot.extended_round_trip_ns
        )
        tick_work_ns = clock_ns() - tick_start_ns
        failures: list[str] = []
        failures.extend(
            f"{servo_id}:{ErrorCode(int(code)).name.lower()}"
            for servo_id, code in zip(SERVO_IDS, self.snapshot.status, strict=True)
            if int(code) != int(ErrorCode.OK)
        )
        if self.snapshot.write_status is not ErrorCode.OK:
            failures.append(f"write:{self.snapshot.write_status.name.lower()}")
        if self.snapshot.extended_status is not ErrorCode.OK:
            failures.append(
                f"extended-{self.snapshot.extended_servo_id}:"
                f"{self.snapshot.extended_status.name.lower()}"
            )
        if self.snapshot.partial_bytes:
            failures.append(f"partial-bytes:{self.snapshot.partial_bytes}")
        if self.snapshot.unexpected_packets:
            failures.append(f"unexpected-packets:{self.snapshot.unexpected_packets}")
        if self.snapshot.any_device_alarm:
            failures.append("device-alarm:" + _device_alarm_details(self.snapshot))
        if self.sensors.imu_stale:
            failures.append("sensor-stale:imu")
        if self.sensors.contacts_stale:
            failures.append("sensor-stale:contacts")
        bus_total_ms = self.snapshot.bus_total_ns / 1e6
        if bus_total_ms >= 5.0:
            failures.append(f"bus-total-ms:{bus_total_ms:.6f}")
        tick_work_ms = tick_work_ns / 1e6
        if tick_work_ns > self.watchdog.hard_overrun_ns:
            failures.append(f"tick-work-ms:{tick_work_ms:.6f}")
        details = {
            "status": "PASS" if not failures else "FAIL",
            "failures": failures,
            "paused": self.paused,
            "policy_staged": False,
            "policy_committed_ticks": (
                self.t247_host.committed_ticks if self.t247_host is not None else None
            ),
            "phase": self.phase.value,
            "tick_start_monotonic_ns": tick_start_ns,
            "tick_work_ms": tick_work_ms,
            "release_lateness_ms": release_lateness_ns / 1e6,
            "next_release_monotonic_ns": ticker.next_release_ns,
            "bus_total_ms": bus_total_ms,
            "group_round_trip_ms": self.snapshot.group_round_trip_ns / 1e6,
            "extended_round_trip_ms": self.snapshot.extended_round_trip_ns / 1e6,
            "write_status": self.snapshot.write_status.name.lower(),
            "all_fresh": not bool(np.any(self.snapshot.stale)),
            "per_servo_status": [
                ErrorCode(int(code)).name.lower() for code in self.snapshot.status
            ],
            "per_servo_device_status": [
                int(value) for value in self.snapshot.device_status
            ],
            "extended_status": self.snapshot.extended_status.name.lower(),
            "extended_device_status": int(self.snapshot.extended_device_status),
            "imu_stale": bool(self.sensors.imu_stale),
            "contacts_stale": bool(self.sensors.contacts_stale),
            "partial_bytes": self.snapshot.partial_bytes,
            "unexpected_packets": self.snapshot.unexpected_packets,
        }
        self.writer.publish_event("startup_readiness", details=details)
        if failures:
            raise SafetyError("startup readiness failed: " + ", ".join(failures))
        self._previous_tick_start_ns = tick_start_ns

    def _require_controller_ready(self, *, reject_toggle: bool) -> None:
        self.controller.read_into(self.controller_readout)
        now_ns = clock_ns()
        if self.args.controller != "none" and (
            not self.controller_readout.connected
            or now_ns - self.controller_readout.timestamp_ns > 250_000_000
        ):
            raise SafetyError("physical controller state is disconnected or stale")
        if reject_toggle and self.controller_readout.pause_toggle:
            raise SafetyError("physical controller toggled during startup readiness")

    def _update_controller(self, tick_start_ns: int) -> None:
        self._require_controller_ready(reject_toggle=False)
        np.copyto(self.commands, self.controller_readout.commands)
        if self.args.fixed_command_x is not None:
            self.commands[0] = float(self.args.fixed_command_x)
        if self.controller_readout.pause_toggle:
            if self.paused and self.policy is None and self.t247_host is None:
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
        if self.args.controller != "none" and (
            tick_start_ns - self.controller_readout.timestamp_ns > 250_000_000
        ):
            raise SafetyError("physical controller state is disconnected or stale")

    def _policy_start_details(self) -> dict[str, object] | None:
        if self.policy_path is None:
            return None
        if self.t247_host is None:
            return {
                "contract": POLICY_CONTRACT_V1,
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
        assets = {
            name: {
                "path": str(path),
                "sha256": _sha256(path) if path.is_file() else None,
            }
            for name, path in self.t247_asset_paths.items()
            if name not in {"context_route_root", "command_route_root"}
        }
        assets["context_route_root"] = {
            "path": str(self.t247_asset_paths["context_route_root"]),
            "verified_models": 6,
            "router_sha256": _sha256(
                self.t247_asset_paths["context_route_root"]
                / "policy.context-router.onnx"
            ),
        }
        assets["command_route_root"] = {
            "path": str(self.t247_asset_paths["command_route_root"]),
            "verified_models": 24,
        }
        return {
            "contract": POLICY_CONTRACT_T247,
            "path": str(self.policy_path),
            "sha256": self.policy_sha256,
            "calibration_ticks": T247_CALIBRATION_TICKS,
            "calibrator_inputs": {
                "obs": [1, 115],
                "previous_action": [1, 14],
                "h_in": [1, 64],
            },
            "locomotion_inputs": {
                "obs": [1, 115],
                "previous_action": [1, 14],
                "h_in": [1, 64],
                "calibration_context": [1, 64],
            },
            "outputs": {
                "action": [1, 14],
                "previous_action_out": [1, 14],
                "h_out": [1, 64],
            },
            "context_routes": 6,
            "exact_command_routes": 24,
            "fallback_preserved": True,
            "assets": assets,
        }

    def _runtime_start_details(self) -> dict[str, object]:
        sensor_diagnostics = self.sensor_hub.diagnostics()
        imu_diagnostics = dict(sensor_diagnostics["imu"])
        return {
            "contract_id": (
                T247_RUNTIME_CONTRACT_ID
                if self.t247_host is not None
                else CONTRACT_ID
            ),
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
            "sensors": {
                "initial_sample_ready_timeout_s": INITIAL_SENSOR_READY_TIMEOUT_S,
                "imu": {
                    "backend": "bno055_smbus" if self.args.bus == "serial" else "mock",
                    "i2c_device": (
                        f"/dev/i2c-{self.args.imu_bus}"
                        if self.args.bus == "serial"
                        else "mock://bno055"
                    ),
                    "address": self.args.imu_address,
                    "upside_down": self.config.imu_upside_down,
                    "identity_verified": bool(
                        imu_diagnostics.get("identity_verified", False)
                    ),
                    "calibration_applied": bool(
                        imu_diagnostics.get("calibration_applied", False)
                    ),
                    "calibration_readback_verified": bool(
                        imu_diagnostics.get("calibration_readback_verified", False)
                    ),
                    "calibration_profile_path": imu_diagnostics.get(
                        "calibration_profile_path"
                    ),
                    "calibration_profile_sha256": imu_diagnostics.get(
                        "calibration_profile_sha256"
                    ),
                    "calibration_source_sha256": imu_diagnostics.get(
                        "calibration_source_sha256"
                    ),
                },
                "contacts": {
                    "backend": "Hobot.GPIO" if self.args.bus == "serial" else "mock",
                    "numbering": "BCM",
                    "left": {"bcm": 22, "physical_pin": 15},
                    "right": {"bcm": 27, "physical_pin": 13},
                    "polarity": "raw GPIO false -> contact true",
                },
            },
            "policy": self._policy_start_details(),
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
        self.sensor_hub.wait_until_ready(INITIAL_SENSOR_READY_TIMEOUT_S)
        self.sensor_hub.read_into(self.sensors, clock_ns())
        if self.sensors.imu_stale or self.sensors.contacts_stale:
            stale_sources = []
            if self.sensors.imu_stale:
                stale_sources.append("imu")
            if self.sensors.contacts_stale:
                stale_sources.append("contacts")
            raise SafetyError(
                "initial sensor publication was already stale: "
                + ", ".join(stale_sources)
            )
        self._verify_all_servos()
        if self.stop_requested:
            return
        with TorqueGuard(self.bus) as guard:
            self._move_home_slowly(guard)
            ticker = AbsoluteTicker()
            if self.args.bus == "serial" and self.args.gate5_authorized:
                self._run_startup_readiness(ticker)
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
                t247_staged = False
                policy_stage: str | None = None
                if not self.paused and self.t247_host is not None:
                    policy_tick = self.t247_host.committed_ticks
                    policy_stage = (
                        "calibration"
                        if self.t247_host.confirmed_calibration_ticks
                        < T247_CALIBRATION_TICKS
                        else "locomotion"
                    )
                    try:
                        physical_target = self.t247_host.stage_tick(
                            tick_index=policy_tick,
                            logical_period_ns=CONTROL_PERIOD_NS,
                            servo_sample_tick_index=policy_tick,
                            imu_sample_tick_index=policy_tick,
                            contacts_sample_tick_index=policy_tick,
                            gyro_rad_s=self.sensors.gyro_rad_s,
                            acceleration_m_s2=self.sensors.acceleration_m_s2,
                            commands=self.commands,
                            positions_rad=self.logical_positions,
                            velocities_rad_s=self.logical_velocities,
                            foot_contacts=self.sensors.contacts,
                            servo_stale=self.snapshot.stale,
                            imu_stale=self.sensors.imu_stale,
                            contacts_stale=self.sensors.contacts_stale,
                            soft_offsets_rad=self.offsets,
                        )
                        np.copyto(
                            self.telemetry_action,
                            self.t247_host.normalized_action_view,
                        )
                        np.greater(
                            self.t247_host.target_pipeline.graph_rate_excess_rad_s,
                            0.0,
                            out=self.t247_over_envelope,
                        )
                        observation_valid = True
                        t247_staged = True
                    except (WinnerV13ContractError, WinnerV2ContractError) as exc:
                        raise SafetyError(f"T247 policy transaction failed: {exc}") from exc
                elif not self.paused and self.policy is not None:
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
                    if self.t247_host is None:
                        self.action_pipeline.implied_velocity_rad_s.fill(0.0)
                        self.action_pipeline.over_envelope.fill(False)
                    else:
                        self.t247_host.target_pipeline.implied_velocity_rad_s.fill(0.0)
                        self.t247_over_envelope.fill(False)

                if observation_valid and not t247_staged:
                    np.copyto(self.hold_physical_target, physical_target)

                write_start_ns = clock_ns()
                self.snapshot.write_status = self.bus.write_positions(physical_target)
                write_elapsed_ns = clock_ns() - write_start_ns
                if t247_staged:
                    if self.snapshot.write_status is not ErrorCode.OK:
                        try:
                            self.t247_host.complete_send(write_succeeded=False)
                        except WinnerV13ContractError as exc:
                            raise SafetyError(
                                "T247 target write failed; recurrent state was not committed"
                            ) from exc
                        raise SafetyError(
                            "T247 target write failed without faulting the policy host"
                        )
                    try:
                        self.t247_host.complete_send(write_succeeded=True)
                        if (
                            self.t247_host.confirmed_calibration_ticks
                            == T247_CALIBRATION_TICKS
                            and not self.t247_host.handoff_complete
                        ):
                            self.t247_host.confirm_calibration_handoff(True)
                    except WinnerV13ContractError as exc:
                        raise SafetyError(
                            f"T247 confirmed-send commit failed: {exc}"
                        ) from exc
                    np.copyto(self.hold_physical_target, physical_target)
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

                if self.t247_host is None:
                    telemetry_observation = self.assembler.observation
                    telemetry_sent_target = (
                        self.action_pipeline.previous_motor_target_rad
                    )
                    telemetry_implied_velocity = (
                        self.action_pipeline.implied_velocity_rad_s
                    )
                    telemetry_over_envelope = self.action_pipeline.over_envelope
                    selected_context_route = None
                    selected_command_route = None
                else:
                    telemetry_observation = self.t247_host.observation_view
                    telemetry_sent_target = self.t247_host.logical_target_view
                    telemetry_implied_velocity = (
                        self.t247_host.target_pipeline.implied_velocity_rad_s
                    )
                    telemetry_over_envelope = self.t247_over_envelope
                    selected_context_route = (
                        self.t247_host.selected_context_route
                    )
                    selected_command_route = (
                        self.t247_host.selected_command_route
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
                    telemetry_observation,
                    self.telemetry_action,
                    self.logical_positions,
                    telemetry_sent_target,
                    telemetry_implied_velocity,
                    telemetry_over_envelope,
                    policy_stage=policy_stage,
                    selected_context_route=selected_context_route,
                    selected_command_route=selected_command_route,
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
