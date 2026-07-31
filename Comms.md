# Active Runtime ↔ Policy Handoff

This file is the short current handoff. The accumulated historical exchange is
preserved in
[`docs/archive/COMMS_HISTORY_THROUGH_20260722.md`](docs/archive/COMMS_HISTORY_THROUGH_20260722.md).

## Current decision

Status: `T237_FULL_R2_IN_PROGRESS — GATE_5_BLOCKED`

The selected offline candidate is the T234B exact low-command route. It keeps
each checkpoint's own policy head at `x=0.0`, `0.077`, and `0.080`, and uses
the paired final checkpoint's head only at the exact float32 command
`x=0.074`. This is a uniform deterministic graph transform, not checkpoint
cherry-picking.

Evidence already green:

- T234B ONNX/ABI and bit-exact route contract;
- T235 fresh nominal matrix: `16/16`;
- T236 fresh former-blocker upper-Z matrix: `16/16`; and
- T237 full R2 restart: `5/20` complete conditions, `80/80` completed cells
  green as of 2026-07-30.

The complete T237 decision still requires all `20 × 16 = 320` cells. Both
checkpoints, both measured actuator fits, and commands
`0.0/0.074/0.077/0.080` remain mandatory. The sequence stops at the first
complete failed condition. No retry is allowed.

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

1. Complete T237 sequential full R2.
2. If and only if T237 passes all 20 conditions, preregister and run T238
   offline deployment-contract audit.
3. If and only if T238 passes, produce the minimal runtime-v2 handoff packet:
   graph receipts, ABI manifest, state/reset semantics, command-route contract,
   frozen observation golden vectors, and rollback information.
4. Gate 5 remains separately authorized hardware work.

No robot, X5, serial, GPIO/I2C, torque, motion, policy deployment, or Gate 5
action is authorized by this handoff.
