from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .constants import (
    ACTION_DIM,
    ACTION_SCALE_RAD,
    CONTROL_FREQUENCY_HZ,
    ENVELOPE_MONITOR_RAD_S,
    HOME_RAD,
    LEGACY_TARGET_RATE_LIMIT_RAD_S,
    OBSERVATION_DIM,
    PHASE_PERIOD_TICKS,
)


class StaleObservationError(RuntimeError):
    pass


class ContractShapeError(ValueError):
    pass


@dataclass(slots=True)
class PhaseClock:
    frequency_factor_offset: float = 0.0
    index: float = 0.0
    value: np.ndarray = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # The inherited runtime starts with [0, 0], not [1, 0].
        self.value = np.zeros(2, dtype=np.float64)

    def advance(self, base_factor: float = 1.0) -> np.ndarray:
        self.index = (self.index + base_factor + self.frequency_factor_offset) % PHASE_PERIOD_TICKS
        angle = self.index / PHASE_PERIOD_TICKS * 2.0 * math.pi
        self.value[0] = math.cos(angle)
        self.value[1] = math.sin(angle)
        return self.value


class ObservationAssembler:
    """Preallocated implementation of the frozen 101-element observation map."""

    def __init__(self) -> None:
        self.observation = np.zeros(OBSERVATION_DIM, dtype=np.float32)
        self.last_action = np.zeros(ACTION_DIM, dtype=np.float32)
        self.action_minus_2 = np.zeros(ACTION_DIM, dtype=np.float32)
        self.action_minus_3 = np.zeros(ACTION_DIM, dtype=np.float32)
        self._position_error = np.zeros(ACTION_DIM, dtype=np.float64)
        self._velocity_scaled = np.zeros(ACTION_DIM, dtype=np.float64)

    @staticmethod
    def _require_shape(name: str, value: np.ndarray, shape: tuple[int, ...]) -> None:
        if value.shape != shape:
            raise ContractShapeError(f"{name} must have shape {shape}, got {value.shape}")

    def build(
        self,
        *,
        gyro_rad_s: np.ndarray,
        acceleration_m_s2: np.ndarray,
        commands: np.ndarray,
        positions_rad: np.ndarray,
        velocities_rad_s: np.ndarray,
        previous_motor_target_rad: np.ndarray,
        foot_contacts: np.ndarray,
        phase: np.ndarray,
        servo_stale: np.ndarray,
        imu_stale: bool,
        contacts_stale: bool,
    ) -> np.ndarray:
        self._require_shape("gyro", gyro_rad_s, (3,))
        self._require_shape("acceleration", acceleration_m_s2, (3,))
        self._require_shape("commands", commands, (7,))
        self._require_shape("positions", positions_rad, (ACTION_DIM,))
        self._require_shape("velocities", velocities_rad_s, (ACTION_DIM,))
        self._require_shape("previous_motor_target", previous_motor_target_rad, (ACTION_DIM,))
        self._require_shape("foot_contacts", foot_contacts, (2,))
        self._require_shape("phase", phase, (2,))
        self._require_shape("servo_stale", servo_stale, (ACTION_DIM,))
        if bool(servo_stale.any()) or imu_stale or contacts_stale:
            raise StaleObservationError(
                "required input is stale; refusing to assemble a mixed-age policy observation"
            )

        obs = self.observation
        obs[0:3] = gyro_rad_s
        obs[3:6] = acceleration_m_s2
        obs[6:13] = commands
        np.subtract(positions_rad, HOME_RAD, out=self._position_error)
        obs[13:27] = self._position_error
        np.multiply(velocities_rad_s, 0.05, out=self._velocity_scaled)
        obs[27:41] = self._velocity_scaled
        obs[41:55] = self.last_action
        obs[55:69] = self.action_minus_2
        obs[69:83] = self.action_minus_3
        obs[83:97] = previous_motor_target_rad
        obs[97:99] = foot_contacts
        obs[99:101] = phase
        return obs

    def commit_action(self, action: np.ndarray) -> None:
        self._require_shape("action", action, (ACTION_DIM,))
        np.copyto(self.action_minus_3, self.action_minus_2)
        np.copyto(self.action_minus_2, self.last_action)
        np.copyto(self.last_action, action, casting="unsafe")


class ActionPipeline:
    """Frozen action semantics plus a telemetry-only velocity envelope monitor."""

    def __init__(self) -> None:
        self.unlimited_target_rad = np.zeros(ACTION_DIM, dtype=np.float64)
        self.rate_limited_target_rad = HOME_RAD.copy()
        self.sent_target_rad = HOME_RAD.copy()
        self.physical_target_rad = HOME_RAD.copy()
        self.implied_velocity_rad_s = np.zeros(ACTION_DIM, dtype=np.float64)
        self.over_envelope = np.zeros(ACTION_DIM, dtype=np.bool_)
        self._absolute_velocity_rad_s = np.zeros(ACTION_DIM, dtype=np.float64)
        self._delta = np.zeros(ACTION_DIM, dtype=np.float64)
        self._previous_rate_target = HOME_RAD.copy()
        self._previous_sent_target = HOME_RAD.copy()

    @property
    def previous_motor_target_rad(self) -> np.ndarray:
        # This is what the inherited observation stores, including head overlay.
        return self._previous_sent_target

    def seed_previous_targets(
        self,
        rate_limited_target_rad: np.ndarray,
        sent_target_rad: np.ndarray,
    ) -> None:
        """Seed one captured legacy tick for field-by-field contract verification."""
        if rate_limited_target_rad.shape != (ACTION_DIM,):
            raise ContractShapeError(
                f"rate-limited target must have shape ({ACTION_DIM},)"
            )
        if sent_target_rad.shape != (ACTION_DIM,):
            raise ContractShapeError(f"sent target must have shape ({ACTION_DIM},)")
        np.copyto(self._previous_rate_target, rate_limited_target_rad)
        np.copyto(self.rate_limited_target_rad, rate_limited_target_rad)
        np.copyto(self._previous_sent_target, sent_target_rad)
        np.copyto(self.sent_target_rad, sent_target_rad)

    def apply(
        self, action: np.ndarray, commands: np.ndarray, soft_offsets_rad: np.ndarray
    ) -> np.ndarray:
        if action.shape != (ACTION_DIM,):
            raise ContractShapeError(f"action must have shape ({ACTION_DIM},)")
        if commands.shape != (7,):
            raise ContractShapeError("commands must have shape (7,)")
        if soft_offsets_rad.shape != (ACTION_DIM,):
            raise ContractShapeError(f"offsets must have shape ({ACTION_DIM},)")

        np.multiply(action, ACTION_SCALE_RAD, out=self.unlimited_target_rad)
        np.add(self.unlimited_target_rad, HOME_RAD, out=self.unlimited_target_rad)
        np.subtract(self.unlimited_target_rad, self._previous_rate_target, out=self._delta)
        max_step = LEGACY_TARGET_RATE_LIMIT_RAD_S / CONTROL_FREQUENCY_HZ
        np.clip(self._delta, -max_step, max_step, out=self._delta)
        np.add(self._previous_rate_target, self._delta, out=self.rate_limited_target_rad)
        np.copyto(self._previous_rate_target, self.rate_limited_target_rad)

        np.copyto(self.sent_target_rad, self.rate_limited_target_rad)
        self.sent_target_rad[5:9] += commands[3:7]
        np.subtract(
            self.sent_target_rad,
            self._previous_sent_target,
            out=self.implied_velocity_rad_s,
        )
        self.implied_velocity_rad_s *= CONTROL_FREQUENCY_HZ
        np.absolute(self.implied_velocity_rad_s, out=self._absolute_velocity_rad_s)
        np.greater(
            self._absolute_velocity_rad_s,
            ENVELOPE_MONITOR_RAD_S,
            out=self.over_envelope,
        )
        np.copyto(self._previous_sent_target, self.sent_target_rad)
        np.add(self.sent_target_rad, soft_offsets_rad, out=self.physical_target_rad)
        return self.physical_target_rad
