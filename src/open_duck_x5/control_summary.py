from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from .bus.types import ERROR_NAMES, ErrorCode
from .constants import (
    ACTION_DIM,
    CONTRACT_ID,
    ENVELOPE_MONITOR_RAD_S,
    JOINT_NAMES,
    OBSERVATION_DIM,
    SERVO_IDS,
)
from .policy import ONNX_SESSION_CONTRACT
from .t247_command_routes import (
    ROUTE_NAMES as T247_ROUTE_NAMES,
)
from .t247_command_routes import (
    T247_CALIBRATION_TICKS,
    T247_CALIBRATOR_SHA256,
    T247_COMMAND_MANIFEST_SHA256,
    T247_CONTEXT_ROUTER_SHA256,
    T247_OBSERVATION_DIM,
    T247_P30_SHA256,
    T247_POLICY_CONTRACT,
    T247_POLICY_SHA256,
    T247_REFERENCE_SHA256,
    T247_RUNTIME_CONTRACT_ID,
)

CONTROL_TICK_SCHEMA = "open_duck_x5.control_tick.v1"
RUNTIME_EVENT_SCHEMA = "open_duck_x5.runtime_event.v1"
SUMMARY_SCHEMA = "open_duck_x5.control_summary.v1"
STATUS_NAMES = tuple(ERROR_NAMES[int(code)] for code in ErrorCode)
TORQUE_OFF_STATUSES = frozenset((*STATUS_NAMES, "exception", "not_attempted"))


class ControlSummaryError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stats(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {key: None for key in ("min", "mean", "p95", "p99", "p99_9", "max")}
    array = np.asarray(values, dtype=np.float64)
    return {
        "min": float(np.min(array)),
        "mean": float(np.mean(array)),
        "p95": float(np.percentile(array, 95)),
        "p99": float(np.percentile(array, 99)),
        "p99_9": float(np.percentile(array, 99.9)),
        "max": float(np.max(array)),
    }


def _bursts(failed: Sequence[bool]) -> tuple[int, int]:
    count = 0
    longest = 0
    current = 0
    for value in failed:
        if value:
            current += 1
            longest = max(longest, current)
        else:
            if current >= 2:
                count += 1
            current = 0
    if current >= 2:
        count += 1
    return count, longest


def _require_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ControlSummaryError(f"{label} must be an object")
    return value


def _require_array(
    value: object, label: str, length: int, *, booleans: bool = False
) -> list[object]:
    if not isinstance(value, list) or len(value) != length:
        raise ControlSummaryError(f"{label} must contain exactly {length} values")
    if booleans:
        if any(type(item) is not bool for item in value):
            raise ControlSummaryError(f"{label} must contain only booleans")
    else:
        for item in value:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise ControlSummaryError(f"{label} must contain only numbers")
            if not math.isfinite(float(item)):
                raise ControlSummaryError(f"{label} contains a non-finite number")
    return value


def _require_number(value: object, label: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ControlSummaryError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise ControlSummaryError(f"{label} must be finite and >= {minimum}")
    return result


def _validate_startup_readiness(
    record: dict[str, object], *, policy_contract: str | None
) -> dict[str, object]:
    details = _require_mapping(record.get("details"), "startup_readiness.details")
    status = details.get("status")
    if status not in ("PASS", "FAIL"):
        raise ControlSummaryError("startup_readiness status must be PASS or FAIL")
    failures = details.get("failures")
    if not isinstance(failures, list) or any(
        not isinstance(value, str) or not value for value in failures
    ):
        raise ControlSummaryError("startup_readiness failures must be a string array")

    boolean_fields = (
        "paused",
        "policy_staged",
        "all_fresh",
        "imu_stale",
        "contacts_stale",
    )
    if any(type(details.get(name)) is not bool for name in boolean_fields):
        raise ControlSummaryError("startup_readiness boolean fields are invalid")

    committed_ticks = details.get("policy_committed_ticks")
    if committed_ticks is not None and (
        isinstance(committed_ticks, bool)
        or not isinstance(committed_ticks, int)
        or committed_ticks < 0
    ):
        raise ControlSummaryError("startup_readiness policy committed count is invalid")
    if policy_contract == T247_POLICY_CONTRACT and committed_ticks != 0:
        raise ControlSummaryError("T247 startup_readiness did not precede all policy ticks")

    phase = _require_number(details.get("phase"), "startup_readiness phase")
    tick_start = details.get("tick_start_monotonic_ns")
    next_release = details.get("next_release_monotonic_ns")
    if (
        not isinstance(tick_start, int)
        or isinstance(tick_start, bool)
        or tick_start < 0
        or not isinstance(next_release, int)
        or isinstance(next_release, bool)
        or next_release <= tick_start
    ):
        raise ControlSummaryError("startup_readiness ticker timestamps are invalid")
    tick_work_ms = _require_number(
        details.get("tick_work_ms"), "startup_readiness tick work"
    )
    _require_number(
        details.get("release_lateness_ms"), "startup_readiness release lateness"
    )
    bus_total_ms = _require_number(
        details.get("bus_total_ms"), "startup_readiness bus total"
    )
    group_ms = _require_number(
        details.get("group_round_trip_ms"), "startup_readiness group RTT"
    )
    extended_ms = _require_number(
        details.get("extended_round_trip_ms"), "startup_readiness extended RTT"
    )
    if bus_total_ms + 1e-9 < group_ms + extended_ms:
        raise ControlSummaryError("startup_readiness bus total is internally inconsistent")

    status_names = set(STATUS_NAMES)
    write_status = details.get("write_status")
    extended_status = details.get("extended_status")
    statuses = details.get("per_servo_status")
    if write_status not in status_names or extended_status not in status_names:
        raise ControlSummaryError("startup_readiness transaction status is invalid")
    if (
        not isinstance(statuses, list)
        or len(statuses) != ACTION_DIM
        or any(value not in status_names for value in statuses)
    ):
        raise ControlSummaryError(
            "startup_readiness per-servo status must contain 14 valid values"
        )
    device_statuses = details.get("per_servo_device_status")
    if (
        not isinstance(device_statuses, list)
        or len(device_statuses) != ACTION_DIM
        or any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= 255
            for value in device_statuses
        )
    ):
        raise ControlSummaryError(
            "startup_readiness per-servo device status must contain 14 bytes"
        )
    extended_device_status = details.get("extended_device_status")
    if (
        isinstance(extended_device_status, bool)
        or not isinstance(extended_device_status, int)
        or not 0 <= extended_device_status <= 255
    ):
        raise ControlSummaryError("startup_readiness extended device status is invalid")
    partial_bytes = details.get("partial_bytes")
    unexpected_packets = details.get("unexpected_packets")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in (partial_bytes, unexpected_packets)
    ):
        raise ControlSummaryError("startup_readiness structural counters are invalid")

    clean_pass = (
        not failures
        and details["paused"] is True
        and details["policy_staged"] is False
        and committed_ticks in (None, 0)
        and math.isclose(phase, 0.0, rel_tol=0.0, abs_tol=1e-12)
        and details["all_fresh"] is True
        and details["imu_stale"] is False
        and details["contacts_stale"] is False
        and tick_work_ms <= 40.0
        and bus_total_ms < 5.0
        and write_status == "ok"
        and all(value == "ok" for value in statuses)
        and extended_status == "ok"
        and all(value == 0 for value in device_statuses)
        and extended_device_status == 0
        and partial_bytes == 0
        and unexpected_packets == 0
    )
    if status == "PASS" and not clean_pass:
        raise ControlSummaryError("startup_readiness PASS record is not clean")
    if status == "FAIL" and not failures:
        raise ControlSummaryError("startup_readiness FAIL record has no failure reason")
    return details


def _validate_start(details: dict[str, object]) -> str | None:
    contract_id = details.get("contract_id")
    if contract_id not in {CONTRACT_ID, T247_RUNTIME_CONTRACT_ID}:
        raise ControlSummaryError("runtime_start contract_id does not match a reviewed contract")
    if details.get("control_frequency_hz") != 50.0:
        raise ControlSummaryError("runtime_start control frequency is not 50 Hz")
    if details.get("control_period_ns") != 20_000_000:
        raise ControlSummaryError("runtime_start control period is not 20 ms")
    if details.get("joint_names") != list(JOINT_NAMES):
        raise ControlSummaryError("runtime_start joint order does not match the frozen contract")
    if details.get("servo_ids") != list(SERVO_IDS):
        raise ControlSummaryError("runtime_start servo IDs do not match the frozen contract")
    config = _require_mapping(details.get("config"), "runtime_start.config")
    config_sha = config.get("sha256")
    if not isinstance(config_sha, str) or len(config_sha) != 64 or any(
        character not in "0123456789abcdef" for character in config_sha
    ):
        raise ControlSummaryError("runtime_start config SHA-256 is missing")
    bus = _require_mapping(details.get("bus"), "runtime_start.bus")
    if bus.get("backend") not in ("mock", "serial"):
        raise ControlSummaryError("runtime_start bus backend is invalid")
    policy = details.get("policy")
    if policy is None:
        if contract_id != CONTRACT_ID:
            raise ControlSummaryError("T247 runtime_start has no policy provenance")
        return None
    policy_map = _require_mapping(policy, "runtime_start.policy")
    policy_sha = policy_map.get("sha256")
    if not isinstance(policy_sha, str) or len(policy_sha) != 64 or any(
        character not in "0123456789abcdef" for character in policy_sha
    ):
        raise ControlSummaryError("runtime_start policy SHA-256 is missing")
    policy_contract = policy_map.get("contract")
    if policy_contract == T247_POLICY_CONTRACT:
        if contract_id != T247_RUNTIME_CONTRACT_ID:
            raise ControlSummaryError("T247 policy uses the wrong runtime contract ID")
        if policy_sha != T247_POLICY_SHA256:
            raise ControlSummaryError("runtime_start T247 policy SHA-256 differs")
        if policy_map.get("calibration_ticks") != T247_CALIBRATION_TICKS:
            raise ControlSummaryError("runtime_start T247 calibration duration differs")
        if policy_map.get("calibrator_inputs") != {
            "obs": [1, T247_OBSERVATION_DIM],
            "previous_action": [1, ACTION_DIM],
            "h_in": [1, 64],
        }:
            raise ControlSummaryError("runtime_start T247 calibrator ABI differs")
        if policy_map.get("locomotion_inputs") != {
            "obs": [1, T247_OBSERVATION_DIM],
            "previous_action": [1, ACTION_DIM],
            "h_in": [1, 64],
            "calibration_context": [1, 64],
        }:
            raise ControlSummaryError("runtime_start T247 locomotion input ABI differs")
        if policy_map.get("outputs") != {
            "action": [1, ACTION_DIM],
            "previous_action_out": [1, ACTION_DIM],
            "h_out": [1, 64],
        }:
            raise ControlSummaryError("runtime_start T247 output ABI differs")
        if (
            policy_map.get("context_routes") != 6
            or policy_map.get("exact_command_routes") != 24
            or policy_map.get("fallback_preserved") is not True
        ):
            raise ControlSummaryError("runtime_start T247 route catalog differs")
        assets = _require_mapping(policy_map.get("assets"), "runtime_start.policy.assets")
        expected_assets = {
            "calibrator": T247_CALIBRATOR_SHA256,
            "command_route_manifest": T247_COMMAND_MANIFEST_SHA256,
            "p30_fit": T247_P30_SHA256,
            "reference_table": T247_REFERENCE_SHA256,
        }
        for name, expected_sha256 in expected_assets.items():
            asset = _require_mapping(assets.get(name), f"runtime_start.policy.assets.{name}")
            if asset.get("sha256") != expected_sha256:
                raise ControlSummaryError(f"runtime_start T247 {name} SHA-256 differs")
        context_root = _require_mapping(
            assets.get("context_route_root"),
            "runtime_start.policy.assets.context_route_root",
        )
        command_root = _require_mapping(
            assets.get("command_route_root"),
            "runtime_start.policy.assets.command_route_root",
        )
        if (
            context_root.get("verified_models") != 6
            or context_root.get("router_sha256") != T247_CONTEXT_ROUTER_SHA256
            or command_root.get("verified_models") != 24
        ):
            raise ControlSummaryError("runtime_start T247 route-root provenance differs")
        return T247_POLICY_CONTRACT
    if contract_id != CONTRACT_ID:
        raise ControlSummaryError("legacy policy uses the wrong runtime contract ID")
    if policy_contract not in (None, "v1-101"):
        raise ControlSummaryError("runtime_start legacy policy selector differs")
    if policy_map.get("input") != {
        "name": "obs",
        "shape": [1, OBSERVATION_DIM],
        "type": "tensor(float)",
    }:
        raise ControlSummaryError("runtime_start policy input is not frozen obs [1,101]")
    if policy_map.get("output") != {
        "name": "continuous_actions",
        "shape": [1, ACTION_DIM],
        "type": "tensor(float)",
    }:
        raise ControlSummaryError(
            "runtime_start policy output is not frozen continuous_actions [1,14]"
        )
    if policy_map.get("session") != ONNX_SESSION_CONTRACT:
        raise ControlSummaryError(
            "runtime_start policy session is not the deterministic single-thread contract"
        )
    return "v1-101"


def _read_records(
    path: Path,
) -> tuple[
    dict[str, object],
    dict[str, object] | None,
    dict[str, object] | None,
    list[dict[str, object]],
    dict[str, object],
]:
    start: dict[str, object] | None = None
    realtime: dict[str, object] | None = None
    readiness: dict[str, object] | None = None
    halt: dict[str, object] | None = None
    ticks: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, 1):
            line = raw_line.strip()
            if not line:
                raise ControlSummaryError(f"blank JSONL record at line {line_number}")
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ControlSummaryError(
                    f"invalid JSON at line {line_number}: {exc.msg}"
                ) from exc
            record = _require_mapping(record, f"line {line_number}")
            if halt is not None:
                raise ControlSummaryError("runtime_halt must be the final JSONL record")
            schema = record.get("schema_version")
            if schema == CONTROL_TICK_SCHEMA:
                if start is None:
                    raise ControlSummaryError("control tick appeared before runtime_start")
                expected_tick = len(ticks)
                if record.get("tick") != expected_tick:
                    raise ControlSummaryError(
                        f"control tick discontinuity: expected {expected_tick}, "
                        f"got {record.get('tick')}"
                    )
                ticks.append(record)
                continue
            if schema != RUNTIME_EVENT_SCHEMA:
                raise ControlSummaryError(f"unknown schema at line {line_number}: {schema!r}")
            event = record.get("event")
            if event == "runtime_start":
                if start is not None or ticks or realtime is not None or readiness is not None:
                    raise ControlSummaryError("runtime_start is duplicated or out of order")
                start = record
            elif event == "realtime_verified":
                if start is None or realtime is not None or readiness is not None or ticks:
                    raise ControlSummaryError("realtime_verified is duplicated or out of order")
                realtime = record
            elif event == "startup_readiness":
                if start is None or readiness is not None or ticks:
                    raise ControlSummaryError(
                        "startup_readiness is duplicated or out of order"
                    )
                readiness = record
            elif event == "runtime_halt":
                if start is None:
                    raise ControlSummaryError("runtime_halt appeared before runtime_start")
                halt = record
            else:
                raise ControlSummaryError(f"unknown runtime event at line {line_number}: {event!r}")
    if start is None:
        raise ControlSummaryError("runtime_start event is missing")
    if halt is None:
        raise ControlSummaryError("runtime_halt event is missing")
    return start, realtime, readiness, ticks, halt


def summarize_control_run(path: Path) -> dict[str, object]:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise ControlSummaryError(f"control JSONL not found: {source}")
    start, realtime, readiness, ticks, halt = _read_records(source)
    details = _require_mapping(start.get("details"), "runtime_start.details")
    policy_contract = _validate_start(details)
    bus_details = _require_mapping(details["bus"], "runtime_start.bus")
    backend = str(bus_details["backend"])
    config_details = _require_mapping(details["config"], "runtime_start.config")
    max_ticks = int(details.get("max_ticks", 0))
    max_active_ticks = int(details.get("max_active_ticks", 0))
    fixed_command_x = details.get("fixed_command_x")
    policy_present = policy_contract is not None
    readiness_details = (
        _validate_startup_readiness(readiness, policy_contract=policy_contract)
        if readiness is not None
        else None
    )
    realtime_required = details.get("realtime_required") is True
    if realtime_required != (realtime is not None):
        raise ControlSummaryError(
            "realtime verification presence does not match runtime_start.realtime_required"
        )
    realtime_details: dict[str, object] | None = None
    if realtime is not None:
        realtime_details = _require_mapping(realtime.get("details"), "realtime.details")
        cpu = realtime_details.get("cpu")
        affinity = realtime_details.get("affinity")
        initial_affinity = realtime_details.get("initial_affinity")
        housekeeping = realtime_details.get("housekeeping_affinity")
        background = realtime_details.get("background_threads")
        if (
            not isinstance(cpu, int)
            or realtime_details.get("scheduler") != "SCHED_FIFO"
            or realtime_details.get("isolated") is not True
            or affinity != [cpu]
            or not isinstance(initial_affinity, list)
            or cpu not in initial_affinity
            or not isinstance(housekeeping, list)
            or not housekeeping
            or cpu in housekeeping
            or not isinstance(background, list)
        ):
            raise ControlSummaryError("realtime verification details are inconsistent")
        for thread in background:
            thread_map = _require_mapping(thread, "realtime background thread")
            thread_affinity = thread_map.get("affinity")
            if not isinstance(thread_affinity, list) or cpu in thread_affinity:
                raise ControlSummaryError(
                    "realtime background thread can execute on the control CPU"
                )
    if backend == "serial":
        if details.get("policy") is None:
            raise ControlSummaryError("serial Gate 5 evidence has no policy provenance")
        if not all(
            details.get(key) is True
            for key in ("gate5_authorized", "hardware_authorized", "suspended_or_benched")
        ):
            raise ControlSummaryError("serial Gate 5 authorization provenance is incomplete")
        if config_details.get("start_paused") is not True:
            raise ControlSummaryError("serial Gate 5 evidence did not start paused")
        if fixed_command_x not in (0.0, 0.08):
            raise ControlSummaryError("serial Gate 5 fixed command is not 0 or 0.08")
        if (
            max_ticks < 1
            or max_active_ticks < 1
            or max_ticks <= max_active_ticks
            or not realtime_required
        ):
            raise ControlSummaryError("serial Gate 5 duration/RT provenance is incomplete")
        if policy_contract == T247_POLICY_CONTRACT and max_active_ticks != 850:
            raise ControlSummaryError(
                "serial T247 Gate 5 requires 250 calibration and 600 locomotion ticks"
            )

    tick_period_ms: list[float] = []
    tick_work_ms: list[float] = []
    bus_total_ms: list[float] = []
    group_round_trip_ms: list[float] = []
    extended_round_trip_ms: list[float] = []
    imu_age_ms: list[float] = []
    contacts_age_ms: list[float] = []
    group_failed_ticks: list[bool] = []
    status_counts = {name: 0 for name in STATUS_NAMES}
    unexpected_packets = 0
    partial_bytes = 0
    stale_servo_samples = 0
    device_alarm_replies = 0
    voltage_alarm_replies = 0
    paused_ticks = 0
    active_policy_ticks = 0
    t247_policy_stages: list[str] = []
    t247_context_routes: set[str] = set()
    t247_command_routes: set[str] = set()
    command_x_values: list[float] = []
    max_abs_non_x_command = 0.0
    envelope_events = np.zeros(ACTION_DIM, dtype=np.int64)
    max_abs_target_velocity = np.zeros(ACTION_DIM, dtype=np.float64)
    extended_coverage = {str(servo_id): 0 for servo_id in SERVO_IDS}
    previous_timestamp: int | None = None

    start_timestamp = start.get("timestamp_monotonic_ns")
    halt_timestamp = halt.get("timestamp_monotonic_ns")
    if (
        not isinstance(start_timestamp, int)
        or not isinstance(halt_timestamp, int)
        or start_timestamp < 0
        or halt_timestamp < start_timestamp
    ):
        raise ControlSummaryError("runtime event timestamps are invalid")
    if realtime is not None:
        realtime_timestamp = realtime.get("timestamp_monotonic_ns")
        if (
            not isinstance(realtime_timestamp, int)
            or realtime_timestamp < start_timestamp
            or realtime_timestamp > halt_timestamp
        ):
            raise ControlSummaryError("realtime event timestamp is out of order")
    if readiness is not None:
        readiness_timestamp = readiness.get("timestamp_monotonic_ns")
        readiness_tick_start = int(readiness_details["tick_start_monotonic_ns"])
        lower_timestamp = (
            int(realtime["timestamp_monotonic_ns"])
            if realtime is not None
            else start_timestamp
        )
        if (
            not isinstance(readiness_timestamp, int)
            or isinstance(readiness_timestamp, bool)
            or readiness_timestamp < lower_timestamp
            or readiness_timestamp < readiness_tick_start
            or readiness_timestamp > halt_timestamp
        ):
            raise ControlSummaryError("startup_readiness event timestamp is out of order")

    for index, tick in enumerate(ticks):
        timestamp = tick.get("timestamp_monotonic_ns")
        if not isinstance(timestamp, int) or timestamp < 0:
            raise ControlSummaryError(f"tick {index} timestamp is invalid")
        if timestamp < start_timestamp or timestamp > halt_timestamp:
            raise ControlSummaryError(f"tick {index} timestamp is outside runtime events")
        period_value = tick.get("tick_period_ms")
        if index == 0:
            if readiness_details is None:
                if period_value is not None:
                    raise ControlSummaryError("first control tick period must be null")
            else:
                period = _require_number(period_value, "tick 0 period")
                if int(readiness["timestamp_monotonic_ns"]) > timestamp:
                    raise ControlSummaryError(
                        "first control tick timestamp precedes startup readiness event"
                    )
                expected_period = (
                    timestamp
                    - int(readiness_details["tick_start_monotonic_ns"])
                ) / 1e6
                if not math.isclose(period, expected_period, rel_tol=0.0, abs_tol=1e-9):
                    raise ControlSummaryError(
                        "first control tick period does not match startup readiness"
                    )
                if expected_period <= 0:
                    raise ControlSummaryError(
                        "first control tick does not follow startup readiness"
                    )
                tick_period_ms.append(period)
        else:
            period = _require_number(period_value, f"tick {index} period")
            expected_period = (timestamp - int(previous_timestamp)) / 1e6
            if not math.isclose(period, expected_period, rel_tol=0.0, abs_tol=1e-9):
                raise ControlSummaryError(f"tick {index} period does not match timestamps")
            if expected_period <= 0:
                raise ControlSummaryError("control tick timestamps are not strictly increasing")
            tick_period_ms.append(period)
        previous_timestamp = timestamp
        tick_work_ms.append(_require_number(tick.get("tick_work_ms"), f"tick {index} work"))

        bus = _require_mapping(tick.get("bus"), f"tick {index}.bus")
        group_round_trip_ms.append(
            _require_number(bus.get("group_round_trip_ms"), f"tick {index} group RTT")
        )
        extended_round_trip_ms.append(
            _require_number(bus.get("extended_round_trip_ms"), f"tick {index} extended RTT")
        )
        bus_total_ms.append(
            _require_number(bus.get("bus_total_ms"), f"tick {index} bus total")
        )
        statuses = bus.get("per_servo_status")
        if not isinstance(statuses, list) or len(statuses) != ACTION_DIM:
            raise ControlSummaryError(f"tick {index} per-servo status count is not 14")
        device_statuses = bus.get("per_servo_device_status")
        if (
            not isinstance(device_statuses, list)
            or len(device_statuses) != ACTION_DIM
            or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= 255
                for value in device_statuses
            )
        ):
            raise ControlSummaryError(
                f"tick {index} per-servo device status must contain 14 bytes"
            )
        device_alarm_replies += sum(int(value != 0) for value in device_statuses)
        voltage_alarm_replies += sum(int(bool(value & 0x01)) for value in device_statuses)
        stale = _require_array(bus.get("stale"), f"tick {index}.stale", ACTION_DIM, booleans=True)
        group_failed = False
        for joint_index, status in enumerate(statuses):
            if status not in status_counts:
                raise ControlSummaryError(f"tick {index} has unknown servo status {status!r}")
            status_counts[str(status)] += 1
            failed = status != "ok"
            if bool(stale[joint_index]) != failed:
                raise ControlSummaryError(
                    f"tick {index} stale/status mismatch at joint {joint_index}"
                )
            group_failed = group_failed or failed
            stale_servo_samples += int(bool(stale[joint_index]))
        write_status = bus.get("write_status")
        if write_status not in status_counts:
            raise ControlSummaryError(f"tick {index} has unknown write status")
        status_counts[str(write_status)] += 1
        extended = _require_mapping(tick.get("extended"), f"tick {index}.extended")
        extended_status = extended.get("status")
        if extended_status not in status_counts:
            raise ControlSummaryError(f"tick {index} has unknown extended status")
        status_counts[str(extended_status)] += 1
        extended_device_status = extended.get("device_status_raw")
        if (
            isinstance(extended_device_status, bool)
            or not isinstance(extended_device_status, int)
            or not 0 <= extended_device_status <= 255
        ):
            raise ControlSummaryError(
                f"tick {index} extended device status is not a byte"
            )
        device_alarm_replies += int(extended_device_status != 0)
        voltage_alarm_replies += int(bool(extended_device_status & 0x01))
        expected_extended_id = SERVO_IDS[index % ACTION_DIM]
        if extended.get("servo_id") != expected_extended_id:
            raise ControlSummaryError(
                f"tick {index} extended servo ID is not round-robin ID {expected_extended_id}"
            )
        extended_coverage[str(expected_extended_id)] += 1
        group_failed_ticks.append(group_failed)
        partial_value = bus.get("partial_bytes")
        unexpected_value = bus.get("unexpected_packets")
        if (
            not isinstance(partial_value, int)
            or partial_value < 0
            or not isinstance(unexpected_value, int)
            or unexpected_value < 0
        ):
            raise ControlSummaryError(f"tick {index} partial/unexpected counts are invalid")
        partial_bytes += partial_value
        unexpected_packets += unexpected_value

        sensor_age = _require_mapping(tick.get("sensor_age_ms"), f"tick {index}.sensor_age_ms")
        imu_age_ms.append(_require_number(sensor_age.get("imu"), f"tick {index} IMU age"))
        contacts_age_ms.append(
            _require_number(sensor_age.get("contacts"), f"tick {index} contact age")
        )

        paused = tick.get("paused")
        observation_valid = tick.get("observation_valid")
        if type(paused) is not bool or type(observation_valid) is not bool:
            raise ControlSummaryError(f"tick {index} pause/observation flags are invalid")
        paused_ticks += int(paused)
        if observation_valid:
            if paused:
                raise ControlSummaryError(f"tick {index} has a valid observation while paused")
            observation_length = (
                T247_OBSERVATION_DIM
                if policy_contract == T247_POLICY_CONTRACT
                else OBSERVATION_DIM
            )
            observation = _require_array(
                tick.get("observation"), f"tick {index}.observation", observation_length
            )
            _require_array(tick.get("action"), f"tick {index}.action", ACTION_DIM)
            max_abs_non_x_command = max(
                max_abs_non_x_command,
                max(abs(float(value)) for value in observation[7:13]),
            )
            if policy_contract == T247_POLICY_CONTRACT:
                policy_host = _require_mapping(
                    tick.get("policy_host"), f"tick {index}.policy_host"
                )
                stage = policy_host.get("stage")
                if stage not in {"calibration", "locomotion"}:
                    raise ControlSummaryError(f"tick {index} T247 stage is invalid")
                t247_policy_stages.append(str(stage))
                context_route = policy_host.get("selected_context_route")
                command_route = policy_host.get("selected_command_route")
                if stage == "calibration":
                    if any(float(value) != 0.0 for value in observation[6:13]):
                        raise ControlSummaryError(
                            f"tick {index} T247 calibration command is not zero"
                        )
                    if context_route is not None:
                        if context_route not in T247_ROUTE_NAMES:
                            raise ControlSummaryError(
                                f"tick {index} T247 calibration context route is invalid"
                            )
                        t247_context_routes.add(str(context_route))
                    if command_route not in {None, "fallback"}:
                        raise ControlSummaryError(
                            f"tick {index} T247 calibration command route is invalid"
                        )
                else:
                    if context_route not in T247_ROUTE_NAMES:
                        raise ControlSummaryError(
                            f"tick {index} T247 locomotion context route is invalid"
                        )
                    expected_route = "x000" if fixed_command_x == 0.0 else "x080"
                    if command_route != expected_route:
                        raise ControlSummaryError(
                            f"tick {index} T247 locomotion command route differs"
                        )
                    t247_context_routes.add(str(context_route))
                    t247_command_routes.add(str(command_route))
                    command_x_values.append(float(observation[6]))
            else:
                if "policy_host" in tick:
                    raise ControlSummaryError(
                        f"tick {index} legacy policy record has T247 host metadata"
                    )
                command_x_values.append(float(observation[6]))
            active_policy_ticks += 1
        elif tick.get("observation") is not None or tick.get("action") is not None:
            raise ControlSummaryError(f"tick {index} invalid observation/action must be null")
        elif "policy_host" in tick:
            raise ControlSummaryError(f"tick {index} inactive record has policy host metadata")
        if policy_present and observation_valid != (not paused):
            raise ControlSummaryError(
                f"tick {index} policy pause/observation state is inconsistent"
            )

        _require_array(
            tick.get("actual_position_rad"), f"tick {index}.actual_position_rad", ACTION_DIM
        )
        _require_array(
            tick.get("sent_target_rad"), f"tick {index}.sent_target_rad", ACTION_DIM
        )
        velocities = _require_array(
            tick.get("implied_target_velocity_rad_s"),
            f"tick {index}.implied_target_velocity_rad_s",
            ACTION_DIM,
        )
        over = _require_array(
            tick.get("over_3_75_rad_s"),
            f"tick {index}.over_3_75_rad_s",
            ACTION_DIM,
            booleans=True,
        )
        for joint_index, velocity in enumerate(velocities):
            absolute_velocity = abs(float(velocity))
            expected_over = absolute_velocity > ENVELOPE_MONITOR_RAD_S
            if bool(over[joint_index]) != expected_over:
                raise ControlSummaryError(
                    f"tick {index} envelope flag mismatch at joint {joint_index}"
                )
            envelope_events[joint_index] += int(expected_over and observation_valid)
            max_abs_target_velocity[joint_index] = max(
                max_abs_target_velocity[joint_index], absolute_velocity
            )

    burst_count, max_burst = _bursts(group_failed_ticks)
    expected_transactions = len(ticks) * (ACTION_DIM + 2)
    ok_count = status_counts["ok"]
    transaction_failures = expected_transactions - ok_count + unexpected_packets
    failure_rate = (
        transaction_failures / expected_transactions if expected_transactions else 0.0
    )
    dropped = halt.get("telemetry_records_dropped")
    if not isinstance(dropped, int) or dropped < 0:
        raise ControlSummaryError("runtime_halt telemetry drop count is invalid")
    halt_reason = halt.get("reason")
    if not isinstance(halt_reason, str) or not halt_reason:
        raise ControlSummaryError("runtime_halt reason is missing")
    torque_off_attempted = halt.get("torque_off_attempted")
    if type(torque_off_attempted) is not bool:
        raise ControlSummaryError("runtime_halt torque-off attempted flag is invalid")
    torque_off_status = halt.get("torque_off_status")
    if torque_off_status not in TORQUE_OFF_STATUSES:
        raise ControlSummaryError("runtime_halt torque-off status is invalid")
    torque_off_error = halt.get("torque_off_error")
    if torque_off_error is not None and (
        not isinstance(torque_off_error, str) or not torque_off_error
    ):
        raise ControlSummaryError("runtime_halt torque-off error is invalid")
    if torque_off_attempted != (torque_off_status != "not_attempted"):
        raise ControlSummaryError("runtime_halt torque-off attempt/status disagree")
    if torque_off_status == "ok" and torque_off_error is not None:
        raise ControlSummaryError("successful torque-off cannot carry an error")
    if torque_off_status not in ("ok", "not_attempted") and torque_off_error is None:
        raise ControlSummaryError("failed torque-off must carry an error")
    torque_off_confirmed = torque_off_attempted and torque_off_status == "ok"
    complete_tick_count = max_ticks > 0 and len(ticks) <= max_ticks
    active_tick_target_met = (
        active_policy_ticks == max_active_ticks
        if max_active_ticks > 0
        else len(ticks) == max_ticks
    )
    normal_exit = halt_reason == "normal_exit"
    complete_record_stream = (
        dropped == 0 and complete_tick_count and active_tick_target_met
    )
    command_matches = (
        fixed_command_x is not None
        and bool(command_x_values)
        and all(
            math.isclose(value, float(fixed_command_x), rel_tol=0.0, abs_tol=1e-6)
            for value in command_x_values
        )
    )
    t247_stage_sequence_exact = True
    t247_route_sequence_exact = True
    if policy_contract == T247_POLICY_CONTRACT:
        locomotion_ticks = active_policy_ticks - T247_CALIBRATION_TICKS
        t247_stage_sequence_exact = (
            locomotion_ticks > 0
            and t247_policy_stages
            == ["calibration"] * T247_CALIBRATION_TICKS
            + ["locomotion"] * locomotion_ticks
        )
        expected_command_route = "x000" if fixed_command_x == 0.0 else "x080"
        t247_route_sequence_exact = (
            len(t247_context_routes) == 1
            and t247_command_routes == {expected_command_route}
        )
    tick_stats = _stats(tick_period_ms)
    bus_stats = _stats(bus_total_ms)
    gates = {
        "complete_record_stream": complete_record_stream,
        "normal_exit": normal_exit,
        "torque_off_confirmed": torque_off_confirmed,
        "realtime_verified_when_required": not realtime_required or realtime is not None,
        "startup_readiness_passed": backend != "serial"
        or (
            readiness_details is not None
            and readiness_details.get("status") == "PASS"
        ),
        "policy_ticks_present": active_policy_ticks > 0,
        "fixed_command_matches": command_matches,
        "zero_non_x_commands": max_abs_non_x_command <= 1e-7,
        "t247_stage_sequence_exact": t247_stage_sequence_exact,
        "t247_route_sequence_exact": t247_route_sequence_exact,
        "tick_p99_at_most_21_ms": tick_stats["p99"] is not None
        and tick_stats["p99"] <= 21.0,
        "tick_p99_9_at_most_22_ms": tick_stats["p99_9"] is not None
        and tick_stats["p99_9"] <= 22.0,
        "zero_read_bursts": burst_count == 0,
        "zero_partial_bytes": partial_bytes == 0,
        "zero_unexpected_packets": unexpected_packets == 0,
        "transaction_failure_below_0_1_percent": failure_rate < 0.001,
        "zero_device_alarms": device_alarm_replies == 0,
        "bus_max_under_5_ms": bus_stats["max"] is not None and bus_stats["max"] < 5.0,
        "zero_stale_servo_samples": stale_servo_samples == 0,
    }
    gates["gate5_timing_and_bus_candidate"] = all(gates.values())
    return {
        "schema_version": SUMMARY_SCHEMA,
        "source": {"path": str(source), "sha256": _sha256(source)},
        "backend": backend,
        "informational_only": backend == "mock",
        "review_status": "INFORMATIONAL_ONLY" if backend == "mock" else "REVIEW_REQUIRED",
        "hardware_gate_status": (
            "NOT_APPLICABLE_MOCK" if backend == "mock" else "REVIEW_REQUIRED"
        ),
        "run_status": (
            "COMPLETE"
            if normal_exit and complete_record_stream and torque_off_confirmed
            else "HALTED"
        ),
        "halt_reason": halt_reason,
        "ticks": len(ticks),
        "ticks_requested": max_ticks,
        "paused_ticks": paused_ticks,
        "active_policy_ticks": active_policy_ticks,
        "active_ticks_requested": max_active_ticks,
        "telemetry_records_dropped": dropped,
        "provenance": details,
        "realtime": realtime_details,
        "startup_readiness": readiness_details,
        "safety": {
            "torque_off_attempted": torque_off_attempted,
            "torque_off_status": torque_off_status,
            "torque_off_error": torque_off_error,
            "torque_off_confirmed": torque_off_confirmed,
        },
        "timing": {
            "tick_period_ms": tick_stats,
            "tick_work_ms": _stats(tick_work_ms),
        },
        "bus": {
            "bus_total_ms": bus_stats,
            "group_round_trip_ms": _stats(group_round_trip_ms),
            "extended_round_trip_ms": _stats(extended_round_trip_ms),
            "transactions_expected": expected_transactions,
            "transactions_failed": transaction_failures,
            "transaction_failure_rate": failure_rate,
            "transaction_status_counts": status_counts,
            "device_alarm_reply_count": device_alarm_replies,
            "voltage_alarm_reply_count": voltage_alarm_replies,
            "unexpected_packet_count": unexpected_packets,
            "partial_byte_count": partial_bytes,
            "read_burst_count": burst_count,
            "max_read_burst_ticks": max_burst,
            "stale_servo_sample_count": stale_servo_samples,
        },
        "sensors": {
            "imu_age_ms": _stats(imu_age_ms),
            "contacts_age_ms": _stats(contacts_age_ms),
        },
        "command": {
            "fixed_x": fixed_command_x,
            "observed_x": _stats(command_x_values),
            "matches_fixed_x": command_matches,
            "max_abs_non_x": max_abs_non_x_command,
        },
        "envelope": {
            "threshold_rad_s": ENVELOPE_MONITOR_RAD_S,
            "events_by_joint": {
                name: int(envelope_events[index])
                for index, name in enumerate(JOINT_NAMES)
            },
            "max_abs_target_velocity_rad_s_by_joint": {
                name: float(max_abs_target_velocity[index])
                for index, name in enumerate(JOINT_NAMES)
            },
            "total_events": int(envelope_events.sum()),
        },
        "extended_telemetry_coverage": extended_coverage,
        "gates": gates,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize and structurally verify runtime control JSONL"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.input.expanduser().resolve() == args.output.expanduser().resolve():
        parser.error("--input and --output must be different files")
    try:
        summary = summarize_control_run(args.input)
    except (ControlSummaryError, OSError) as exc:
        parser.error(str(exc))
    output_path = args.output.expanduser().resolve()
    provenance = _require_mapping(summary["provenance"], "summary.provenance")
    config = _require_mapping(provenance["config"], "summary.provenance.config")
    protected_paths = {Path(str(config["path"])).expanduser().resolve()}
    policy = provenance.get("policy")
    if policy is not None:
        policy_map = _require_mapping(policy, "summary.provenance.policy")
        protected_paths.add(Path(str(policy_map["path"])).expanduser().resolve())
    if output_path in protected_paths:
        parser.error("--output must not overwrite the recorded config or policy")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(
        (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
