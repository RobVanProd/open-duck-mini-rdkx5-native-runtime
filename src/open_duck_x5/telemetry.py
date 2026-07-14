from __future__ import annotations

import json
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .bus.types import ERROR_NAMES, ServoSnapshot
from .clock import clock_ns
from .constants import ACTION_DIM, OBSERVATION_DIM


class TelemetryError(RuntimeError):
    """The evidence stream is incomplete or could not be written."""


@dataclass(slots=True)
class ProbeRecord:
    tick: int = 0
    tick_start_ns: int = 0
    tick_period_ns: int = 0
    release_lateness_ns: int = 0
    group_round_trip_ns: int = 0
    extended_round_trip_ns: int = 0
    bus_total_ns: int = 0
    write_status: int = 0
    extended_status: int = 0
    extended_servo_id: int = -1
    current_raw: int = 0
    current_a: float = 0.0
    voltage_v: float = 0.0
    temperature_c: float = 0.0
    partial_bytes: int = 0
    unexpected_packets: int = 0
    status: np.ndarray = field(
        default_factory=lambda: np.zeros(ACTION_DIM, dtype=np.uint8)
    )
    stale: np.ndarray = field(
        default_factory=lambda: np.zeros(ACTION_DIM, dtype=np.bool_)
    )
    target_positions_rad: np.ndarray = field(
        default_factory=lambda: np.zeros(ACTION_DIM, dtype=np.float64)
    )
    actual_positions_rad: np.ndarray = field(
        default_factory=lambda: np.zeros(ACTION_DIM, dtype=np.float64)
    )
    absolute_error_rad: np.ndarray = field(
        default_factory=lambda: np.zeros(ACTION_DIM, dtype=np.float64)
    )

    def capture(
        self,
        tick: int,
        tick_start_ns: int,
        tick_period_ns: int,
        release_lateness_ns: int,
        snapshot: ServoSnapshot,
        target_positions_rad: np.ndarray,
    ) -> None:
        self.tick = tick
        self.tick_start_ns = tick_start_ns
        self.tick_period_ns = tick_period_ns
        self.release_lateness_ns = release_lateness_ns
        self.group_round_trip_ns = snapshot.group_round_trip_ns
        self.extended_round_trip_ns = snapshot.extended_round_trip_ns
        self.bus_total_ns = snapshot.bus_total_ns
        self.write_status = int(snapshot.write_status)
        self.extended_status = int(snapshot.extended_status)
        self.extended_servo_id = snapshot.extended_servo_id
        self.current_raw = snapshot.present_current_raw
        self.current_a = snapshot.present_current_a
        self.voltage_v = snapshot.present_voltage_v
        self.temperature_c = snapshot.present_temperature_c
        self.partial_bytes = snapshot.partial_bytes
        self.unexpected_packets = snapshot.unexpected_packets
        np.copyto(self.status, snapshot.status)
        np.copyto(self.stale, snapshot.stale)
        np.copyto(self.target_positions_rad, target_positions_rad)
        np.copyto(self.actual_positions_rad, snapshot.positions_rad)
        np.subtract(
            self.actual_positions_rad,
            self.target_positions_rad,
            out=self.absolute_error_rad,
        )
        np.absolute(self.absolute_error_rad, out=self.absolute_error_rad)

    def as_jsonable(self) -> dict[str, object]:
        return {
            "schema_version": "open_duck_x5.timing_tick.v2",
            "tick": self.tick,
            "timestamp_monotonic_ns": self.tick_start_ns,
            "tick_period_ms": self.tick_period_ns / 1e6 if self.tick_period_ns else None,
            "release_lateness_ms": self.release_lateness_ns / 1e6,
            "serial": {
                "group_round_trip_ms": self.group_round_trip_ns / 1e6,
                "extended_round_trip_ms": self.extended_round_trip_ns / 1e6,
                "bus_total_ms": self.bus_total_ns / 1e6,
                "write_status": ERROR_NAMES[self.write_status],
                "per_servo_status": [ERROR_NAMES[int(code)] for code in self.status],
                "stale": self.stale.tolist(),
                "partial_bytes": self.partial_bytes,
                "unexpected_packets": self.unexpected_packets,
            },
            "extended": {
                "servo_id": self.extended_servo_id,
                "status": ERROR_NAMES[self.extended_status],
                "present_current_raw": self.current_raw,
                "present_current_a": self.current_a,
                "present_voltage_v": self.voltage_v,
                "present_temperature_c": self.temperature_c,
            },
            "motion": {
                "target_positions_rad": self.target_positions_rad.tolist(),
                "actual_positions_rad": self.actual_positions_rad.tolist(),
                "absolute_error_rad": self.absolute_error_rad.tolist(),
            },
        }


class AsyncProbeWriter:
    """Bounded preallocated record pool; JSON serialization happens off-thread."""

    def __init__(self, path: str | Path, *, capacity: int = 1024) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._free: queue.SimpleQueue[ProbeRecord] = queue.SimpleQueue()
        self._pending: queue.Queue[ProbeRecord | None] = queue.Queue(maxsize=capacity)
        for _ in range(capacity):
            self._free.put(ProbeRecord())
        self.dropped = 0
        self._error: BaseException | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="probe-jsonl-writer", daemon=True)
        self._thread.start()
        self._ready.wait()
        self._raise_if_failed()

    def _raise_if_failed(self) -> None:
        if self._error is not None:
            raise TelemetryError(f"timing telemetry writer failed: {self._error}") from self._error

    def publish(
        self,
        tick: int,
        tick_start_ns: int,
        tick_period_ns: int,
        release_lateness_ns: int,
        snapshot: ServoSnapshot,
        target_positions_rad: np.ndarray,
    ) -> None:
        self._raise_if_failed()
        try:
            record = self._free.get_nowait()
        except queue.Empty as exc:
            self.dropped += 1
            raise TelemetryError("timing telemetry record pool exhausted") from exc
        record.capture(
            tick,
            tick_start_ns,
            tick_period_ns,
            release_lateness_ns,
            snapshot,
            target_positions_rad,
        )
        try:
            self._pending.put_nowait(record)
        except queue.Full as exc:
            self.dropped += 1
            self._free.put(record)
            raise TelemetryError("timing telemetry queue overflow") from exc

    def _run(self) -> None:
        try:
            with self.path.open("w", encoding="utf-8", buffering=1) as handle:
                self._ready.set()
                while True:
                    record = self._pending.get()
                    if record is None:
                        return
                    handle.write(
                        json.dumps(record.as_jsonable(), separators=(",", ":")) + "\n"
                    )
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


@dataclass(slots=True)
class ControlRecord:
    tick: int = 0
    tick_start_ns: int = 0
    tick_period_ns: int = 0
    tick_work_ns: int = 0
    paused: bool = True
    observation_valid: bool = False
    imu_age_ns: int = 0
    contacts_age_ns: int = 0
    group_round_trip_ns: int = 0
    extended_round_trip_ns: int = 0
    bus_total_ns: int = 0
    write_status: int = 0
    extended_status: int = 0
    extended_servo_id: int = -1
    current_a: float = 0.0
    voltage_v: float = 0.0
    temperature_c: float = 0.0
    partial_bytes: int = 0
    unexpected_packets: int = 0
    status: np.ndarray = field(
        default_factory=lambda: np.zeros(ACTION_DIM, dtype=np.uint8)
    )
    stale: np.ndarray = field(
        default_factory=lambda: np.zeros(ACTION_DIM, dtype=np.bool_)
    )
    observation: np.ndarray = field(
        default_factory=lambda: np.zeros(OBSERVATION_DIM, dtype=np.float32)
    )
    action: np.ndarray = field(default_factory=lambda: np.zeros(ACTION_DIM, dtype=np.float32))
    actual_position_rad: np.ndarray = field(
        default_factory=lambda: np.zeros(ACTION_DIM, dtype=np.float64)
    )
    sent_target_rad: np.ndarray = field(
        default_factory=lambda: np.zeros(ACTION_DIM, dtype=np.float64)
    )
    implied_velocity_rad_s: np.ndarray = field(
        default_factory=lambda: np.zeros(ACTION_DIM, dtype=np.float64)
    )
    over_envelope: np.ndarray = field(
        default_factory=lambda: np.zeros(ACTION_DIM, dtype=np.bool_)
    )

    def capture(
        self,
        tick: int,
        tick_start_ns: int,
        tick_period_ns: int,
        tick_work_ns: int,
        paused: bool,
        observation_valid: bool,
        imu_age_ns: int,
        contacts_age_ns: int,
        snapshot: ServoSnapshot,
        observation: np.ndarray,
        action: np.ndarray,
        actual_position_rad: np.ndarray,
        sent_target_rad: np.ndarray,
        implied_velocity_rad_s: np.ndarray,
        over_envelope: np.ndarray,
    ) -> None:
        self.tick = tick
        self.tick_start_ns = tick_start_ns
        self.tick_period_ns = tick_period_ns
        self.tick_work_ns = tick_work_ns
        self.paused = paused
        self.observation_valid = observation_valid
        self.imu_age_ns = imu_age_ns
        self.contacts_age_ns = contacts_age_ns
        self.group_round_trip_ns = snapshot.group_round_trip_ns
        self.extended_round_trip_ns = snapshot.extended_round_trip_ns
        self.bus_total_ns = snapshot.bus_total_ns
        self.write_status = int(snapshot.write_status)
        self.extended_status = int(snapshot.extended_status)
        self.extended_servo_id = snapshot.extended_servo_id
        self.current_a = snapshot.present_current_a
        self.voltage_v = snapshot.present_voltage_v
        self.temperature_c = snapshot.present_temperature_c
        self.partial_bytes = snapshot.partial_bytes
        self.unexpected_packets = snapshot.unexpected_packets
        np.copyto(self.status, snapshot.status)
        np.copyto(self.stale, snapshot.stale)
        np.copyto(self.observation, observation)
        np.copyto(self.action, action)
        np.copyto(self.actual_position_rad, actual_position_rad)
        np.copyto(self.sent_target_rad, sent_target_rad)
        np.copyto(self.implied_velocity_rad_s, implied_velocity_rad_s)
        np.copyto(self.over_envelope, over_envelope)

    def as_jsonable(self) -> dict[str, object]:
        return {
            "schema_version": "open_duck_x5.control_tick.v1",
            "tick": self.tick,
            "timestamp_monotonic_ns": self.tick_start_ns,
            "tick_period_ms": self.tick_period_ns / 1e6 if self.tick_period_ns else None,
            "tick_work_ms": self.tick_work_ns / 1e6,
            "paused": self.paused,
            "observation_valid": self.observation_valid,
            "sensor_age_ms": {
                "imu": self.imu_age_ns / 1e6,
                "contacts": self.contacts_age_ns / 1e6,
            },
            "bus": {
                "group_round_trip_ms": self.group_round_trip_ns / 1e6,
                "extended_round_trip_ms": self.extended_round_trip_ns / 1e6,
                "bus_total_ms": self.bus_total_ns / 1e6,
                "write_status": ERROR_NAMES[self.write_status],
                "per_servo_status": [ERROR_NAMES[int(code)] for code in self.status],
                "stale": self.stale.tolist(),
                "partial_bytes": self.partial_bytes,
                "unexpected_packets": self.unexpected_packets,
            },
            "extended": {
                "servo_id": self.extended_servo_id,
                "status": ERROR_NAMES[self.extended_status],
                "present_current_a": self.current_a,
                "present_voltage_v": self.voltage_v,
                "present_temperature_c": self.temperature_c,
            },
            "observation": self.observation.tolist() if self.observation_valid else None,
            "action": self.action.tolist() if self.observation_valid else None,
            "actual_position_rad": self.actual_position_rad.tolist(),
            "sent_target_rad": self.sent_target_rad.tolist(),
            "implied_target_velocity_rad_s": self.implied_velocity_rad_s.tolist(),
            "over_3_75_rad_s": self.over_envelope.tolist(),
        }


class AsyncControlWriter:
    def __init__(self, path: str | Path, *, capacity: int = 512) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._free: queue.SimpleQueue[ControlRecord] = queue.SimpleQueue()
        self._pending: queue.Queue[ControlRecord | dict[str, object] | None] = queue.Queue(
            maxsize=capacity
        )
        for _ in range(capacity):
            self._free.put(ControlRecord())
        self.dropped = 0
        self._error: BaseException | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="control-jsonl-writer", daemon=True)
        self._thread.start()
        self._ready.wait()
        self._raise_if_failed()

    def _raise_if_failed(self) -> None:
        if self._error is not None:
            raise TelemetryError(f"control telemetry writer failed: {self._error}") from self._error

    def publish(
        self,
        tick: int,
        tick_start_ns: int,
        tick_period_ns: int,
        tick_work_ns: int,
        paused: bool,
        observation_valid: bool,
        imu_age_ns: int,
        contacts_age_ns: int,
        snapshot: ServoSnapshot,
        observation: np.ndarray,
        action: np.ndarray,
        actual_position_rad: np.ndarray,
        sent_target_rad: np.ndarray,
        implied_velocity_rad_s: np.ndarray,
        over_envelope: np.ndarray,
    ) -> None:
        self._raise_if_failed()
        try:
            record = self._free.get_nowait()
        except queue.Empty as exc:
            self.dropped += 1
            raise TelemetryError("control telemetry record pool exhausted") from exc
        record.capture(
            tick,
            tick_start_ns,
            tick_period_ns,
            tick_work_ns,
            paused,
            observation_valid,
            imu_age_ns,
            contacts_age_ns,
            snapshot,
            observation,
            action,
            actual_position_rad,
            sent_target_rad,
            implied_velocity_rad_s,
            over_envelope,
        )
        try:
            self._pending.put_nowait(record)
        except queue.Full as exc:
            self.dropped += 1
            self._free.put(record)
            raise TelemetryError("control telemetry queue overflow") from exc

    def _run(self) -> None:
        try:
            with self.path.open("w", encoding="utf-8", buffering=1) as handle:
                self._ready.set()
                while True:
                    record = self._pending.get()
                    if record is None:
                        return
                    if isinstance(record, dict):
                        handle.write(json.dumps(record, separators=(",", ":")) + "\n")
                        continue
                    handle.write(
                        json.dumps(record.as_jsonable(), separators=(",", ":")) + "\n"
                    )
                    self._free.put(record)
        except BaseException as exc:
            self._error = exc
            self._ready.set()

    def publish_event(
        self, event: str, *, details: dict[str, object] | None = None
    ) -> None:
        self._raise_if_failed()
        payload: dict[str, object] = {
            "schema_version": "open_duck_x5.runtime_event.v1",
            "timestamp_monotonic_ns": clock_ns(),
            "event": event,
        }
        if details is not None:
            payload["details"] = details
        try:
            self._pending.put_nowait(payload)
        except queue.Full as exc:
            self.dropped += 1
            raise TelemetryError("control telemetry queue overflow") from exc

    def close(
        self,
        *,
        reason: str = "normal_exit",
        torque_off_attempted: bool = False,
        torque_off_status: str = "not_attempted",
        torque_off_error: str | None = None,
    ) -> None:
        halt_record = {
            "schema_version": "open_duck_x5.runtime_event.v1",
            "timestamp_monotonic_ns": clock_ns(),
            "event": "runtime_halt",
            "reason": reason,
            "telemetry_records_dropped": self.dropped,
            "torque_off_attempted": torque_off_attempted,
            "torque_off_status": torque_off_status,
            "torque_off_error": torque_off_error,
        }
        halt_queued = False
        while self._thread.is_alive() and not halt_queued:
            try:
                self._pending.put(halt_record, timeout=0.1)
                halt_queued = True
            except queue.Full:
                continue
        while self._thread.is_alive():
            try:
                self._pending.put(None, timeout=0.1)
                break
            except queue.Full:
                continue
        self._thread.join()
        self._raise_if_failed()
