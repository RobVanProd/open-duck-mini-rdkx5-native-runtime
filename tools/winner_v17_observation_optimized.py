"""Default-disabled observation-only optimization selected after T251A5."""

from __future__ import annotations

import numpy as np

from open_duck_x5.constants import ACTION_DIM, HOME_RAD
from open_duck_x5.winner_v2 import (
    WINNER_V2_OBSERVATION_DIM,
    WinnerV2ContractError,
)
from open_duck_x5.winner_v13_state_coherent import (
    CALIBRATION_COMMAND,
    CALIBRATION_PHASE,
    WinnerV13ContractError,
    WinnerV13StateError,
)
from tools.winner_v14_optimized import X5OptimizedObservationAssembler
from tools.winner_v16_target_optimized import WinnerV16TargetOptimizedTransaction

CONTRACT_ID = "open-duck-mini.t251a6.winner-v17.observation-optimized.115x14.v1"


class X5TrustedObservationAssembler(X5OptimizedObservationAssembler):
    """Exact assembler for cold-bound stable runtime sample arrays."""

    def __init__(self, reference: object) -> None:
        super().__init__(reference)
        self._action_history = np.zeros((4, ACTION_DIM), dtype=np.float32)
        self.last_action = self._action_history[0]
        self.action_minus_2 = self._action_history[1]
        self.action_minus_3 = self._action_history[2]
        self._deferred_action = self._action_history[3]
        self._visible_action_history = self._action_history[:3]
        self._observation_history = self.observation[41:83].reshape(3, ACTION_DIM)
        self._gyro: np.ndarray | None = None
        self._acceleration: np.ndarray | None = None
        self._commands: np.ndarray | None = None
        self._positions: np.ndarray | None = None
        self._velocities: np.ndarray | None = None
        self._observer_target: np.ndarray | None = None
        self._foot_contacts: np.ndarray | None = None
        self._phase: np.ndarray | None = None
        self._servo_stale: np.ndarray | None = None

    def bind_output(self, observation: np.ndarray) -> None:
        if (
            not isinstance(observation, np.ndarray)
            or observation.shape != (WINNER_V2_OBSERVATION_DIM,)
            or observation.dtype != np.dtype(np.float32)
        ):
            raise WinnerV13ContractError(
                "observation output must be float32 shape (115,)"
            )
        self.observation = observation
        self._observation_history = observation[41:83].reshape(3, ACTION_DIM)

    def bind_sources(
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
        servo_stale: np.ndarray,
    ) -> None:
        if self._gyro is not None:
            raise WinnerV13StateError("observation sources are already bound")
        expected = (
            ("gyro", gyro_rad_s, (3,), np.float64),
            ("acceleration", acceleration_m_s2, (3,), np.float64),
            ("commands", commands, (7,), np.float64),
            ("positions", positions_rad, (ACTION_DIM,), np.float64),
            ("velocities", velocities_rad_s, (ACTION_DIM,), np.float64),
            ("observer_target", observer_target_rad, (ACTION_DIM,), np.float64),
            ("foot_contacts", foot_contacts, (2,), np.float64),
            ("phase", phase, (2,), np.float32),
            ("servo_stale", servo_stale, (ACTION_DIM,), np.bool_),
        )
        for name, value, shape, dtype in expected:
            if (
                not isinstance(value, np.ndarray)
                or value.shape != shape
                or value.dtype != np.dtype(dtype)
            ):
                raise WinnerV13ContractError(
                    f"bound {name} must be {np.dtype(dtype)} shape {shape}"
                )
        self._gyro = gyro_rad_s
        self._acceleration = acceleration_m_s2
        self._commands = commands
        self._positions = positions_rad
        self._velocities = velocities_rad_s
        self._observer_target = observer_target_rad
        self._foot_contacts = foot_contacts
        self._phase = phase
        self._servo_stale = servo_stale

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
        if (
            gyro_rad_s is not self._gyro
            or acceleration_m_s2 is not self._acceleration
            or positions_rad is not self._positions
            or velocities_rad_s is not self._velocities
            or observer_target_rad is not self._observer_target
            or foot_contacts is not self._foot_contacts
            or servo_stale is not self._servo_stale
            or (commands is not CALIBRATION_COMMAND and commands is not self._commands)
            or (phase is not CALIBRATION_PHASE and phase is not self._phase)
        ):
            raise WinnerV2ContractError(
                "observation source is not its exact cold-bound runtime array"
            )
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
        np.subtract(
            positions_rad,
            HOME_RAD,
            out=obs[13:27],
            casting="unsafe",
        )
        np.multiply(
            velocities_rad_s,
            0.05,
            out=obs[27:41],
            casting="unsafe",
        )
        np.copyto(self._observation_history, self._visible_action_history)
        obs[83:97] = observer_target_rad
        obs[97:99] = foot_contacts
        obs[99:101] = phase

        np.isfinite(obs, out=self._observation_finite)
        if not bool(self._observation_finite.all()):
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
            or (
                float(commands[0]) != 0.0
                and not 0.074 <= float(commands[0]) <= 0.080
            )
        ):
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


class WinnerV17ObservationOptimizedTransaction(WinnerV16TargetOptimizedTransaction):
    """Unchanged T247 host with only the selected observation correction."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        assembler = X5TrustedObservationAssembler(self.reference)
        assembler.bind_output(self._calibrator._observation[0])
        self.assembler = assembler
        self._calibrator.bind_trusted_observation(assembler.observation)

    def bind_observation_sources(
        self,
        *,
        gyro_rad_s: np.ndarray,
        acceleration_m_s2: np.ndarray,
        commands: np.ndarray,
        positions_rad: np.ndarray,
        velocities_rad_s: np.ndarray,
        foot_contacts: np.ndarray,
        servo_stale: np.ndarray,
    ) -> None:
        if self.pending or self.committed_ticks != 0:
            raise WinnerV13StateError(
                "observation sources must be bound before the first tick"
            )
        self.assembler.bind_sources(
            gyro_rad_s=gyro_rad_s,
            acceleration_m_s2=acceleration_m_s2,
            commands=commands,
            positions_rad=positions_rad,
            velocities_rad_s=velocities_rad_s,
            observer_target_rad=self.observer.value_view,
            foot_contacts=foot_contacts,
            phase=self.phase.value,
            servo_stale=servo_stale,
        )

    def confirm_calibration_handoff(self, confirmed_success: object) -> None:
        super().confirm_calibration_handoff(confirmed_success)
        # V15 installed and trusted this exact ndarray view object. Refresh
        # only the assembler's cached history view without creating a new
        # row-view object that would fail the graph's identity contract.
        self.assembler.bind_output(self.assembler.observation)
