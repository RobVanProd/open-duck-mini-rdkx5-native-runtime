# Active Runtime <-> Policy Handoff

This file is the short current handoff. The accumulated historical exchange is
preserved in
[`docs/archive/COMMS_HISTORY_THROUGH_20260722.md`](docs/archive/COMMS_HISTORY_THROUGH_20260722.md).

## Current decision

Status: `T237_FULL_R2_FAILED - CANDIDATE_CLOSED - GATE_5_BLOCKED`

The evaluated offline candidate was the T234B exact low-command route. It keeps
each checkpoint's own policy head at `x=0.0`, `0.077`, and `0.080`, and uses
the paired final checkpoint's head only at the exact float32 command
`x=0.074`. This is a uniform deterministic graph transform, not checkpoint
cherry-picking.

Evidence already green:

- T234B ONNX/ABI and bit-exact route contract;
- T235 fresh nominal matrix: `16/16`;
- T236 fresh former-blocker upper-Z matrix: `16/16`; and
- T237 conditions 1-16: `256/256` cells green; and
- T237 condition 17, `HOME_JOINT_OFFSET_NEG`: `0/16`, terminal failure.

Condition 17 shifted the modeled home joint positions by `-0.03 rad`. Every
`x=0` cell held for the full duration, while every moving-command cell fell
across both checkpoints and both measured actuator fits. Saturation and rate
excess remained zero. T237 stopped at that first failed condition as
preregistered; the exact low-command route is closed with no retry.

## Candidate ABI

The candidate is runtime-v2, not the frozen runtime-v1 interface:

```text
inputs:
  obs[1,115]
  previous_action[1,14]
  calibration_context[1,64]
  h_in[1,64]
outputs:
  continuous_actions[1,14]
  previous_action_out[1,14]
  h_out[1,64]
```

Candidate receipts:

| checkpoint | step | bytes | SHA-256 |
| --- | ---: | ---: | --- |
| half | 1,003,520 | 988,264 | `c34cdba0c1e1c1310f16926161ed3b1cefe89e79ea88636ed2b4d5feb535b370` |
| final | 2,007,040 | 988,264 | `b19b81262aba747871058238c92f0f4bd57ffaa16b8e70ab007c8c9849c02e51` |

These receipts identify evaluation candidates only. No deployment policy has
been selected or copied into this repository.

## Next decision sequence

1. Diagnose the home/calibration-alignment failure using the frozen T237
   traces and CPU-only counterfactuals.
2. Preregister a successor only if that diagnosis identifies a falsifiable
   mechanism; do not retrain or rerun T237.
3. Only after a successor passes the full offline gate may it proceed to a
   deployment-contract audit and produce the minimal runtime-v2 handoff:
   graph receipts, ABI manifest, state/reset semantics, command-route contract,
   frozen observation golden vectors, and rollback information.
4. Gate 5 remains separately authorized hardware work.

No robot, X5, serial, GPIO/I2C, torque, motion, policy deployment, or Gate 5
action is authorized by this handoff.
