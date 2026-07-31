"""Default-disabled T247 graph-host correction selected by T251A3.

This variant changes only the host boundary around the frozen calibrator and
locomotion graphs.  The observation assembler writes directly into the active
graph's pre-bound input buffer.  The send-authoritative action is validated
before target generation; the complete action/state chain remains validated
after a confirmed send and before recurrent state is committed.
"""

from __future__ import annotations

from tools.winner_v14_optimized import WinnerV14X5OptimizedTransaction

CONTRACT_ID = "open-duck-mini.t251a4.winner-v15.graph-host-optimized.115x14.v1"


class WinnerV15GraphHostOptimizedTransaction(WinnerV14X5OptimizedTransaction):
    """Byte-exact direct-bound host for the unchanged T247 graphs."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        observation = self._calibrator._observation[0]
        self.assembler.observation = observation
        self._calibrator.bind_trusted_observation(observation)
        self._calibrator.stage = self._calibrator.stage_bound_action_validated

    def confirm_calibration_handoff(self, confirmed_success: object) -> None:
        # The predecessor performs and commits the complete exact handoff first.
        # Only a successful handoff may switch the assembler's trusted buffer.
        super().confirm_calibration_handoff(confirmed_success)
        observation = self._locomotion._observation[0]
        self.assembler.observation = observation
        self._locomotion.bind_trusted_observation(observation)
        self._locomotion.stage = self._locomotion.stage_bound_action_validated
