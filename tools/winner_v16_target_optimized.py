"""Default-disabled target-only optimization selected after T251A4."""

from __future__ import annotations

import numpy as np

from open_duck_x5.constants import (
    ACTION_DIM,
    ACTION_SCALE_RAD,
    CONTROL_FREQUENCY_HZ,
)
from open_duck_x5.winner_v2 import (
    WINNER_V2_HOME_RAD,
    WINNER_V2_RATE_LIMITS_RAD_S,
)
from open_duck_x5.winner_v13_state_coherent import (
    WinnerV13ContractError,
    WinnerV13StateError,
)
from tools.winner_v14_optimized import X5OptimizedTargetPipeline
from tools.winner_v15_graph_host_optimized import (
    WinnerV15GraphHostOptimizedTransaction,
)

CONTRACT_ID = "open-duck-mini.t251a5.winner-v16.target-optimized.115x14.v1"


class X5TrustedOffsetTargetPipeline(X5OptimizedTargetPipeline):
    """Exact target pipeline with cold-bound offsets and locomotion identity."""

    def __init__(self) -> None:
        super().__init__()
        self._trusted_offsets: np.ndarray | None = None
        self._locomotion_identity = False

    def bind_soft_offsets(self, soft_offsets_rad: np.ndarray) -> None:
        if self._pending:
            raise WinnerV13StateError("cannot bind offsets with a staged target")
        if self._trusted_offsets is not None:
            raise WinnerV13StateError("soft offsets are already bound")
        if (
            not isinstance(soft_offsets_rad, np.ndarray)
            or soft_offsets_rad.shape != (ACTION_DIM,)
            or soft_offsets_rad.dtype != np.dtype(np.float64)
        ):
            raise WinnerV13ContractError(
                "bound soft offsets must be float64 shape (14,)"
            )
        np.isfinite(soft_offsets_rad, out=self._offset_finite)
        if not bool(self._offset_finite.all()):
            raise WinnerV13ContractError("bound soft offsets contain a non-finite value")
        soft_offsets_rad.setflags(write=False)
        self._trusted_offsets = soft_offsets_rad

    def enter_locomotion_identity(self) -> None:
        if self._pending:
            raise WinnerV13StateError("cannot enter locomotion with a staged target")
        if self._trusted_offsets is None:
            raise WinnerV13StateError("soft offsets must be bound before handoff")
        if self._locomotion_identity:
            raise WinnerV13StateError("locomotion target identity is already active")
        # Locomotion already proved the inherited limiter is identity. Sharing
        # the buffers removes only the redundant desired-to-sent copy.
        self.sent_logical_target_rad = self.desired_logical_target_rad
        self._locomotion_identity = True

    def stage(
        self,
        action: np.ndarray,
        soft_offsets_rad: np.ndarray,
        *,
        mode: str,
    ) -> np.ndarray:
        if soft_offsets_rad is not self._trusted_offsets:
            raise WinnerV13ContractError(
                "soft offsets are not the exact trusted immutable array"
            )
        if mode == "calibration":
            return super().stage(action, soft_offsets_rad, mode=mode)
        if mode != "locomotion":
            raise WinnerV13ContractError(f"unknown target-pipeline mode: {mode}")
        if not self._locomotion_identity:
            raise WinnerV13StateError("locomotion target identity is not active")
        if self._pending:
            raise WinnerV13StateError("target pipeline already has a staged target")
        if not isinstance(action, np.ndarray) or action.shape != (ACTION_DIM,):
            raise WinnerV13ContractError("action must be a numpy shape-(14,) vector")
        if action.dtype != np.dtype(np.float32):
            raise WinnerV13ContractError(f"action must be float32, got {action.dtype}")

        np.multiply(
            action,
            np.float32(ACTION_SCALE_RAD),
            out=self.desired_logical_target_rad,
        )
        np.add(
            self.desired_logical_target_rad,
            WINNER_V2_HOME_RAD,
            out=self.desired_logical_target_rad,
        )
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
        maximum_excess = float(self.graph_rate_excess_rad_s.max())
        if maximum_excess > 1.0e-5:
            # Preserve the predecessor's exposed cold-fault vector exactly.
            np.maximum(
                self.graph_rate_excess_rad_s,
                0.0,
                out=self.graph_rate_excess_rad_s,
            )
            self.graph_rate_excess_rad_s[
                self.graph_rate_excess_rad_s <= 1.0e-5
            ] = 0.0
            indices = np.flatnonzero(self.graph_rate_excess_rad_s > 0.0).tolist()
            raise WinnerV13ContractError(
                f"locomotion graph measured-rate envelope exceeded at joints {indices}"
            )
        self.graph_rate_excess_rad_s.fill(0.0)
        np.add(
            self.sent_logical_target_rad,
            soft_offsets_rad,
            out=self.physical_target_rad,
        )
        self._pending = True
        self._staged_mode = mode
        return self.physical_target_rad


class WinnerV16TargetOptimizedTransaction(WinnerV15GraphHostOptimizedTransaction):
    """Unchanged T247 host with only the selected target correction."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.target_pipeline = X5TrustedOffsetTargetPipeline()

    def bind_soft_offsets(self, soft_offsets_rad: np.ndarray) -> None:
        self.target_pipeline.bind_soft_offsets(soft_offsets_rad)

    def confirm_calibration_handoff(self, confirmed_success: object) -> None:
        super().confirm_calibration_handoff(confirmed_success)
        self.target_pipeline.enter_locomotion_identity()
