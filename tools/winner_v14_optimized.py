"""Default-disabled, bit-exact X5 hot-path optimization for Winner-v13.

The optimization changes no policy graph, ABI, observation ordering, numeric
state, target semantics, or transaction boundary. It removes duplicated finite
scans, caches an unchanged reference lookup, precomputes P30 coefficients, and
updates the P30 delay state with preallocated numpy buffers.
"""

from __future__ import annotations

import math

import numpy as np

from open_duck_x5.constants import (
    ACTION_DIM,
    ACTION_SCALE_RAD,
    CONTROL_FREQUENCY_HZ,
    HOME_RAD,
    LEGACY_TARGET_RATE_LIMIT_RAD_S,
)
from open_duck_x5.winner_v2 import (
    WINNER_V2_HOME_RAD,
    WINNER_V2_OBSERVATION_DIM,
    WINNER_V2_RATE_LIMITS_RAD_S,
    WinnerV2ContractError,
    WinnerV2ObservationAssembler,
    validate_winner_v2_command,
)
from open_duck_x5.winner_v13_state_coherent import (
    P30FitAsset,
    StateCoherentP30Observer,
    StateCoherentTargetPipeline,
    WinnerV13ContractError,
    WinnerV13StateCoherentTransaction,
)

CONTRACT_ID = "open-duck-mini.t251a.winner-v14.x5-optimized.115x14.v1"


class X5OptimizedObservationAssembler(WinnerV2ObservationAssembler):
    """Bit-exact assembler with one finite scan and a command-reference cache."""

    def __init__(self, reference: object) -> None:
        super().__init__(reference)
        self._observation_finite = np.ones(WINNER_V2_OBSERVATION_DIM, dtype=np.bool_)
        self._cached_reference_command = np.full(3, np.nan, dtype=np.float32)
        self._cached_reference_index = -2

    def build(
        self,
        *,
        gyro_rad_s: np.ndarray,
        acceleration_m_s2: np.ndarray,
        commands: np.ndarray,
        positions_rad: np.ndarray,
        velocities_rad_s: np.ndarray,
        observer_target_rad: np.ndarray,
        foot_contacts: np.ndarray,
        phase: np.ndarray,
        phase_index: int,
        servo_stale: np.ndarray,
        imu_stale: bool,
        contacts_stale: bool,
    ) -> np.ndarray:
        self._shape("gyro", gyro_rad_s, (3,))
        self._shape("acceleration", acceleration_m_s2, (3,))
        self._shape("commands", commands, (7,))
        self._shape("positions", positions_rad, (ACTION_DIM,))
        self._shape("velocities", velocities_rad_s, (ACTION_DIM,))
        self._shape("observer_target", observer_target_rad, (ACTION_DIM,))
        self._shape("foot_contacts", foot_contacts, (2,))
        self._shape("phase", phase, (2,))
        self._shape("servo_stale", servo_stale, (ACTION_DIM,))
        if bool(servo_stale.any()) or imu_stale or contacts_stale:
            raise WinnerV2ContractError(
                "required winner-v2 sample is stale; refusing mixed-age observation"
            )
        if not isinstance(phase_index, (int, np.integer)):
            raise WinnerV2ContractError("phase index must be an integer")

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
        obs[83:97] = observer_target_rad
        obs[97:99] = foot_contacts
        obs[99:101] = phase

        np.isfinite(obs, out=self._observation_finite)
        if not bool(self._observation_finite.all()):
            # Preserve the predecessor's field-specific diagnostic on the cold
            # fault path without charging eight numpy calls to every valid tick.
            return super().build(
                gyro_rad_s=gyro_rad_s,
                acceleration_m_s2=acceleration_m_s2,
                commands=commands,
                positions_rad=positions_rad,
                velocities_rad_s=velocities_rad_s,
                observer_target_rad=observer_target_rad,
                foot_contacts=foot_contacts,
                phase=phase,
                phase_index=phase_index,
                servo_stale=servo_stale,
                imu_stale=imu_stale,
                contacts_stale=contacts_stale,
            )
        if (
            float(commands[1]) != 0.0
            or float(commands[2]) != 0.0
            or float(commands[3]) != 0.0
            or float(commands[4]) != 0.0
            or float(commands[5]) != 0.0
            or float(commands[6]) != 0.0
        ) or (
            float(commands[0]) != 0.0 and not 0.074 <= float(commands[0]) <= 0.080
        ):
            validate_winner_v2_command(commands)

        command3 = obs[6:9]
        if command3[0] != self._cached_reference_command[0]:
            np.copyto(self._cached_reference_command, command3)
            if bool(np.all(command3 == 0.0)):
                self._cached_reference_index = -1
            else:
                np.subtract(
                    self.reference.commands,
                    command3,
                    out=self.reference._difference,
                )
                np.abs(self.reference._difference, out=self.reference._difference)
                np.sum(
                    self.reference._difference,
                    axis=1,
                    out=self.reference._distance,
                )
                self._cached_reference_index = int(np.argmin(self.reference._distance))
        if self._cached_reference_index < 0:
            obs[101:115].fill(0.0)
        else:
            np.copyto(
                obs[101:115],
                self.reference.actions[
                    self._cached_reference_index,
                    int(phase_index) % 27,
                ],
            )
        return obs


class X5OptimizedP30Observer(StateCoherentP30Observer):
    """Vectorized observer whose next-state calculation runs after confirmed send."""

    def __init__(self, asset: P30FitAsset) -> None:
        super().__init__(asset)
        self._delay = np.asarray([param.delay_ticks for param in self.params], dtype=np.int64)
        self._positive_delay = self._delay > 0
        self._has_positive_delay = bool(self._positive_delay.any())
        self._joint_indices = np.arange(ACTION_DIM, dtype=np.int64)
        maximum_delay = int(np.max(self._delay))
        self._history = np.repeat(
            self._value[np.newaxis, :],
            max(1, maximum_delay),
            axis=0,
        )
        self._delayed = self._value.copy()
        self._desired = self._value.copy()
        self._delta = np.zeros(ACTION_DIM, dtype=np.float64)
        self._step = np.zeros(ACTION_DIM, dtype=np.float64)
        self._alpha = np.ones(ACTION_DIM, dtype=np.float64)
        self._tau_positive = np.zeros(ACTION_DIM, dtype=np.bool_)
        self._max_step = np.empty(ACTION_DIM, dtype=np.float64)
        for index, param in enumerate(self.params):
            if param.tau_s > 0.0:
                self._tau_positive[index] = True
                self._alpha[index] = 1.0 - math.exp(-0.02 / param.tau_s)
            self._max_step[index] = param.velocity_limit_rad_s * 0.02
        self._negative_max_step = -self._max_step

    def stage_confirmed_target(self, sent_logical_target_rad: np.ndarray) -> None:
        if self._pending:
            raise WinnerV2ContractError("P30 observer already has a staged target")
        if sent_logical_target_rad.shape != (ACTION_DIM,):
            raise WinnerV2ContractError("sent_logical_target_rad must have shape (14,)")
        np.isfinite(sent_logical_target_rad, out=self._target_finite)
        if not bool(self._target_finite.all()):
            raise WinnerV2ContractError("sent_logical_target_rad contains a non-finite value")
        np.copyto(self._staged_target, sent_logical_target_rad, casting="unsafe")
        self._pending = True

    def commit_staged(self) -> None:
        if not self._pending:
            raise WinnerV2ContractError("P30 observer has no staged target")
        np.copyto(self._delayed, self._staged_target)
        if self._has_positive_delay:
            mask = self._positive_delay
            self._delayed[mask] = self._history[
                self._delay[mask] - 1,
                self._joint_indices[mask],
            ]
        np.copyto(self._desired, self._delayed)
        np.subtract(self._delayed, self._value, out=self._delta)
        np.multiply(self._delta, self._alpha, out=self._step)
        np.add(self._value, self._step, out=self._step)
        self._desired[self._tau_positive] = self._step[self._tau_positive]
        np.subtract(self._desired, self._value, out=self._step)
        np.clip(self._step, self._negative_max_step, self._max_step, out=self._step)
        np.add(self._value, self._step, out=self._staged_value)
        np.isfinite(self._staged_value, out=self._value_finite)
        if not bool(self._value_finite.all()):
            raise WinnerV2ContractError("P30 observer staged a non-finite value")
        np.copyto(self._value, self._staged_value)
        if self._history.shape[0] > 1:
            self._history[1:] = self._history[:-1]
        np.copyto(self._history[0], self._staged_target)
        self._pending = False


class X5OptimizedTargetPipeline(StateCoherentTargetPipeline):
    """Prevalidated equivalent of the Winner-v13 target pipeline."""

    def __init__(self) -> None:
        super().__init__()
        self._max_step = np.float32(LEGACY_TARGET_RATE_LIMIT_RAD_S / CONTROL_FREQUENCY_HZ)
        self._offset_finite = np.ones(ACTION_DIM, dtype=np.bool_)

    def stage(
        self,
        action: np.ndarray,
        soft_offsets_rad: np.ndarray,
        *,
        mode: str,
    ) -> np.ndarray:
        if self._pending:
            raise WinnerV13ContractError("target pipeline already has a staged target")
        if mode not in {"calibration", "locomotion"}:
            raise WinnerV13ContractError(f"unknown target-pipeline mode: {mode}")
        if not isinstance(action, np.ndarray) or action.shape != (ACTION_DIM,):
            raise WinnerV13ContractError("action must be a numpy shape-(14,) vector")
        if action.dtype != np.dtype(np.float32):
            raise WinnerV13ContractError(f"action must be float32, got {action.dtype}")
        if not isinstance(soft_offsets_rad, np.ndarray) or soft_offsets_rad.shape != (ACTION_DIM,):
            raise WinnerV13ContractError("soft_offsets_rad must be a numpy shape-(14,) vector")
        np.isfinite(soft_offsets_rad, out=self._offset_finite)
        if not bool(self._offset_finite.all()):
            raise WinnerV13ContractError("soft_offsets_rad contains a non-finite value")

        np.multiply(action, np.float32(ACTION_SCALE_RAD), out=self.desired_logical_target_rad)
        np.add(
            self.desired_logical_target_rad,
            WINNER_V2_HOME_RAD,
            out=self.desired_logical_target_rad,
        )
        if mode == "calibration":
            np.subtract(
                self._previous_sent_logical_target_rad,
                self._max_step,
                out=self._lower_bound,
            )
            np.add(
                self._previous_sent_logical_target_rad,
                self._max_step,
                out=self._upper_bound,
            )
            np.clip(
                self.desired_logical_target_rad,
                self._lower_bound,
                self._upper_bound,
                out=self.sent_logical_target_rad,
            )
        else:
            # Every per-joint measured limit is <= 5.24 rad/s, so passing the
            # stricter monitor below proves the inherited clamp is identity.
            np.copyto(self.sent_logical_target_rad, self.desired_logical_target_rad)
        np.subtract(
            self.sent_logical_target_rad,
            self._previous_sent_logical_target_rad,
            out=self.implied_velocity_rad_s,
        )
        self.implied_velocity_rad_s *= CONTROL_FREQUENCY_HZ
        np.abs(self.implied_velocity_rad_s, out=self._absolute_velocity_rad_s)
        np.subtract(
            self._absolute_velocity_rad_s,
            WINNER_V2_RATE_LIMITS_RAD_S,
            out=self.graph_rate_excess_rad_s,
        )
        np.maximum(self.graph_rate_excess_rad_s, 0.0, out=self.graph_rate_excess_rad_s)
        self.graph_rate_excess_rad_s[self.graph_rate_excess_rad_s <= 1.0e-5] = 0.0
        if mode == "locomotion" and bool(self.graph_rate_excess_rad_s.any()):
            indices = np.flatnonzero(self.graph_rate_excess_rad_s > 0.0).tolist()
            raise WinnerV13ContractError(
                f"locomotion graph measured-rate envelope exceeded at joints {indices}"
            )
        np.add(self.sent_logical_target_rad, soft_offsets_rad, out=self.physical_target_rad)
        self._pending = True
        self._staged_mode = mode
        return self.physical_target_rad


class WinnerV14X5OptimizedTransaction(WinnerV13StateCoherentTransaction):
    """Default-disabled optimized implementation of the exact Winner-v13 state."""

    def __init__(self, *args: object, p30_fit: P30FitAsset, **kwargs: object) -> None:
        super().__init__(*args, p30_fit=p30_fit, **kwargs)
        self.observer = X5OptimizedP30Observer(p30_fit)
        self.assembler = X5OptimizedObservationAssembler(self.reference)
        self.target_pipeline = X5OptimizedTargetPipeline()
        # The optimized assembler performs one final finite scan over all 115
        # fields. Avoid repeating it inside each graph session.
        self._calibrator.stage = self._calibrator.stage_prevalidated_fast
        self._locomotion.stage = self._locomotion.stage_prevalidated_fast
