# Active Runtime <-> Policy Handoff

This file is the short current handoff. Historical exchanges remain in
[`docs/archive/COMMS_HISTORY_THROUGH_20260722.md`](docs/archive/COMMS_HISTORY_THROUGH_20260722.md).

## Current decision

Status: `T247_OFFLINE_GREEN - T251A4_X5_RESERVED_SCREEN_HOLD_P99 - GATE_5_BLOCKED`

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

T251A proved that T251's approximately `55 ms` tail was Linux RT-bandwidth
throttling caused by an unpaced diagnostic, not the policy, Python GC, or the
real 20 ms loop. It also isolated the steady miss to Python host work while the
exact ONNX graph remained below the frozen p99 limit.

T251A2 then ran the default-off optimized host at real 20 ms releases. All
2,298 ticks were byte-exact to the T250 host with zero rate excess and no robot
interfaces. Its max passed the reserved screen, but p99 `2.179714 ms` and
p99.9 `2.545636 ms` missed the preregistered `1.8/2.5/4.0 ms` reserve limits.
The canonical result SHA-256 is
`291daa5f92f49930d9094ac5aaa31db4b6b01a460aebccafbab09044bf9713e5`.
Therefore T251B is not earned.

T251A3 completed on the X5 and separated the immutable ONNX call from Python
host work. The single-host action trace remained exact, the governor restored,
and no robot interface was opened. The largest eligible non-ONNX component was
the graph host at `0.232334 ms` median. Its uninstrumented stage remained over
the reference reserve at p99 `2.326800 ms` and p99.9 `2.718311 ms`.

T251A4 therefore changed only that measured boundary in a separate,
default-disabled host: the assembler writes into the active graph's already
bound observation input, current action remains validated before target
generation, and the full action/recurrent-state chain remains validated after
a confirmed send and before state commit. The real-asset CPU contract is green
for all `2,298` ticks, one exact handoff, and zero rate excess; the frozen T247
policy and every observation/action/target semantic are unchanged.

The one no-device T251A4 X5 screen completed without a rerun. Its semantic arm
passed every `2,298` tick byte comparison, reproduced the exact frozen action
trace, showed zero rate excess, and opened no robot interface. The corrected
single host passed p99.9 at `2.441701 ms` and max at `2.517046 ms`, but p99
`2.039060 ms` missed the unchanged `1.8 ms` reserve. The graph-host correction
is therefore closed and T251B remains unearned.

The correction was still material: versus T251A3, p50 fell by `0.140313 ms`
and p99 by `0.287740 ms`. With immutable ONNX and the closed graph-host work
excluded, the next largest unchanged measured component is target construction
at `0.211167 ms` median. The only earned next work is a local CPU contract for
one target-only, default-disabled correction. It cannot run on the X5 until
that contract independently passes. Thresholds remain frozen; production
integration, policy staging, Hardware Gate 5, torque, and motion remain
unearned and unrun.

Local validation at this handoff is green: `443` tests pass and the `184`-entry
reviewed-artifact manifest verifies.
