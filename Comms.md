# Active Runtime <-> Policy Handoff

This file is the short current handoff. Historical exchanges remain in
[`docs/archive/COMMS_HISTORY_THROUGH_20260722.md`](docs/archive/COMMS_HISTORY_THROUGH_20260722.md).

## Current decision

Status: `T247_OFFLINE_GREEN - X5_THREAD_CPU_ATTRIBUTION_RUNNER_IMPLEMENTED - GATE_5_BLOCKED`

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
at `0.211167 ms` median. T251A5 changed only that target boundary in a separate,
default-disabled host. Its real-asset CPU contract is byte-exact for all
`2,298` ticks, preserves one exact handoff and zero rate excess, and makes the
bound offset array immutable. A balanced `20,000`-sample local microbenchmark
measured a corrected/predecessor median ratio of `0.641026`, clearing the
preregistered `<= 0.75` requirement.

That result earned exactly one no-device X5 target screen at the unchanged
`1.8/2.5/4.0 ms` p99/p99.9/max reserve. It ran once without any robot interface.
All `2,298` semantic ticks remained byte-exact, the T247 trace was unchanged,
offset/target invariants passed, and p99.9 `2.396691 ms` plus max `2.701923 ms`
passed. Only p99 `2.011089 ms` missed the frozen `1.8 ms` reserve, so the target
correction is closed without a rerun and T251B remains unearned. The board CPU
governor restored exactly to `schedutil`.

After excluding immutable ONNX and the closed graph-host and target components,
the next largest unchanged measured host component is observation assembly at
`0.179042 ms` median. T251A6 tested one preregistered observation-only correction
locally. It preserved every value and the complete `2,298`-tick recurrent trace,
including mutated in-place sensor sources, but its balanced `20,000`-sample
microbenchmark measured `1.027778x` the predecessor median rather than the
required `<= 0.75x`. The observation correction is therefore closed as too
small, and no X5 execution was earned or performed.

The next measured component, transaction residual at `0.087543 ms` median,
was tested in T251A7 with one preregistered default-disabled correction. Its
full real-asset chain remained byte-exact for all `2,298` ticks, including one
handoff, zero rate excess, seven exact fallback-diagnostic cases, and six exact
fault-boundary cases. The balanced `20,000`-sample transaction-shell benchmark
improved from `0.0042 ms` to `0.0034 ms` median, but the `0.809524x` ratio did
not meet the unchanged `<= 0.75x` materiality requirement. The correction is
therefore closed as too small, and no X5 execution was earned or performed.

The final independently measured eligible component, observer staging at
`0.045501 ms` median, was tested in T251A8. Its full real-asset chain remained
byte-exact for all `2,298` ticks with exact calibration/handoff/P30 state and
zero rate excess. Its stage-only median improved from `0.0027 ms` to `0.0021
ms`, but the `0.777778x` ratio missed the unchanged `<= 0.75x` materiality bar.
Stage-plus-commit remained inside its non-regression bound at `1.037267x`.
The correction is closed, and no X5 execution was earned or performed.

All independently measured Python host components were therefore either
materially corrected and screened or falsified locally. A read-only graph
audit then selected exact post-calibration context-route specialization: the
64-D context is immutable after handoff, so six complete route-specific graph
closures can be derived without changing T247 weights, numerics, recurrence,
or ABI. The local CPU contract passed `14/14` checks across all six routes,
including threshold neighborhoods, `3,072` one-step cases, and the complete
`2,298`-tick chain.

The corrected no-device X5 screen ran under verified `SCHED_FIFO` 80 on
isolated CPU 7 with the performance governor. T247 and the selected
`lower-cond0` specialized graph were byte-exact for all `2,298` ticks, the
action trace remained `6af1f952...20bd3`, rate excess was zero, and no robot
interface opened. Stage p50/p95/p99/p99.9/max were
`1.602483/1.703418/2.097216/2.267942/2.285213 ms`. Thus p99 alone missed the
unchanged `1.8/2.5/4.0 ms` reserve. Per preregistration, context-route
specialization is closed with no retry and no threshold change; T247 itself
remains the frozen offline-green policy.

The preserved raw population has `53/2,048` ticks over `1.8 ms`: eight recur
at roughly 250/251-tick spacing, 35 lie in one 44-tick cluster, and ten are
elsewhere. A read-only board audit found that CPU 7 is excluded with
`isolcpus=7`, but this kernel has no `CONFIG_NO_HZ_FULL`; CPU 7 still records
timer/RCU work and has local kernel workers. Existing evidence does not align
that work to individual slow ticks.

One zero-selection-weight diagnostic is now preregistered: pair wall time with
`CLOCK_THREAD_CPUTIME_ID` around the exact T247 stage call over one paced
250+2,048 chain. This can distinguish scheduled policy compute from time stolen
by interrupts, softirqs, or preemption. It cannot reopen context-route
specialization, rescore the reserve, or change a threshold. Training,
production integration, Hardware Gate 5, torque, and motion remain unearned.

Local validation at this handoff is green: `491` tests pass and the `210`-entry
reviewed-artifact manifest verifies. The required Windows mock probe completed
as informational-only evidence and made no hardware claim.
