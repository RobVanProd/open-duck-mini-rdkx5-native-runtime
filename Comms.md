# Active Runtime <-> Policy Handoff

This file is the short current handoff. Historical exchanges remain in
[`docs/archive/COMMS_HISTORY_THROUGH_20260722.md`](docs/archive/COMMS_HISTORY_THROUGH_20260722.md).

## Current decision

Status: `T250_RUNTIME_INTEGRATION_PASS - T251_X5_CPU_PREFLIGHT_NOT_RUN - GATE_5_BLOCKED`

The selected policy route is now green offline. T249B completed the full
20-condition R2 matrix with `320/320` passing cells across both checkpoints,
both measured actuator fits, and x=`0.0/0.074/0.077/0.080`. T250 then selected
the terminal checkpoint by the frozen maximum-step rule and passed the exact
deployment-contract audit.

The native-runtime repository now contains a separate, default-disabled 115-D
state-coherent host. It does not alter the frozen 101-D production contract and
is not imported by the production runtime. Its real-asset T250 verification
passed `25/25` checks with zero numeric delta for ONNX recurrence, observation
fields, P30 observer state, target/offset handling, calibration context,
boundary action history, phase reset, and measured-rate monitoring.

## Selected assets

| role | step | bytes | SHA-256 |
| --- | ---: | ---: | --- |
| persistence witness | 1,003,520 | 993,875 | `21c714b0cbe30e43233f6a29d6ccfa058c550f28fab3dd836a73a6015b73f8f2` |
| deployment terminal | 2,007,040 | 993,875 | `dadfb446ea7c720f274a15bc65e9171c2e74d715ccfaf58adbb408b6c1365a54` |
| calibrator | n/a | 55,573 | `0f3aebfd9946a6271fdb14adec3d68d556648f270984639d372c973a7d7dc576` |
| fixed P30 runtime observer | n/a | 18,664 | `a58db8ffc505d2bb64cba7f5618d0e2c65904fc9f9ac37b560a1231e090f5f4f` |
| projected reference table | n/a | 259,604 | `8102d9cd139584816d807ca635bcca6d37fa6b3c455848e00395b6d565968212` |

No policy binary is committed to this repository or copied into the production
runtime tree.

## Exact versioned ABI and handoff

```text
calibrator inputs:  obs[1,115], previous_action[1,14], h_in[1,64]
calibrator outputs: calibration_actions[1,14], previous_action_out[1,14], h_out[1,64]

policy inputs:  obs[1,115], previous_action[1,14], h_in[1,64], calibration_context[1,64]
policy outputs: continuous_actions[1,14], previous_action_out[1,14], h_out[1,64]
```

The transition is exactly 250 confirmed calibration ticks and zero home-return
ticks. Physical/observer state and the final three calibration actions survive
the handoff; policy `previous_action` receives the calibrator's final
`previous_action_out`; policy hidden state resets to zero; final calibrator
`h_out` becomes immutable context; locomotion phase resets to `[1,0]`.

## Current next step

T251 is frozen and ready: an isolated, no-motion X5 CPU preflight with 250
calibration ticks plus 10,000 synthetic locomotion host ticks under verified
single-CPU `SCHED_FIFO` and the `performance` governor. Its compute-only limits
are p99 <= 2.0 ms, p99.9 <= 3.0 ms, and max <= 5.0 ms.

The X5 at `192.168.1.50` was unreachable when execution was attempted, so T251
is honestly `NOT_RUN`. A T251 pass earns only opt-in production-integration
preregistration. Production integration, policy staging, Hardware Gate 5,
torque, and motion remain unearned and unrun.

Local validation at the current handoff is green: `400` tests pass and the
`170`-entry artifact manifest verifies.
