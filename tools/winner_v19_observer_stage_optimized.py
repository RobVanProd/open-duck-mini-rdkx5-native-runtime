"""Default-disabled observer-stage optimization selected after T251A7."""

from __future__ import annotations

import numpy as np

from open_duck_x5.constants import ACTION_DIM
from open_duck_x5.winner_v2 import WinnerV2ContractError
from open_duck_x5.winner_v13_state_coherent import (
    P30FitAsset,
    WinnerV13ContractError,
    WinnerV13StateError,
)
from tools.winner_v14_optimized import X5OptimizedP30Observer
from tools.winner_v16_target_optimized import WinnerV16TargetOptimizedTransaction

CONTRACT_ID = "open-duck-mini.t251a8.winner-v19.observer-stage-optimized.115x14.v1"


class X5TrustedP30Observer(X5OptimizedP30Observer):
    """P30 observer with an exact post-handoff target-array binding."""

    def __init__(self, asset: P30FitAsset) -> None:
        super().__init__(asset)
        self._trusted_target: np.ndarray | None = None
        self._private_staged_target = self._staged_target
        self._trusted_target_staged = False

    def bind_trusted_target(self, sent_logical_target_rad: np.ndarray) -> None:
        if self._pending:
            raise WinnerV13StateError("cannot bind an observer with a staged target")
        if self._trusted_target is not None:
            raise WinnerV13StateError("observer target is already bound")
        if (
            not isinstance(sent_logical_target_rad, np.ndarray)
            or sent_logical_target_rad.shape != (ACTION_DIM,)
            or sent_logical_target_rad.dtype != np.dtype(np.float32)
        ):
            raise WinnerV13ContractError(
                "trusted observer target must be float32 shape (14,)"
            )
        self._trusted_target = sent_logical_target_rad

    def stage_confirmed_target(self, sent_logical_target_rad: np.ndarray) -> None:
        if sent_logical_target_rad is not self._trusted_target or self._pending:
            return super().stage_confirmed_target(sent_logical_target_rad)
        np.isfinite(sent_logical_target_rad, out=self._target_finite)
        if not bool(self._target_finite.all()):
            raise WinnerV2ContractError(
                "sent_logical_target_rad contains a non-finite value"
            )
        self._staged_target = sent_logical_target_rad
        self._trusted_target_staged = True
        self._pending = True

    def commit_staged(self) -> None:
        super().commit_staged()
        if self._trusted_target_staged:
            # The predecessor retains the last confirmed target in its private
            # staged buffer even after commit.  Preserve that cold-path state
            # exactly while keeping the send-critical stage free of the copy.
            np.copyto(
                self._private_staged_target,
                self._trusted_target,
                casting="unsafe",
            )
            self._staged_target = self._private_staged_target
            self._trusted_target_staged = False

    def discard_staged(self) -> None:
        super().discard_staged()
        if self._trusted_target_staged:
            self._staged_target = self._private_staged_target
            self._trusted_target_staged = False


class WinnerV19ObserverStageOptimizedTransaction(
    WinnerV16TargetOptimizedTransaction
):
    """Unchanged T247 host with only the selected observer-stage correction."""

    def __init__(
        self,
        *args: object,
        p30_fit: P30FitAsset,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, p30_fit=p30_fit, **kwargs)
        self.observer = X5TrustedP30Observer(p30_fit)

    def confirm_calibration_handoff(self, confirmed_success: object) -> None:
        super().confirm_calibration_handoff(confirmed_success)
        self.observer.bind_trusted_target(
            self.target_pipeline.sent_logical_target_rad
        )
