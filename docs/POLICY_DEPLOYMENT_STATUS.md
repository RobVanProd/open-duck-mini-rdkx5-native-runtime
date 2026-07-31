# Policy Deployment Status

Status date: 2026-07-31

## Executive status

`OFFLINE_POLICY_GREEN - RUNTIME_INTEGRATION_GREEN - X5_OPTIMIZED_SCREEN_HOLD_RESERVE - GATE_5_NOT_RUN`

We are no longer searching for a policy mechanism. The T247 terminal candidate
passed the complete T249B offline robustness matrix, and T250 proved that the
new default-disabled RDK host reproduces its exact two-stage state contract.
The remaining work is deployment engineering and X5 evidence, not another
training run.

## Evidence summary

| Gate | Result |
| --- | --- |
| T249B full sequential R2 | `20/20 conditions; 320/320 cells PASS` |
| T250 policy deployment-contract audit | `PASS` |
| T250 native-runtime real-asset integration | `25/25 PASS; all numeric deltas 0` |
| T251 no-motion X5 CPU preflight | `HOLD; 15/18 checks PASS; all 3 latency checks FAIL` |
| T251A compute attribution | `PASS; unpaced RT throttling and steady host overhead attributed` |
| T251A2 optimized paced screen | `HOLD; 13/15 checks PASS; byte-exact; p99/p99.9 reserve FAIL` |
| Opt-in production runtime integration | `NOT_PREREGISTERED; waits for T251` |
| Hardware Gate 5 | `NOT_RUN` |

T250 runtime-integration result canonical SHA-256:
`09f794ae312a2acc172db0d4d06e6aa7205131276fa030cec9291f51fd6dede9`

T250 runtime-integration result file SHA-256:
`2261673c26cc8c0ec364967fd20f9437b982796322d54f0beb2b91c44f2abcc0`

T251 preregistration file SHA-256:
`7593cd1a87733fcf469a7c9d68f2aa0361456b32a24fa70c49a5109a3b3ed138`

T251 result canonical SHA-256:
`3e78002a6b1fb23e38881a0813a153678eaf1f53003ae613cf5a4ef9c5ba875c`

T251 result file SHA-256:
`db5a038d3a0eee1155740276abef5e14a8044ac106a16b44198532b3f17bc01c`

T251A2 result canonical SHA-256:
`291daa5f92f49930d9094ac5aaa31db4b6b01a460aebccafbab09044bf9713e5`

T251A2 result file SHA-256:
`dcc1472d5a98127b5c8434363e14eb1e879af6d63c40a8933e08d0c7ed1f7fc8`

## What is proven

- The policy persists across both frozen checkpoints and both measured
  actuator fits over all 20 offline conditions.
- The deployment checkpoint was selected by the frozen terminal-step rule,
  not by cherry-picking a metric.
- The exact calibrator/policy ABI, 250/0 handoff, 115 observation fields,
  P30 observer, action history, phase reset, immutable context, soft offsets,
  and target-rate monitor agree on CPU.
- The frozen 101-D runtime remains unchanged and default production behavior
  does not import or enable the new host.
- The exact T247 assets and T250 state-coherent host execute on a single
  isolated X5 CPU under verified `SCHED_FIFO`/`performance` setup without
  importing or opening any robot interface. All 15 non-timing T251 checks
  passed, including exact 250/0/10,000 tick counts, finite state, immutable
  context, and zero measured target-rate excess.
- T251A2's optimized host remained byte-exact to the original host for all
  2,298 paced ticks. It imported and opened no robot interface, restored the
  governor, and had zero measured target-rate excess.
- Repository validation is green: `423` tests and all `177` reviewed artifact
  hashes pass.

## What is not proven

- The corrected X5 host has not earned the 10,000-tick gate. T251A2 measured
  p99 `2.179714 ms`, p99.9 `2.545636 ms`, and max `2.620463 ms` against its
  stricter reserved screen limits of `1.8/2.5/4.0 ms`; p99 and p99.9 failed.
- The new host is not connected to the live sensor/bus/safety loop.
- No policy asset has been staged in the production runtime tree.
- No Gate 5 policy replay, torque-enabled policy execution, or grounded replay
  has occurred.

## Advance rule

Preserve T251 and T251A2. Preregister one single-optimized-host/component
attribution run to separate paired-session cache pressure from the remaining
observation, graph-validation, and target-pipeline costs. Change only the
measured component, then require a new reserved screen before T251B can be
preregistered. No threshold changes or blind reruns are permitted. Production
integration and Hardware Gate 5 remain blocked.
