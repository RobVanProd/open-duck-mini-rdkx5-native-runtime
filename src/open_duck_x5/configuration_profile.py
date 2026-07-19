from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

from .config import ConfigError, DuckConfig
from .configuration_support import (
    AUTOMATIC_METHOD,
    PROFILE_SCHEMA_VERSION,
    ConfigurationSupportError,
    validate_automatic_profile_data,
)
from .constants import (
    ACTION_DIM,
    CONTROL_FREQUENCY_HZ,
    HOME_RAD,
    JOINT_NAMES,
    SERVO_IDS,
)

METADATA_SCHEMA_VERSION = "open_duck_x5.configuration_excitation_metadata.v3"
TICK_SCHEMA_VERSION = "open_duck_x5.configuration_excitation_tick.v2"
MAXIMUM_CALIBRATION_TARGET_VELOCITY_RAD_S = 0.25
MAXIMUM_CALIBRATION_TARGET_SPAN_RAD = 0.06
MAXIMUM_CALIBRATION_HOME_DEVIATION_RAD = 0.03
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ConfigurationProfileError(ValueError):
    """Raised when raw automatic-excitation evidence cannot form a profile."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigurationProfileError(f"{label} must be an object")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing or extra:
        raise ConfigurationProfileError(f"{label} keys differ: missing={missing}, extra={extra}")


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigurationProfileError(f"{label} must be boolean")
    return value


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigurationProfileError(f"{label} must be an integer >= {minimum}")
    return value


def _finite(value: Any, label: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationProfileError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ConfigurationProfileError(f"{label} must be finite")
    if nonnegative and result < 0.0:
        raise ConfigurationProfileError(f"{label} must be nonnegative")
    return result


def _vector(value: Any, length: int, label: str) -> np.ndarray:
    if not isinstance(value, list) or len(value) != length:
        raise ConfigurationProfileError(f"{label} must contain {length} values")
    return np.asarray(
        [_finite(item, f"{label}[{index}]") for index, item in enumerate(value)],
        dtype=np.float64,
    )


def _load_metadata(path: Path) -> dict[str, Any]:
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationProfileError(f"could not read excitation metadata: {exc}") from exc
    metadata = _object(metadata, "metadata")
    _exact_keys(
        metadata,
        {
            "schema_version",
            "frequency_hz",
            "tick_count",
            "max_delay_ticks",
            "minimum_stage_ticks",
            "minimum_target_span_rad",
            "maximum_nonexcited_target_span_rad",
            "maximum_target_velocity_rad_s",
            "minimum_current_samples_per_joint",
            "backend",
            "device",
            "informational_only",
            "hardware_authorized",
            "motion_authorized",
            "configuration_calibration_authorized",
            "suspended_or_benched",
            "torque_off_confirmed",
            "telemetry_drop_count",
            "configuration_sha256",
            "policy_envelope_sha256",
            "imu_calibration_sha256",
            "imu_calibration_source_sha256",
            "physical_home_rad",
            "maximum_home_deviation_rad",
            "inventory",
            "stages",
        },
        "metadata",
    )
    if metadata["schema_version"] != METADATA_SCHEMA_VERSION:
        raise ConfigurationProfileError("metadata schema_version is unsupported")
    if _finite(metadata["frequency_hz"], "metadata.frequency_hz") != CONTROL_FREQUENCY_HZ:
        raise ConfigurationProfileError("configuration excitation must run at 50 Hz")
    tick_count = _integer(metadata["tick_count"], "metadata.tick_count", minimum=1)
    max_delay = _integer(metadata["max_delay_ticks"], "metadata.max_delay_ticks")
    if max_delay > 10:
        raise ConfigurationProfileError("metadata.max_delay_ticks exceeds 10")
    minimum_stage_ticks = _integer(
        metadata["minimum_stage_ticks"], "metadata.minimum_stage_ticks", minimum=8
    )
    if minimum_stage_ticks <= max_delay + 3:
        raise ConfigurationProfileError("minimum_stage_ticks is too short for delay fitting")
    if (
        _finite(
            metadata["minimum_target_span_rad"],
            "metadata.minimum_target_span_rad",
            nonnegative=True,
        )
        <= 0.0
    ):
        raise ConfigurationProfileError("minimum_target_span_rad must be positive")
    _finite(
        metadata["maximum_nonexcited_target_span_rad"],
        "metadata.maximum_nonexcited_target_span_rad",
        nonnegative=True,
    )
    maximum_target_velocity = _finite(
        metadata["maximum_target_velocity_rad_s"],
        "metadata.maximum_target_velocity_rad_s",
        nonnegative=True,
    )
    if not 0.0 < maximum_target_velocity <= MAXIMUM_CALIBRATION_TARGET_VELOCITY_RAD_S:
        raise ConfigurationProfileError("maximum_target_velocity_rad_s must be in (0, 0.25]")
    _integer(
        metadata["minimum_current_samples_per_joint"],
        "metadata.minimum_current_samples_per_joint",
        minimum=1,
    )
    backend = metadata["backend"]
    if not isinstance(backend, str) or backend not in {"mock", "serial"}:
        raise ConfigurationProfileError("metadata.backend must be 'mock' or 'serial'")
    if not isinstance(metadata["device"], str) or not metadata["device"].strip():
        raise ConfigurationProfileError("metadata.device must be a nonempty string")
    informational_only = _boolean(metadata["informational_only"], "metadata.informational_only")
    hardware_authorized = _boolean(metadata["hardware_authorized"], "metadata.hardware_authorized")
    motion_authorized = _boolean(metadata["motion_authorized"], "metadata.motion_authorized")
    calibration_authorized = _boolean(
        metadata["configuration_calibration_authorized"],
        "metadata.configuration_calibration_authorized",
    )
    suspended_or_benched = _boolean(
        metadata["suspended_or_benched"], "metadata.suspended_or_benched"
    )
    if backend == "mock":
        if (
            not informational_only
            or hardware_authorized
            or motion_authorized
            or calibration_authorized
            or suspended_or_benched
        ):
            raise ConfigurationProfileError(
                "mock metadata must be informational_only without physical authority"
            )
        if (
            metadata["imu_calibration_sha256"] is not None
            or metadata["imu_calibration_source_sha256"] is not None
        ):
            raise ConfigurationProfileError("mock metadata cannot claim IMU calibration hashes")
        if metadata["policy_envelope_sha256"] is not None:
            raise ConfigurationProfileError(
                "mock metadata cannot claim a preregistered policy envelope"
            )
    elif informational_only:
        raise ConfigurationProfileError("serial metadata cannot be informational_only")
    elif (
        not hardware_authorized
        or not motion_authorized
        or not calibration_authorized
        or not suspended_or_benched
    ):
        raise ConfigurationProfileError(
            "serial metadata lacks exact hardware, motion, or supported-state authority"
        )
    else:
        for key in (
            "policy_envelope_sha256",
            "imu_calibration_sha256",
            "imu_calibration_source_sha256",
        ):
            value = metadata[key]
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                raise ConfigurationProfileError(f"metadata.{key} is invalid")
    if not _boolean(metadata["torque_off_confirmed"], "metadata.torque_off_confirmed"):
        raise ConfigurationProfileError("metadata lacks final torque-off confirmation")
    if _integer(metadata["telemetry_drop_count"], "metadata.telemetry_drop_count"):
        raise ConfigurationProfileError("metadata reports telemetry drops")
    configuration_sha256 = metadata["configuration_sha256"]
    if not isinstance(configuration_sha256, str) or not _SHA256_RE.fullmatch(configuration_sha256):
        raise ConfigurationProfileError("metadata.configuration_sha256 is invalid")
    metadata["physical_home_rad"] = _vector(
        metadata["physical_home_rad"], ACTION_DIM, "metadata.physical_home_rad"
    ).tolist()
    maximum_home_deviation = _finite(
        metadata["maximum_home_deviation_rad"],
        "metadata.maximum_home_deviation_rad",
        nonnegative=True,
    )
    if not 0.0 < maximum_home_deviation <= MAXIMUM_CALIBRATION_HOME_DEVIATION_RAD:
        raise ConfigurationProfileError("maximum_home_deviation_rad must be in (0, 0.03]")

    inventory = _object(metadata["inventory"], "metadata.inventory")
    _exact_keys(
        inventory,
        {
            "required_servo_ids",
            "responding_servo_ids",
            "imu_present",
            "contacts_present",
        },
        "metadata.inventory",
    )
    if inventory["required_servo_ids"] != list(SERVO_IDS):
        raise ConfigurationProfileError("metadata changes the frozen required servo IDs")
    if inventory["responding_servo_ids"] != list(SERVO_IDS):
        raise ConfigurationProfileError("automatic excitation requires all frozen servos")
    if not _boolean(inventory["imu_present"], "metadata.inventory.imu_present"):
        raise ConfigurationProfileError("automatic excitation requires the IMU")
    if not _boolean(inventory["contacts_present"], "metadata.inventory.contacts_present"):
        raise ConfigurationProfileError("automatic excitation requires both contacts")

    stages = metadata["stages"]
    if not isinstance(stages, list) or len(stages) != ACTION_DIM:
        raise ConfigurationProfileError("metadata requires one stage for every frozen joint")
    expected_start = 0
    stage_names: list[str] = []
    for index, raw_stage in enumerate(stages):
        stage = _object(raw_stage, f"metadata.stages[{index}]")
        _exact_keys(stage, {"joint_name", "start_tick", "end_tick"}, f"stage[{index}]")
        joint_name = stage["joint_name"]
        if joint_name != JOINT_NAMES[index]:
            raise ConfigurationProfileError("metadata stage order differs from frozen joint order")
        start = _integer(stage["start_tick"], f"stage[{index}].start_tick")
        end = _integer(stage["end_tick"], f"stage[{index}].end_tick", minimum=1)
        if start != expected_start or end <= start:
            raise ConfigurationProfileError("metadata stages must be contiguous and nonempty")
        if end - start < minimum_stage_ticks:
            raise ConfigurationProfileError(f"stage {joint_name} is too short")
        expected_start = end
        stage_names.append(joint_name)
    if expected_start != tick_count or stage_names != list(JOINT_NAMES):
        raise ConfigurationProfileError("metadata stages do not cover the complete tick population")
    return metadata


def _expected_stage(metadata: dict[str, Any], tick: int, stage_index: int) -> tuple[str, int]:
    stages = metadata["stages"]
    while stage_index < len(stages) and tick >= int(stages[stage_index]["end_tick"]):
        stage_index += 1
    if stage_index >= len(stages):
        raise ConfigurationProfileError(f"tick {tick} lies outside all stages")
    return str(stages[stage_index]["joint_name"]), stage_index


def _read_trace(
    path: Path, metadata: dict[str, Any]
) -> tuple[
    np.ndarray,
    np.ndarray,
    list[list[tuple[int, float]]],
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
]:
    tick_count = int(metadata["tick_count"])
    targets = np.zeros((tick_count, ACTION_DIM), dtype=np.float64)
    actual = np.zeros((tick_count, ACTION_DIM), dtype=np.float64)
    currents: list[list[tuple[int, float]]] = [[] for _ in range(ACTION_DIM)]
    gyro = np.zeros((tick_count, 3), dtype=np.float64)
    acceleration = np.zeros((tick_count, 3), dtype=np.float64)
    bus_total_ms = np.zeros(tick_count, dtype=np.float64)
    timestamps_ns = np.zeros(tick_count, dtype=np.int64)
    expected_keys = {
        "schema_version",
        "tick",
        "timestamp_monotonic_ns",
        "bus_total_ms",
        "stage_joint",
        "target_positions_rad",
        "actual_positions_rad",
        "present_current_a",
        "gyro_rad_s",
        "acceleration_m_s2",
        "foot_contacts",
        "imu_timestamp_monotonic_ns",
        "contacts_timestamp_monotonic_ns",
        "per_servo_status",
        "stale",
        "imu_stale",
        "contacts_stale",
    }
    previous_timestamp = -1
    previous_imu_timestamp = -1
    previous_contacts_timestamp = -1
    stage_index = 0
    row_count = 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            for row_count, line in enumerate(handle, start=1):
                tick = row_count - 1
                if tick >= tick_count:
                    raise ConfigurationProfileError("trace has more rows than metadata.tick_count")
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ConfigurationProfileError(f"trace row {tick} is invalid JSON") from exc
                row = _object(row, f"trace row {tick}")
                _exact_keys(row, expected_keys, f"trace row {tick}")
                if row["schema_version"] != TICK_SCHEMA_VERSION:
                    raise ConfigurationProfileError(f"trace row {tick} schema is unsupported")
                if row["tick"] != tick:
                    raise ConfigurationProfileError(f"trace tick sequence breaks at row {tick}")
                timestamp = _integer(
                    row["timestamp_monotonic_ns"], f"trace row {tick} timestamp", minimum=1
                )
                if timestamp <= previous_timestamp:
                    raise ConfigurationProfileError("trace timestamps are not strictly monotonic")
                previous_timestamp = timestamp
                timestamps_ns[tick] = timestamp
                bus_total_ms[tick] = _finite(
                    row["bus_total_ms"], f"trace row {tick} bus_total_ms", nonnegative=True
                )
                expected_stage, stage_index = _expected_stage(metadata, tick, stage_index)
                if row["stage_joint"] != expected_stage:
                    raise ConfigurationProfileError(f"trace row {tick} stage label is wrong")
                targets[tick] = _vector(
                    row["target_positions_rad"], ACTION_DIM, f"trace row {tick} targets"
                )
                actual[tick] = _vector(
                    row["actual_positions_rad"], ACTION_DIM, f"trace row {tick} actual"
                )
                current_values = row["present_current_a"]
                if not isinstance(current_values, list) or len(current_values) != ACTION_DIM:
                    raise ConfigurationProfileError(
                        f"trace row {tick} present_current_a must contain 14 values/nulls"
                    )
                for joint_index, value in enumerate(current_values):
                    if value is not None:
                        currents[joint_index].append(
                            (
                                tick,
                                _finite(
                                    value,
                                    f"trace row {tick} current[{joint_index}]",
                                    nonnegative=True,
                                ),
                            )
                        )
                gyro[tick] = _vector(row["gyro_rad_s"], 3, f"trace row {tick} gyro")
                acceleration[tick] = _vector(
                    row["acceleration_m_s2"], 3, f"trace row {tick} acceleration"
                )
                _vector(row["foot_contacts"], 2, f"trace row {tick} contacts")
                imu_timestamp = _integer(
                    row["imu_timestamp_monotonic_ns"],
                    f"trace row {tick} IMU timestamp",
                    minimum=1,
                )
                contacts_timestamp = _integer(
                    row["contacts_timestamp_monotonic_ns"],
                    f"trace row {tick} contacts timestamp",
                    minimum=1,
                )
                if imu_timestamp < previous_imu_timestamp:
                    raise ConfigurationProfileError("IMU timestamps move backward")
                if contacts_timestamp < previous_contacts_timestamp:
                    raise ConfigurationProfileError("contact timestamps move backward")
                previous_imu_timestamp = imu_timestamp
                previous_contacts_timestamp = contacts_timestamp
                if row["per_servo_status"] != ["ok"] * ACTION_DIM:
                    raise ConfigurationProfileError(f"trace row {tick} has a transaction failure")
                if row["stale"] != [False] * ACTION_DIM:
                    raise ConfigurationProfileError(f"trace row {tick} has stale servo data")
                if _boolean(row["imu_stale"], f"trace row {tick} imu_stale"):
                    raise ConfigurationProfileError(f"trace row {tick} has stale IMU data")
                if _boolean(row["contacts_stale"], f"trace row {tick} contacts_stale"):
                    raise ConfigurationProfileError(f"trace row {tick} has stale contact data")
    except OSError as exc:
        raise ConfigurationProfileError(f"could not read excitation trace: {exc}") from exc
    if row_count != tick_count:
        raise ConfigurationProfileError(
            f"trace row population is {row_count}, expected {tick_count}"
        )
    return targets, actual, currents, gyro, acceleration, bus_total_ms, timestamps_ns


def _fit_joint_response(
    target: np.ndarray,
    actual: np.ndarray,
    *,
    max_delay_ticks: int,
    period_s: float,
) -> tuple[float, float, float]:
    best: tuple[float, int, float, float] | None = None
    count = target.size
    for delay in range(max_delay_ticks + 1):
        start = max(1, delay)
        sample_count = count - start
        if sample_count < 4:
            continue
        response = actual[start:]
        previous = actual[start - 1 : count - 1]
        delayed_target = target[start - delay : count - delay]
        design = np.column_stack((previous, delayed_target, np.ones(sample_count)))
        coefficients, *_ = np.linalg.lstsq(design, response, rcond=None)
        pole = float(coefficients[0])
        input_coefficient = float(coefficients[1])
        if not (0.0 <= pole < 0.999999 and input_coefficient > 0.0):
            continue
        residual = response - design @ coefficients
        rmse = float(np.sqrt(np.mean(np.square(residual))))
        if not math.isfinite(rmse):
            continue
        candidate = (rmse, delay, pole, input_coefficient)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    if best is None:
        raise ConfigurationProfileError("no stable positive-gain joint response fit")
    _rmse, delay, pole, input_coefficient = best
    gain = input_coefficient / (1.0 - pole)
    time_constant = 0.0 if pole <= 1e-12 else -period_s / math.log(pole)
    if not math.isfinite(gain) or gain < 0.0:
        raise ConfigurationProfileError("joint response gain is invalid")
    if not math.isfinite(time_constant) or time_constant < 0.0:
        raise ConfigurationProfileError("joint response time constant is invalid")
    return float(delay), float(gain), float(time_constant)


def build_automatic_configuration_profile(
    *, trace_path: Path, metadata_path: Path, configuration_path: Path
) -> dict[str, Any]:
    trace_path = trace_path.expanduser().resolve()
    metadata_path = metadata_path.expanduser().resolve()
    configuration_path = configuration_path.expanduser().resolve()
    metadata = _load_metadata(metadata_path)
    try:
        configuration_sha256 = _sha256(configuration_path)
    except OSError as exc:
        raise ConfigurationProfileError(f"could not read configuration: {exc}") from exc
    if configuration_sha256 != metadata["configuration_sha256"]:
        raise ConfigurationProfileError("configuration SHA-256 differs from metadata")
    try:
        configuration = DuckConfig.load(configuration_path)
    except (ConfigError, OSError) as exc:
        raise ConfigurationProfileError(f"could not load configuration: {exc}") from exc
    expected_physical_home = HOME_RAD + configuration.offsets_array
    if not np.array_equal(
        np.asarray(metadata["physical_home_rad"], dtype=np.float64),
        expected_physical_home,
    ):
        raise ConfigurationProfileError(
            "metadata physical_home_rad differs from frozen home plus configuration offsets"
        )
    (
        targets,
        actual,
        currents,
        gyro,
        acceleration,
        bus_total_ms,
        timestamps_ns,
    ) = _read_trace(trace_path, metadata)
    period_s = 1.0 / float(metadata["frequency_hz"])
    minimum_target_span = float(metadata["minimum_target_span_rad"])
    max_other_span = float(metadata["maximum_nonexcited_target_span_rad"])
    minimum_current_samples = int(metadata["minimum_current_samples_per_joint"])
    max_delay = int(metadata["max_delay_ticks"])
    maximum_target_velocity = float(metadata["maximum_target_velocity_rad_s"])
    physical_home = np.asarray(metadata["physical_home_rad"], dtype=np.float64)
    maximum_home_deviation = float(metadata["maximum_home_deviation_rad"])

    tick_period_ms = np.diff(timestamps_ns.astype(np.float64)) / 1e6
    tick_period_p99_ms = float(np.percentile(tick_period_ms, 99))
    tick_period_p99_9_ms = float(np.percentile(tick_period_ms, 99.9))
    bus_total_max_ms = float(np.max(bus_total_ms))
    if tick_period_p99_ms > 21.0:
        raise ConfigurationProfileError(f"trace tick p99 {tick_period_p99_ms} ms exceeds 21 ms")
    if tick_period_p99_9_ms > 22.0:
        raise ConfigurationProfileError(f"trace tick p99.9 {tick_period_p99_9_ms} ms exceeds 22 ms")
    if bus_total_max_ms >= 5.0:
        raise ConfigurationProfileError(
            f"trace bus maximum {bus_total_max_ms} ms is not below 5 ms"
        )

    target_deltas = np.diff(np.vstack((physical_home, targets)), axis=0)
    maximum_observed_velocity = float(
        np.max(np.abs(target_deltas)) * float(metadata["frequency_hz"])
    )
    if maximum_observed_velocity > maximum_target_velocity + 1e-12:
        raise ConfigurationProfileError(
            "trace exceeds maximum target velocity, including stage boundaries"
        )

    joint_response: dict[str, dict[str, float]] = {}
    for joint_index, (joint_name, stage) in enumerate(
        zip(JOINT_NAMES, metadata["stages"], strict=True)
    ):
        start = int(stage["start_tick"])
        end = int(stage["end_tick"])
        stage_targets = targets[start:end]
        excited_target = stage_targets[:, joint_index]
        target_span = float(np.ptp(excited_target))
        if target_span < minimum_target_span:
            raise ConfigurationProfileError(
                f"stage {joint_name} target span {target_span} is below minimum"
            )
        if target_span > MAXIMUM_CALIBRATION_TARGET_SPAN_RAD:
            raise ConfigurationProfileError(
                f"stage {joint_name} target span {target_span} exceeds 0.06 rad"
            )
        maximum_excited_deviation = float(
            np.max(np.abs(excited_target - physical_home[joint_index]))
        )
        if maximum_excited_deviation > maximum_home_deviation + 1e-12:
            raise ConfigurationProfileError(
                f"stage {joint_name} exceeds maximum deviation from home"
            )
        target_velocity = np.abs(np.diff(excited_target)) * float(metadata["frequency_hz"])
        if (
            target_velocity.size
            and float(np.max(target_velocity)) > maximum_target_velocity + 1e-12
        ):
            raise ConfigurationProfileError(f"stage {joint_name} exceeds maximum target velocity")
        for other_index, other_name in enumerate(JOINT_NAMES):
            if other_index == joint_index:
                continue
            span = float(np.ptp(stage_targets[:, other_index]))
            if span > max_other_span:
                raise ConfigurationProfileError(
                    f"stage {joint_name} also excites {other_name}: span={span}"
                )
            deviation = float(
                np.max(np.abs(stage_targets[:, other_index] - physical_home[other_index]))
            )
            if deviation > max_other_span:
                raise ConfigurationProfileError(
                    f"stage {joint_name} holds {other_name} away from home: deviation={deviation}"
                )
        delay, gain, time_constant = _fit_joint_response(
            excited_target,
            actual[start:end, joint_index],
            max_delay_ticks=max_delay,
            period_s=period_s,
        )
        current_samples = [value for tick, value in currents[joint_index] if start <= tick < end]
        if len(current_samples) < minimum_current_samples:
            raise ConfigurationProfileError(
                f"joint {joint_name} has {len(current_samples)} current samples; "
                f"requires {minimum_current_samples}"
            )
        joint_response[joint_name] = {
            "delay_ticks": delay,
            "gain_ratio": gain,
            "time_constant_s": time_constant,
            "tracking_p95_rad": float(
                np.percentile(np.abs(actual[start:end, joint_index] - excited_target), 95)
            ),
            "current_p95_a": float(np.percentile(current_samples, 95)),
        }

    acceleration_norm = np.linalg.norm(acceleration, axis=1)
    inventory = metadata["inventory"]
    profile: dict[str, Any] = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "source": {
            "method": AUTOMATIC_METHOD,
            "backend": str(metadata["backend"]),
            "device": str(metadata["device"]),
            "informational_only": bool(metadata["informational_only"]),
            "trace_sha256": _sha256(trace_path),
            "metadata_sha256": _sha256(metadata_path),
            "configuration_sha256": str(metadata["configuration_sha256"]),
            "policy_envelope_sha256": metadata["policy_envelope_sha256"],
            "manual_measurements_used": False,
            "hardware_authorized": bool(metadata["hardware_authorized"]),
            "motion_authorized": bool(metadata["motion_authorized"]),
            "configuration_calibration_authorized": bool(
                metadata["configuration_calibration_authorized"]
            ),
            "suspended_or_benched": bool(metadata["suspended_or_benched"]),
            "torque_off_confirmed": bool(metadata["torque_off_confirmed"]),
        },
        "inventory": {
            "required_servo_ids": list(inventory["required_servo_ids"]),
            "responding_servo_ids": list(inventory["responding_servo_ids"]),
            "imu_present": bool(inventory["imu_present"]),
            "contacts_present": bool(inventory["contacts_present"]),
        },
        "sample_contract": {
            "frequency_hz": float(metadata["frequency_hz"]),
            "tick_count": int(metadata["tick_count"]),
            "complete": True,
            "stale_sample_count": 0,
            "transaction_failure_count": 0,
            "telemetry_drop_count": int(metadata["telemetry_drop_count"]),
            "tick_period_p99_ms": tick_period_p99_ms,
            "tick_period_p99_9_ms": tick_period_p99_9_ms,
            "bus_total_max_ms": bus_total_max_ms,
        },
        "joint_response": joint_response,
        "body_response": {
            "pitch_rate_p95_rad_s": float(np.percentile(np.abs(gyro[:, 1]), 95)),
            "roll_rate_p95_rad_s": float(np.percentile(np.abs(gyro[:, 0]), 95)),
            "acceleration_norm_p95_m_s2": float(np.percentile(acceleration_norm, 95)),
        },
    }
    try:
        issues = validate_automatic_profile_data(profile)
    except ConfigurationSupportError as exc:
        raise ConfigurationProfileError(f"generated profile is invalid: {exc}") from exc
    allowed_issues = {"source.informational_only_mock"}
    unexpected_issues = [issue for issue in issues if issue not in allowed_issues]
    if unexpected_issues:
        raise ConfigurationProfileError(
            "generated profile has hold issues: " + ", ".join(unexpected_issues)
        )
    return profile


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an automatic configuration profile from excitation evidence"
    )
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = args.output.expanduser().resolve()
    inputs = {
        args.trace.expanduser().resolve(),
        args.metadata.expanduser().resolve(),
        args.configuration.expanduser().resolve(),
    }
    if output in inputs:
        print("result=FAIL reason=--output must not overwrite an input")
        return 2
    try:
        output.unlink(missing_ok=True)
    except OSError as exc:
        print(f"result=FAIL reason=could not clear prior output: {exc}")
        return 2
    try:
        profile = build_automatic_configuration_profile(
            trace_path=args.trace,
            metadata_path=args.metadata,
            configuration_path=args.configuration,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except ConfigurationProfileError as exc:
        print(f"result=FAIL reason={exc}")
        return 2
    print(
        "result=PASS "
        f"joints={len(profile['joint_response'])} "
        f"ticks={profile['sample_contract']['tick_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
