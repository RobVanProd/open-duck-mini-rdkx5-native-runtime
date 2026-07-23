# Winner-v12 / Winner-v102 runtime alignment audit

Status: `HOLD_FINAL_V102_GRAPH_AND_GOLDEN_REPLAY`

This is an offline CPU/mock audit. It does not authorize robot access, policy
deployment, serial access, torque, motion, Gate 5, or grounded walking.

## Finding and correction

The provisional two-graph host originally performed 250 calibration
transactions and then handed the calibrator's last action directly to the
locomotion graph. That differed from the accepted Winner-v102 training reset:

1. 250 calibrator-driven response ticks;
2. 250 explicit zero-action home-return ticks;
3. locomotion phase reset to `[1, 0]`;
4. locomotion recurrent state and `previous_action` reset to exact zero;
5. the final 64-D calibration context held immutable during locomotion.

The runtime host now implements that exact sequencing. Home return is a
separate transactional phase with an immutable zero action, exactly 250
literal-`True` confirmations, explicit final handoff, and fail-closed behavior
for skipped, failed, or ambiguous commits. The calibrator context is captured
after tick 250, retained through home return, and copied into the locomotion
graph only after home return passes. Locomotion begins with exact-zero
`previous_action` and hidden state.

## Evidence

- Existing base runtime-v2 completion audit:
  `artifacts/gates/phase_5_policy/winner_v2_completion_audit_20260719.json`
  at SHA-256
  `a226e8c69c4cdc5931c1b79077b219795d0c070b0500a9ce52997706d8501af4`.
  It records the frozen 101-D v1 separation, 115-D observation semantics,
  P30 observer, projected-reference slot, graph-authoritative transforms,
  fail-closed transaction state, and the prior four-cell / 2,400-tick
  candidate replay as passing.
- Corrected provisional two-graph host:
  `src/open_duck_x5/winner_v12_two_stage.py` at SHA-256
  `231d76ed15611447a9215b22252a3e8754dc8a378cc3166f870f81b5d7dca25d`.
- Focused contract tests:
  `tests/test_winner_v12_two_stage.py` at SHA-256
  `d4f6e89c1afb64a088aeb5a4b04c4b7dd6d373066cdebe44e9510361b254b045`.
  They cover default-disabled zero inference, exact graph hashes and ABIs,
  CPU-only sessions, calibration/home-return counts, immutable context,
  zero-state locomotion handoff, transaction discard/commit behavior,
  nonfinite and out-of-range outputs, action/state divergence, ambiguous
  confirmations, and a synthetic four-cell / 2,400-tick state-chain replay.
- Repository validation after the correction: `375 passed`.
- Policy-side pre-outcome selection contract:
  `winner_v103_response_conditioned_behavior_preregistration.json` at
  SHA-256
  `1087c9a60b93c359be15d2423bf3f1fc1cbc740e3a7d6fc4a650f6b73cb7efcf`
  on policy commit `490810ec`. It freezes the unchanged 1,024-cell evaluation
  matrix and the same 250+250 reset prefix.

## What remains unproven

- Winner-v102 hosted training has not run.
- No final locomotion checkpoint or locomotion ONNX SHA-256 exists.
- The synthetic 2,400-tick two-graph test is not a substitute for replaying
  the selected final ONNX and its golden traces.
- The final calibrator/locomotion pair has not passed the complete 2,400-tick
  runtime replay.
- The no-servo X5 CPU timing preflight remains `NOT_RUN`.
- `robot_clearance` remains `false`.

The old 46-field manual COM worksheet is not a remaining requirement on this
route. Winner-v102 replaces static per-build measurements with automatic
response calibration, but that mechanism still must pass its hosted training,
full CPU behavior matrix, exact asset selection, final runtime replay, and
later separately authorized hardware gates.
