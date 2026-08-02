# Policy Deployment Status

Status date: 2026-08-01

## Executive status

`OFFLINE_POLICY_GREEN - RUNTIME_INTEGRATION_GREEN - X5_COMMAND_ROUTE_PACKAGE_SEALED - GATE_5_NOT_RUN`

T247 remains the frozen policy winner. It passed the complete T249B offline
robustness matrix, and T250 proved that the default-disabled RDK host reproduces
its exact two-stage state contract. The current blocker is a strict deployment
reserve on X5 policy-host p99, not policy behavior, servo timing, kernel jitter,
or a request for more training. An exact command-route specialization has now
passed its CPU contract and earned one sealed no-device X5 screen.

## Evidence summary

| Gate | Result |
| --- | --- |
| T249B full sequential R2 | `20/20 conditions; 320/320 cells PASS` |
| T250 policy deployment contract | `PASS` |
| T250 native-runtime real-asset integration | `25/25 PASS; all numeric deltas 0` |
| T247 context-route X5 screen | `27/28; exact outputs; HOLD on p99 only` |
| T247 wall-vs-thread CPU attribution | `24/24; SCHEDULED_COMPUTE_DOMINANT` |
| Static calibration-context partial evaluation | `exact, but CLOSED_TOO_SMALL; no X5 run earned` |
| Exact context/command route CPU contract | `15/15 PASS; 24 variants; worst p50/p99 ratio .8735/.8780` |
| Exact command-route X5 screen | `EXECUTION PACKAGE SEALED; NOT_RUN` |
| Opt-in production runtime integration | `NOT_PREREGISTERED` |
| Hardware Gate 5 | `NOT_RUN` |

## Current measured result

The no-device attribution ran the exact frozen T247 lower-cond0 route for 250
calibration ticks and 2,048 locomotion ticks on isolated CPU 7 under
`SCHED_FIFO` priority 80 and the temporary `performance` governor.

| Metric | Wall time | Thread CPU time | Unscheduled/stolen time |
| --- | ---: | ---: | ---: |
| p50 | 1.558235 ms | 1.553064 ms | 0.005256 ms |
| p95 | 1.708950 ms | 1.703243 ms | 0.007881 ms |
| p99 | 2.112700 ms | 2.108831 ms | 0.009717 ms |
| p99.9 | 2.390626 ms | 2.389529 ms | 0.013950 ms |
| max | 2.489467 ms | 2.478875 ms | 0.017091 ms |

Forty-six of 47 wall-slow ticks were also thread-CPU-slow. That is the
preregistered signature of scheduled computation, not time stolen by the kernel
or scheduler. Kernel-housekeeping changes are therefore not selected.

The run passed all 24 checks, reproduced the frozen action trace exactly, had
zero target-rate excess, restored the governor, and opened no robot interface.
It did not read sensors or servos, enable torque, move the robot, deploy a
policy, or authorize Gate 5.

Board result file SHA-256:
`c9ca65799e25072633ab51ca0e2f73cbd15ef98c6f612b072e6e911ae2f7d9b7`

Raw tick arrays SHA-256:
`a7f25d75605bcd4e1cdaa0ee1b4ed0ed9f954bf3bacc2235baddc274d75b608d`

## Follow-on audit

The attribution selected a read-only static calibration-context
partial-evaluation audit. The existing route specialization had already removed
the large conditional path. Only five context-only nodes and one boolean branch
remained. Folding that frozen branch removed seven nodes while preserving every
tested output byte-for-byte.

The local 20,000-sample alternating benchmark reduced p50 by 5.42% and p99 by
6.14%. Both miss the inherited 12% materiality floor, while the measured X5 p99
would need a 14.80% reduction to reach the unchanged 1.8 ms reserve. The
mechanism is therefore closed without an X5 run, retry, or threshold change.

The next graph audit found a larger exact mechanism. After the immutable
calibration context chooses one of six context routes, the four frozen command
values (`0`, `.074`, `.077`, `.080`) each make several eager branches
unreachable. The deterministic deriver generates 24 command subroutes and
retains the original selected-context graph as fallback for every other valid
command, so command support is not narrowed.

The formal CPU contract passed all 15 checks: two derivations were byte-exact;
all 24 ONNX models, ABIs, and retained initializers passed; 6,144 one-step cases,
7,920 recurrent route-switch ticks, 2,160 fallback ticks, and four complete
2,298-tick chains were byte-exact with zero rate excess. Across 20,000
alternating samples per variant, the worst p50 and p99 ratios were `.873508`
and `.878014` against the unchanged `.88` limit.

## What is proven

- T247 is offline green at both frozen checkpoints over all 320 R2 cells.
- T250 reproduces the policy ABI and state contract exactly in the native
  runtime host.
- T247's lower-cond0 route is action-trace exact on X5 with zero rate excess.
- The remaining X5 p99 tail is policy computation time; scheduler/kernel stolen
  time is too small to explain it.
- Constant-context folding is exact but too small to earn a board execution.
- Exact command-route specialization preserves all frozen outputs and fallback
  behavior while clearing the local materiality gate across all 24 variants.
- Repository validation is green at `497` tests and `218` reviewed artifact
  hashes after this evidence update.

## What is not proven

- The policy host has not met its strict 1.8 ms p99 deployment reserve.
- The new host is not connected to the live sensor, bus, or safety loop.
- No policy asset has been staged in the production runtime tree.
- No Gate 5 policy replay, torque-enabled policy execution, or grounded replay
  has occurred.

## Advance rule

Preserve T247 and all completed X5 evidence. Seal and run exactly one no-device
X5 screen containing the x=0 and x=.08 command routes. Both arms must remain
byte-exact and independently pass p99/p99.9/max at `1.8/2.5/4.0 ms`. A valid
miss permanently closes this mechanism; a pass earns only the opt-in production
host contract and Gate-5 readiness audit. No threshold change, policy training,
robot interface, torque, motion, production integration, or Gate 5 execution is
authorized by the CPU result.
