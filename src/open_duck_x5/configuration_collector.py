from __future__ import annotations

import argparse
import hashlib
import json
import math
import queue
import signal
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .bus import ErrorCode, MockSTS3215Bus, ServoSnapshot, STS3215Bus
from .bus.types import ERROR_NAMES
from .clock import clock_ns
from .config import DuckConfig
from .configuration_profile import (
    METADATA_SCHEMA_VERSION,
    TICK_SCHEMA_VERSION,
    build_automatic_configuration_profile,
)
from .configuration_support import validate_supported_configuration_envelope_data
from .constants import ACTION_DIM, CONTROL_FREQUENCY_HZ, HOME_RAD, JOINT_NAMES, SERVO_IDS
from .hardware_guard import (
    HardwareAuthorizationError,
    add_hardware_ack_arguments,
    require_hardware_authorization,
)
from .imu_calibration import BNO055Calibration, CalibrationError
from .probe import ProbeInterrupted, _move_home_slowly, _verify_servos
from .realtime import RealtimeSetupError, configure_realtime, prepare_realtime
from .safety import Watchdog, WatchdogTrip
from .sensors import (
    INITIAL_SENSOR_READY_TIMEOUT_S,
    BNO055Smbus,
    MockSensorHub,
    SensorHub,
    SensorReadout,
    X5FootContacts,
)
from .timing import AbsoluteTicker

STAGE_TICKS = 201
TICK_COUNT = STAGE_TICKS * ACTION_DIM
MAX_DELAY_TICKS = 4
MINIMUM_CURRENT_SAMPLES_PER_JOINT = 10
MAXIMUM_TARGET_VELOCITY_RAD_S = 0.21
MAXIMUM_HOME_DEVIATION_RAD = 0.03
MINIMUM_TARGET_SPAN_RAD = 0.03
MAXIMUM_NONEXCITED_TARGET_SPAN_RAD = 1e-12
HOME_SECONDS = 5.0
WATCHDOG_FAILURES = 3


class ConfigurationCollectionError(RuntimeError):
    """Raised when an automatic configuration trace cannot complete safely."""


class _ImmediateTicker:
    """Deterministic no-wait clock used only by an explicitly mock collector."""

    def __init__(self) -> None:
        self._timestamp_ns = clock_ns()

    def wait(self) -> tuple[int, int]:
        self._timestamp_ns += int(1e9 / CONTROL_FREQUENCY_HZ)
        return self._timestamp_ns, 0


@dataclass(slots=True)
class ConfigurationExcitationRecord:
    tick: int = 0
    timestamp_ns: int = 0
    bus_total_ms: float = 0.0
    stage_joint: str = ""
    extended_servo_id: int = -1
    extended_status: int = int(ErrorCode.TIMEOUT)
    present_current_a: float = 0.0
    target_positions_rad: np.ndarray = field(
        default_factory=lambda: np.zeros(ACTION_DIM, dtype=np.float64)
    )
    actual_positions_rad: np.ndarray = field(
        default_factory=lambda: np.zeros(ACTION_DIM, dtype=np.float64)
    )
    gyro_rad_s: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float64))
    acceleration_m_s2: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float64))
    foot_contacts: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=np.float32))
    imu_timestamp_ns: int = 0
    contacts_timestamp_ns: int = 0
    status: np.ndarray = field(default_factory=lambda: np.zeros(ACTION_DIM, dtype=np.uint8))
    stale: np.ndarray = field(default_factory=lambda: np.ones(ACTION_DIM, dtype=np.bool_))
    imu_stale: bool = True
    contacts_stale: bool = True

    def capture(
        self,
        *,
        tick: int,
        timestamp_ns: int,
        stage_joint: str,
        targets: np.ndarray,
        snapshot: ServoSnapshot,
        sensors: SensorReadout,
    ) -> None:
        self.tick = tick
        self.timestamp_ns = timestamp_ns
        self.bus_total_ms = snapshot.bus_total_ns / 1e6
        self.stage_joint = stage_joint
        self.extended_servo_id = snapshot.extended_servo_id
        self.extended_status = int(snapshot.extended_status)
        self.present_current_a = snapshot.present_current_a
        np.copyto(self.target_positions_rad, targets)
        np.copyto(self.actual_positions_rad, snapshot.positions_rad)
        np.copyto(self.gyro_rad_s, sensors.gyro_rad_s)
        np.copyto(self.acceleration_m_s2, sensors.acceleration_m_s2)
        np.copyto(self.foot_contacts, sensors.contacts)
        self.imu_timestamp_ns = sensors.imu_timestamp_ns
        self.contacts_timestamp_ns = sensors.contacts_timestamp_ns
        np.copyto(self.status, snapshot.status)
        np.copyto(self.stale, snapshot.stale)
        self.imu_stale = sensors.imu_stale
        self.contacts_stale = sensors.contacts_stale

    def as_jsonable(self) -> dict[str, object]:
        currents: list[float | None] = [None] * ACTION_DIM
        if self.extended_status == int(ErrorCode.OK):
            try:
                index = SERVO_IDS.index(self.extended_servo_id)
            except ValueError:
                pass
            else:
                currents[index] = self.present_current_a
        return {
            "schema_version": TICK_SCHEMA_VERSION,
            "tick": self.tick,
            "timestamp_monotonic_ns": self.timestamp_ns,
            "bus_total_ms": self.bus_total_ms,
            "stage_joint": self.stage_joint,
            "target_positions_rad": self.target_positions_rad.tolist(),
            "actual_positions_rad": self.actual_positions_rad.tolist(),
            "present_current_a": currents,
            "gyro_rad_s": self.gyro_rad_s.tolist(),
            "acceleration_m_s2": self.acceleration_m_s2.tolist(),
            "foot_contacts": self.foot_contacts.tolist(),
            "imu_timestamp_monotonic_ns": self.imu_timestamp_ns,
            "contacts_timestamp_monotonic_ns": self.contacts_timestamp_ns,
            "per_servo_status": [ERROR_NAMES[int(code)] for code in self.status],
            "stale": self.stale.tolist(),
            "imu_stale": self.imu_stale,
            "contacts_stale": self.contacts_stale,
        }


class AsyncConfigurationWriter:
    """Preallocated bounded trace writer; JSON work stays off the control thread."""

    def __init__(self, path: Path, *, capacity: int) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._free: queue.SimpleQueue[ConfigurationExcitationRecord] = queue.SimpleQueue()
        self._pending: queue.Queue[ConfigurationExcitationRecord | None] = queue.Queue(
            maxsize=capacity
        )
        for _ in range(capacity):
            self._free.put(ConfigurationExcitationRecord())
        self._error: BaseException | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="configuration-jsonl-writer", daemon=True
        )
        self._thread.start()
        self._ready.wait()
        self._raise_if_failed()

    def _raise_if_failed(self) -> None:
        if self._error is not None:
            raise ConfigurationCollectionError(
                f"configuration trace writer failed: {self._error}"
            ) from self._error

    def publish(
        self,
        *,
        tick: int,
        timestamp_ns: int,
        stage_joint: str,
        targets: np.ndarray,
        snapshot: ServoSnapshot,
        sensors: SensorReadout,
    ) -> None:
        self._raise_if_failed()
        try:
            record = self._free.get_nowait()
        except queue.Empty as exc:
            raise ConfigurationCollectionError("configuration trace record pool exhausted") from exc
        record.capture(
            tick=tick,
            timestamp_ns=timestamp_ns,
            stage_joint=stage_joint,
            targets=targets,
            snapshot=snapshot,
            sensors=sensors,
        )
        try:
            self._pending.put_nowait(record)
        except queue.Full as exc:
            self._free.put(record)
            raise ConfigurationCollectionError("configuration trace queue overflow") from exc

    def _run(self) -> None:
        try:
            with self.path.open("x", encoding="utf-8", buffering=1) as handle:
                self._ready.set()
                while True:
                    record = self._pending.get()
                    if record is None:
                        return
                    handle.write(json.dumps(record.as_jsonable(), separators=(",", ":")) + "\n")
                    self._free.put(record)
        except BaseException as exc:
            self._error = exc
            self._ready.set()

    def close(self) -> None:
        while self._thread.is_alive():
            try:
                self._pending.put(None, timeout=0.1)
                break
            except queue.Full:
                continue
        self._thread.join()
        self._raise_if_failed()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _excitation(local_tick: int) -> float:
    return 0.015 * math.sin(2.0 * math.pi * local_tick / 40.0) + 0.005 * math.sin(
        2.0 * math.pi * local_tick / 20.0
    )


def _raise_if_stop_requested(args: argparse.Namespace) -> None:
    signum = getattr(args, "stop_signal", None)
    if signum is not None:
        raise ProbeInterrupted(f"signal:{signum}")


def _validate_arguments(
    args: argparse.Namespace,
) -> tuple[Path, Path, Path, Path, Path, Path | None]:
    if args.baudrate <= 0:
        raise ValueError("--baudrate must be positive")
    if not math.isfinite(args.timeout_ms) or args.timeout_ms <= 0.0:
        raise ValueError("--timeout-ms must be finite and positive")
    if not math.isfinite(args.mock_latency_ms) or args.mock_latency_ms < 0.0:
        raise ValueError("--mock-latency-ms must be finite and nonnegative")
    if args.i2c_bus < 0 or args.rt_cpu < 0:
        raise ValueError("--i2c-bus and --rt-cpu must be nonnegative")
    if not 1 <= args.rt_priority <= 99:
        raise ValueError("--rt-priority must be in 1..99")
    trace = args.trace.expanduser().resolve()
    metadata = args.metadata.expanduser().resolve()
    profile = args.profile.expanduser().resolve()
    configuration = args.config.expanduser().resolve()
    policy_envelope = (
        args.policy_envelope.expanduser().resolve() if args.policy_envelope is not None else None
    )
    partial = trace.with_name(trace.name + ".partial")
    metadata_temporary = metadata.with_name(metadata.name + ".tmp")
    profile_temporary = profile.with_name(profile.name + ".tmp")
    outputs = {
        trace,
        metadata,
        profile,
        partial,
        metadata_temporary,
        profile_temporary,
    }
    if len(outputs) != 6:
        raise ValueError("collector output and temporary paths must be distinct")
    protected = {configuration}
    if policy_envelope is not None:
        protected.add(policy_envelope)
    if args.imu_calibration is not None:
        protected.add(args.imu_calibration.expanduser().resolve())
    if args.bus == "serial":
        protected.add(Path(args.device).expanduser().resolve())
    if outputs & protected:
        raise ValueError("collector outputs must not overwrite hardware or configuration inputs")
    existing = sorted(str(path) for path in outputs if path.exists())
    if existing:
        raise ValueError("collector refuses existing output paths: " + ", ".join(existing))
    if args.mock_no_wait and args.bus != "mock":
        raise ValueError("--mock-no-wait is forbidden for the serial backend")
    if args.bus == "serial":
        require_hardware_authorization(
            hardware_authorized=args.hardware_authorized,
            suspended_or_benched=args.suspended_or_benched,
            operation="automatic configuration calibration",
        )
        if not args.moving_gate_authorized or not args.configuration_calibration_authorized:
            raise HardwareAuthorizationError(
                "automatic configuration calibration is blocked without both exact moving "
                "and configuration-calibration authorizations"
            )
        if args.imu_calibration is None:
            raise ValueError("serial configuration calibration requires --imu-calibration")
        if policy_envelope is None:
            raise ValueError(
                "serial configuration calibration requires a preregistered --policy-envelope"
            )
        if not args.require_realtime:
            raise RealtimeSetupError("serial configuration calibration requires --require-realtime")
    elif policy_envelope is not None:
        raise ValueError("--policy-envelope is reserved for physical serial collection")
    return trace, metadata, profile, configuration, partial, policy_envelope


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists():
        raise ConfigurationCollectionError(f"refuse existing temporary output: {temporary}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _metadata(
    *,
    args: argparse.Namespace,
    bus: Any,
    configuration_sha256: str,
    physical_home: np.ndarray,
    torque_off_confirmed: bool,
    policy_envelope_sha256: str | None,
    imu_calibration_sha256: str | None,
    imu_calibration_source_sha256: str | None,
) -> dict[str, Any]:
    stages = [
        {
            "joint_name": joint_name,
            "start_tick": index * STAGE_TICKS,
            "end_tick": (index + 1) * STAGE_TICKS,
        }
        for index, joint_name in enumerate(JOINT_NAMES)
    ]
    serial = args.bus == "serial"
    return {
        "schema_version": METADATA_SCHEMA_VERSION,
        "frequency_hz": CONTROL_FREQUENCY_HZ,
        "tick_count": TICK_COUNT,
        "max_delay_ticks": MAX_DELAY_TICKS,
        "minimum_stage_ticks": STAGE_TICKS,
        "minimum_target_span_rad": MINIMUM_TARGET_SPAN_RAD,
        "maximum_nonexcited_target_span_rad": MAXIMUM_NONEXCITED_TARGET_SPAN_RAD,
        "maximum_target_velocity_rad_s": MAXIMUM_TARGET_VELOCITY_RAD_S,
        "maximum_home_deviation_rad": MAXIMUM_HOME_DEVIATION_RAD,
        "minimum_current_samples_per_joint": MINIMUM_CURRENT_SAMPLES_PER_JOINT,
        "backend": args.bus,
        "device": str(bus.device),
        "informational_only": not serial,
        "hardware_authorized": bool(serial and args.hardware_authorized),
        "motion_authorized": bool(
            serial and args.moving_gate_authorized and args.configuration_calibration_authorized
        ),
        "configuration_calibration_authorized": bool(
            serial and args.configuration_calibration_authorized
        ),
        "suspended_or_benched": bool(serial and args.suspended_or_benched),
        "torque_off_confirmed": torque_off_confirmed,
        "telemetry_drop_count": 0,
        "configuration_sha256": configuration_sha256,
        "policy_envelope_sha256": policy_envelope_sha256,
        "imu_calibration_sha256": imu_calibration_sha256,
        "imu_calibration_source_sha256": imu_calibration_source_sha256,
        "physical_home_rad": physical_home.tolist(),
        "inventory": {
            "required_servo_ids": list(SERVO_IDS),
            "responding_servo_ids": list(bus.ids),
            "imu_present": True,
            "contacts_present": True,
        },
        "stages": stages,
    }


def run_collector(args: argparse.Namespace) -> dict[str, Any]:
    (
        trace_path,
        metadata_path,
        profile_path,
        config_path,
        partial_path,
        policy_envelope_path,
    ) = _validate_arguments(args)
    configuration = DuckConfig.load(config_path)
    physical_home = HOME_RAD + configuration.offsets_array
    configuration_sha256 = _sha256(config_path)
    policy_envelope_sha256: str | None = None
    if policy_envelope_path is not None:
        try:
            policy_envelope = json.loads(policy_envelope_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ConfigurationCollectionError(
                f"cannot read preregistered policy envelope: {exc}"
            ) from exc
        if not isinstance(policy_envelope, dict):
            raise ConfigurationCollectionError(
                "preregistered policy envelope must be a JSON object"
            )
        validate_supported_configuration_envelope_data(policy_envelope)
        policy_envelope_sha256 = _sha256(policy_envelope_path)

    preparation = None
    if args.bus == "serial":
        preparation = prepare_realtime(cpu=args.rt_cpu, require_isolated=True)
        bus = STS3215Bus(
            args.device,
            baudrate=args.baudrate,
            transaction_timeout_s=args.timeout_ms / 1000.0,
        )
    else:
        bus = MockSTS3215Bus(latency_s=args.mock_latency_ms / 1000.0)

    snapshot = ServoSnapshot.create()
    sensors = SensorReadout()
    targets = physical_home.copy()
    watchdog = Watchdog(
        hard_overrun_ns=2 * int(1e9 / CONTROL_FREQUENCY_HZ),
        max_consecutive_bus_failures=WATCHDOG_FAILURES,
    )
    writer: AsyncConfigurationWriter | None = None
    sensor_hub: SensorHub | MockSensorHub | None = None
    primary_error: BaseException | None = None
    torque_off_status = ErrorCode.IO
    torque_off_returned = False
    cleanup_failures: list[str] = []
    imu_calibration_sha256: str | None = None
    imu_calibration_source_sha256: str | None = None
    try:
        if bus.disable_torque() is not ErrorCode.OK:
            raise ConfigurationCollectionError("failed to establish torque-off before setup")
        if args.bus == "serial":
            calibration = BNO055Calibration.load(args.imu_calibration)
            imu_calibration_sha256 = calibration.profile_sha256
            imu_calibration_source_sha256 = calibration.source_sha256
            imu = BNO055Smbus(
                bus_number=args.i2c_bus,
                upside_down=configuration.imu_upside_down,
                calibration=calibration,
            )
            try:
                contacts = X5FootContacts()
            except BaseException:
                imu.close()
                raise
            sensor_hub = SensorHub(imu, contacts)
        else:
            sensor_hub = MockSensorHub()
        _verify_servos(bus, snapshot, reject_device_alarms=True)
        sensor_hub.wait_until_ready(INITIAL_SENSOR_READY_TIMEOUT_S)
        # Create every background thread while the main thread still has the
        # housekeeping affinity prepared by prepare_realtime().
        writer = AsyncConfigurationWriter(partial_path, capacity=TICK_COUNT)
        if preparation is not None:
            configure_realtime(preparation=preparation, priority=args.rt_priority)
        if args.bus == "serial":
            _move_home_slowly(
                bus,
                snapshot,
                physical_home,
                home_seconds=HOME_SECONDS,
                stop_check=lambda: _raise_if_stop_requested(args),
                watchdog=watchdog,
            )
        elif bus.enable_torque() is not ErrorCode.OK:
            raise ConfigurationCollectionError("mock torque setup failed")
        ticker: AbsoluteTicker | _ImmediateTicker = (
            _ImmediateTicker() if args.mock_no_wait else AbsoluteTicker()
        )
        previous_tick_start_ns = 0
        for tick in range(TICK_COUNT):
            _raise_if_stop_requested(args)
            tick_start_ns, _lateness_ns = ticker.wait()
            stage_index = tick // STAGE_TICKS
            local_tick = tick % STAGE_TICKS
            stage_joint = JOINT_NAMES[stage_index]
            targets[:] = physical_home
            targets[stage_index] += _excitation(local_tick)
            bus.exchange_into(targets, snapshot, tick)
            sensor_hub.read_into(sensors, clock_ns())
            bus_ok = (
                snapshot.write_status is ErrorCode.OK
                and snapshot.extended_status is ErrorCode.OK
                and snapshot.all_fresh
                and not snapshot.any_device_alarm
                and snapshot.partial_bytes == 0
                and snapshot.unexpected_packets == 0
            )
            if not bus_ok:
                raise WatchdogTrip(f"bus evidence invalid at tick {tick}")
            if sensors.imu_stale or sensors.contacts_stale:
                raise WatchdogTrip(f"sensor evidence stale at tick {tick}")
            writer.publish(
                tick=tick,
                timestamp_ns=tick_start_ns,
                stage_joint=stage_joint,
                targets=targets,
                snapshot=snapshot,
                sensors=sensors,
            )
            tick_period_ns = tick_start_ns - previous_tick_start_ns if previous_tick_start_ns else 0
            previous_tick_start_ns = tick_start_ns
            watchdog.observe(
                tick_period_ns=tick_period_ns,
                tick_work_ns=clock_ns() - tick_start_ns,
                bus_ok=bus_ok,
            )
    except BaseException as exc:
        primary_error = exc
    finally:
        try:
            torque_off_status = bus.disable_torque()
            torque_off_returned = True
        except BaseException as exc:
            cleanup_failures.append(f"torque-off raised {type(exc).__name__}: {exc}")
        if sensor_hub is not None:
            try:
                sensor_hub.close()
            except BaseException as exc:
                cleanup_failures.append(f"sensor close raised {type(exc).__name__}: {exc}")
        try:
            bus.close()
        except BaseException as exc:
            cleanup_failures.append(f"bus close raised {type(exc).__name__}: {exc}")
        if writer is not None:
            try:
                writer.close()
            except BaseException as exc:
                cleanup_failures.append(f"writer close raised {type(exc).__name__}: {exc}")

    if torque_off_returned and torque_off_status is not ErrorCode.OK:
        cleanup_failures.append(f"final torque-off failed: {torque_off_status.name.lower()}")
    if cleanup_failures:
        cleanup_reason = "; ".join(cleanup_failures)
        if primary_error is not None:
            primary_error = ConfigurationCollectionError(
                f"{type(primary_error).__name__}: {primary_error}; cleanup: {cleanup_reason}"
            )
        else:
            primary_error = ConfigurationCollectionError(cleanup_reason)
    if primary_error is not None:
        for path in (trace_path, metadata_path, profile_path):
            path.unlink(missing_ok=True)
        raise primary_error

    partial_path.replace(trace_path)
    metadata = _metadata(
        args=args,
        bus=bus,
        configuration_sha256=configuration_sha256,
        physical_home=physical_home,
        torque_off_confirmed=True,
        policy_envelope_sha256=policy_envelope_sha256,
        imu_calibration_sha256=imu_calibration_sha256,
        imu_calibration_source_sha256=imu_calibration_source_sha256,
    )
    _write_json_atomic(metadata_path, metadata)
    profile = build_automatic_configuration_profile(
        trace_path=trace_path,
        metadata_path=metadata_path,
        configuration_path=config_path,
    )
    _write_json_atomic(profile_path, profile)
    return {
        "status": "PASS_INFORMATIONAL_MOCK" if args.bus == "mock" else "REVIEW_REQUIRED",
        "backend": args.bus,
        "ticks": TICK_COUNT,
        "trace_sha256": _sha256(trace_path),
        "metadata_sha256": _sha256(metadata_path),
        "profile_sha256": _sha256(profile_path),
        "torque_off_confirmed": True,
        "authority": {
            "robot_clearance": False,
            "gate5": False,
            "runtime_deployment": False,
            "motion": False,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect a bounded automatic configuration response trace"
    )
    parser.add_argument("--bus", choices=("mock", "serial"), default="mock")
    parser.add_argument("--device", default="/dev/ttyS1")
    parser.add_argument("--baudrate", type=int, default=1_000_000)
    parser.add_argument("--timeout-ms", type=float, default=4.0)
    parser.add_argument("--mock-latency-ms", type=float, default=0.0)
    parser.add_argument("--mock-no-wait", action="store_true")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--imu-calibration", type=Path)
    parser.add_argument("--policy-envelope", type=Path)
    parser.add_argument("--i2c-bus", type=int, default=5)
    parser.add_argument("--require-realtime", action="store_true")
    parser.add_argument("--rt-cpu", type=int, default=7)
    parser.add_argument("--rt-priority", type=int, default=80)
    parser.add_argument("--moving-gate-authorized", action="store_true")
    parser.add_argument("--configuration-calibration-authorized", action="store_true")
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    add_hardware_ack_arguments(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.stop_signal = None

    def request_stop(signum, frame) -> None:
        del frame
        args.stop_signal = signum

    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        try:
            result = run_collector(args)
        except (
            CalibrationError,
            ConfigurationCollectionError,
            HardwareAuthorizationError,
            OSError,
            ProbeInterrupted,
            RealtimeSetupError,
            ValueError,
            RuntimeError,
            WatchdogTrip,
        ) as exc:
            parser.error(str(exc))
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
