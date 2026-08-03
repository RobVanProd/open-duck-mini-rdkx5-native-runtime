from __future__ import annotations

import math
from dataclasses import dataclass

from .safety import SafetyError
from .sensors import SensorReadout

GROUNDED_READINESS_SAMPLES = 50
HARD_TILT_CUTOFF_DEG = 32.851061754962494
SUSTAINED_TILT_CUTOFF_DEG = 16.425530877481247
CONSECUTIVE_FAULT_TICKS = 3
MIN_ACCELERATION_NORM_M_S2 = 1e-6


@dataclass(slots=True)
class GroundedStabilityGuard:
    """Default-off G3 tilt/contact guard with a per-run gravity baseline."""

    enforce_contacts: bool
    readiness_samples_required: int = GROUNDED_READINESS_SAMPLES
    readiness_samples: int = 0
    baseline_sum_x: float = 0.0
    baseline_sum_y: float = 0.0
    baseline_sum_z: float = 0.0
    baseline_x: float = 0.0
    baseline_y: float = 0.0
    baseline_z: float = 1.0
    ready: bool = False
    tilt_deg: float = 0.0
    sustained_tilt_ticks: int = 0
    both_contacts_false_ticks: int = 0
    invalid_acceleration_ticks: int = 0
    last_imu_timestamp_ns: int = 0
    last_contacts_timestamp_ns: int = 0
    trip_reason: str | None = None

    @property
    def mode(self) -> str:
        return "grounded-enforced" if self.enforce_contacts else "suspended-revalidation"

    @staticmethod
    def _fresh(sensors: SensorReadout) -> None:
        if sensors.imu_stale:
            raise SafetyError("grounded safety guard received stale IMU data")
        if sensors.contacts_stale:
            raise SafetyError("grounded safety guard received stale contact data")

    @staticmethod
    def _acceleration(sensors: SensorReadout) -> tuple[float, float, float, float]:
        x = float(sensors.acceleration_m_s2[0])
        y = float(sensors.acceleration_m_s2[1])
        z = float(sensors.acceleration_m_s2[2])
        norm = math.sqrt(x * x + y * y + z * z)
        return x, y, z, norm

    def add_readiness_sample(self, sensors: SensorReadout) -> None:
        if self.ready:
            raise SafetyError("grounded safety readiness was already completed")
        self._fresh(sensors)
        if sensors.imu_timestamp_ns <= self.last_imu_timestamp_ns:
            raise SafetyError("grounded readiness IMU sample was not newer")
        if sensors.contacts_timestamp_ns <= self.last_contacts_timestamp_ns:
            raise SafetyError("grounded readiness contact sample was not newer")
        if self.enforce_contacts and not bool(
            sensors.contacts[0] >= 0.5 and sensors.contacts[1] >= 0.5
        ):
            raise SafetyError("grounded readiness requires both feet in contact")
        x, y, z, norm = self._acceleration(sensors)
        if not math.isfinite(norm) or norm <= MIN_ACCELERATION_NORM_M_S2:
            raise SafetyError("grounded readiness acceleration is invalid")
        self.last_imu_timestamp_ns = int(sensors.imu_timestamp_ns)
        self.last_contacts_timestamp_ns = int(sensors.contacts_timestamp_ns)
        self.baseline_sum_x += x
        self.baseline_sum_y += y
        self.baseline_sum_z += z
        self.readiness_samples += 1
        if self.readiness_samples == self.readiness_samples_required:
            mean_x = self.baseline_sum_x / self.readiness_samples
            mean_y = self.baseline_sum_y / self.readiness_samples
            mean_z = self.baseline_sum_z / self.readiness_samples
            mean_norm = math.sqrt(mean_x * mean_x + mean_y * mean_y + mean_z * mean_z)
            if not math.isfinite(mean_norm) or mean_norm <= MIN_ACCELERATION_NORM_M_S2:
                raise SafetyError("grounded readiness mean acceleration is invalid")
            self.baseline_x = mean_x / mean_norm
            self.baseline_y = mean_y / mean_norm
            self.baseline_z = mean_z / mean_norm
            self.ready = True

    def observe(self, sensors: SensorReadout) -> None:
        if not self.ready:
            raise SafetyError("grounded safety guard used before readiness")
        self._fresh(sensors)
        x, y, z, norm = self._acceleration(sensors)
        if not math.isfinite(norm) or norm <= MIN_ACCELERATION_NORM_M_S2:
            self.invalid_acceleration_ticks += 1
            if self.invalid_acceleration_ticks >= CONSECUTIVE_FAULT_TICKS:
                self._trip("invalid acceleration persisted for 3 ticks")
            return
        self.invalid_acceleration_ticks = 0
        dot = (
            self.baseline_x * x + self.baseline_y * y + self.baseline_z * z
        ) / norm
        self.tilt_deg = math.degrees(math.acos(max(-1.0, min(1.0, dot))))
        if self.tilt_deg >= HARD_TILT_CUTOFF_DEG:
            self._trip(
                f"single-tick tilt {self.tilt_deg:.6f} deg reached "
                f"{HARD_TILT_CUTOFF_DEG:.6f} deg"
            )
        if self.tilt_deg >= SUSTAINED_TILT_CUTOFF_DEG:
            self.sustained_tilt_ticks += 1
            if self.sustained_tilt_ticks >= CONSECUTIVE_FAULT_TICKS:
                self._trip(
                    f"tilt {self.tilt_deg:.6f} deg persisted for 3 ticks above "
                    f"{SUSTAINED_TILT_CUTOFF_DEG:.6f} deg"
                )
        else:
            self.sustained_tilt_ticks = 0
        if self.enforce_contacts and bool(
            sensors.contacts[0] < 0.5 and sensors.contacts[1] < 0.5
        ):
            self.both_contacts_false_ticks += 1
            if self.both_contacts_false_ticks >= CONSECUTIVE_FAULT_TICKS:
                self._trip("both foot contacts were false for 3 ticks")
        else:
            self.both_contacts_false_ticks = 0

    def _trip(self, reason: str) -> None:
        self.trip_reason = reason
        raise SafetyError(f"grounded safety cutoff: {reason}")

    def telemetry(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "ready": self.ready,
            "readiness_samples": self.readiness_samples,
            "tilt_from_baseline_deg": self.tilt_deg,
            "sustained_tilt_ticks": self.sustained_tilt_ticks,
            "both_contacts_false_ticks": self.both_contacts_false_ticks,
            "invalid_acceleration_ticks": self.invalid_acceleration_ticks,
            "trip_reason": self.trip_reason,
        }
