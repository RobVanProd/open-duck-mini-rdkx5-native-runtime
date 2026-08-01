"""Default-disabled transaction-shell optimization selected after T251A6."""

from __future__ import annotations

import numpy as np

from open_duck_x5.constants import ACTION_DIM, CONTROL_PERIOD_NS
from open_duck_x5.winner_v13_state_coherent import (
    CALIBRATION_TICKS,
    WinnerV13ContractError,
    WinnerV13StateError,
)
from tools.winner_v16_target_optimized import WinnerV16TargetOptimizedTransaction

CONTRACT_ID = "open-duck-mini.t251a7.winner-v18.transaction-optimized.115x14.v1"


class WinnerV18TransactionOptimizedTransaction(
    WinnerV16TargetOptimizedTransaction
):
    """Exact V16 host with a cold-bound locomotion transaction entry point."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._bound_gyro: np.ndarray | None = None
        self._bound_acceleration: np.ndarray | None = None
        self._bound_commands: np.ndarray | None = None
        self._bound_positions: np.ndarray | None = None
        self._bound_velocities: np.ndarray | None = None
        self._bound_contacts: np.ndarray | None = None
        self._bound_servo_stale: np.ndarray | None = None
        self._bound_soft_offsets: np.ndarray | None = None

    def bind_tick_inputs(
        self,
        *,
        gyro_rad_s: np.ndarray,
        acceleration_m_s2: np.ndarray,
        commands: np.ndarray,
        positions_rad: np.ndarray,
        velocities_rad_s: np.ndarray,
        foot_contacts: np.ndarray,
        servo_stale: np.ndarray,
        soft_offsets_rad: np.ndarray,
    ) -> None:
        """Cold-bind the caller-owned arrays used by every locomotion tick."""

        if self._bound_gyro is not None:
            raise WinnerV13StateError("transaction inputs are already bound")
        if self.pending or self.committed_ticks != 0:
            raise WinnerV13StateError(
                "transaction inputs must be bound before the first tick"
            )
        expected = (
            ("gyro", gyro_rad_s, (3,), np.float64),
            ("acceleration", acceleration_m_s2, (3,), np.float64),
            ("commands", commands, (7,), np.float64),
            ("positions", positions_rad, (ACTION_DIM,), np.float64),
            ("velocities", velocities_rad_s, (ACTION_DIM,), np.float64),
            ("foot contacts", foot_contacts, (2,), np.float64),
            ("servo stale", servo_stale, (ACTION_DIM,), np.bool_),
            ("soft offsets", soft_offsets_rad, (ACTION_DIM,), np.float64),
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
        if self.target_pipeline._trusted_offsets is not soft_offsets_rad:
            raise WinnerV13ContractError(
                "bound soft offsets are not the exact trusted immutable array"
            )
        self._bound_gyro = gyro_rad_s
        self._bound_acceleration = acceleration_m_s2
        self._bound_commands = commands
        self._bound_positions = positions_rad
        self._bound_velocities = velocities_rad_s
        self._bound_contacts = foot_contacts
        self._bound_servo_stale = servo_stale
        self._bound_soft_offsets = soft_offsets_rad

    def _stage_through_predecessor(
        self,
        tick_index: object,
        servo_sample_tick_index: object,
        imu_sample_tick_index: object,
        contacts_sample_tick_index: object,
        imu_stale: bool,
        contacts_stale: bool,
    ) -> np.ndarray:
        if self._bound_gyro is None:
            raise WinnerV13StateError("transaction inputs are not bound")
        return super().stage_tick(
            tick_index=tick_index,  # type: ignore[arg-type]
            logical_period_ns=CONTROL_PERIOD_NS,
            servo_sample_tick_index=servo_sample_tick_index,  # type: ignore[arg-type]
            imu_sample_tick_index=imu_sample_tick_index,  # type: ignore[arg-type]
            contacts_sample_tick_index=contacts_sample_tick_index,  # type: ignore[arg-type]
            gyro_rad_s=self._bound_gyro,
            acceleration_m_s2=self._bound_acceleration,
            commands=self._bound_commands,
            positions_rad=self._bound_positions,
            velocities_rad_s=self._bound_velocities,
            foot_contacts=self._bound_contacts,
            servo_stale=self._bound_servo_stale,
            imu_stale=imu_stale,
            contacts_stale=contacts_stale,
            soft_offsets_rad=self._bound_soft_offsets,
        )

    def stage_bound_tick(
        self,
        tick_index: int,
        servo_sample_tick_index: int,
        imu_sample_tick_index: int,
        contacts_sample_tick_index: int,
        imu_stale: bool,
        contacts_stale: bool,
    ) -> np.ndarray:
        """Stage one post-handoff tick from the exact cold-bound inputs."""

        expected_tick = self.committed_ticks
        fast_path = (
            self._enabled
            and not self._faulted
            and not self.pending
            and self._handoff_complete
            and self._confirmed_calibration_ticks == CALIBRATION_TICKS
            and isinstance(tick_index, (int, np.integer))
            and int(tick_index) == expected_tick
            and (
                servo_sample_tick_index,
                imu_sample_tick_index,
                contacts_sample_tick_index,
            )
            == (expected_tick, expected_tick, expected_tick)
            and self._bound_gyro is not None
        )
        if not fast_path:
            return self._stage_through_predecessor(
                tick_index,
                servo_sample_tick_index,
                imu_sample_tick_index,
                contacts_sample_tick_index,
                imu_stale,
                contacts_stale,
            )

        try:
            observation = self.assembler.build(
                gyro_rad_s=self._bound_gyro,
                acceleration_m_s2=self._bound_acceleration,
                commands=self._bound_commands,
                positions_rad=self._bound_positions,
                velocities_rad_s=self._bound_velocities,
                observer_target_rad=self.observer.value_view,
                foot_contacts=self._bound_contacts,
                phase=self.phase.value,
                phase_index=self.phase.index,
                servo_stale=self._bound_servo_stale,
                imu_stale=imu_stale,
                contacts_stale=contacts_stale,
            )
            if self._first_locomotion_observation:
                observation[41:55] = self._calibration_action_history[0]
                observation[55:69] = self._calibration_action_history[1]
                observation[69:83] = self._calibration_action_history[2]
            action = self._locomotion.stage(observation)
            np.copyto(self._staged_action, action)
            physical_target = self.target_pipeline.stage(
                self._staged_action,
                self._bound_soft_offsets,
                mode="locomotion",
            )
            self.observer.stage_confirmed_target(
                self.target_pipeline.sent_logical_target_rad
            )
        except Exception as exc:
            self._fault(f"locomotion stage failed: {exc}")
            raise
        self._staged_stage = "locomotion"
        self._staged_tick = int(tick_index)
        return physical_target
