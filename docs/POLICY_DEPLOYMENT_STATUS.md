# Policy Deployment Status

Status date: 2026-08-01

## Current state

`T247 READY FOR AN EXPLICIT SUSPENDED GATE-5 x=0 AUTHORIZATION; NOT RUN`

The policy-search and runtime-integration work are green. T247 is still the
unchanged winner; T250/T251 were evidence and integration labels, not newer
policies. No policy binary has been staged on the X5 and Hardware Gate 5 has
not run.

## What is green

| Layer | Evidence |
| --- | --- |
| Offline behavior | T249B: 20/20 robustness conditions and 320/320 cells pass |
| Policy/runtime contract | T250 exact two-stage 115-D/14-action integration passes |
| X5 policy compute | Exact x=0 and x=.08 routes pass 35/35 with zero rate excess |
| Production host wiring | 18/18 mock real-asset checks pass, including pause and injected-write failure |
| Independent summary | T247 stage, route, ABI, asset, duration, and safety validation passes |
| Robot runtime | Hardware Gates 1-4 are `PASS_REVIEWED` |
| Gate 5 launcher | Frozen one-arm launcher validates all hashes and restores the governor on every exit |

The measured X5 policy-host timing is comfortably inside its separately frozen
compute reserve:

| Route | p99 | p99.9 | max | Limits |
| --- | ---: | ---: | ---: | ---: |
| x=0 | 0.786446 ms | 1.178854 ms | 1.409879 ms | 1.8 / 2.5 / 4.0 ms |
| x=.08 | 1.606359 ms | 1.937126 ms | 1.944338 ms | 1.8 / 2.5 / 4.0 ms |

The Windows mock host produced slow mock tick and bus timing because its sleep
resolution quantized the fake bus delay. That summary is explicitly
`INFORMATIONAL_ONLY`; it does not override the green X5 measurements or claim a
hardware timing result.

## Exact remaining sequence

1. Receive explicit authorization for the suspended T247 x=0 Gate 5 run.
2. Stage the hash-frozen source and external policy assets on the X5 without
   running them.
3. With the robot securely supported and the Xbox controller connected, run
   one launcher invocation for x=0: 250 calibration ticks plus 600 replay
   ticks.
4. Independently summarize and review that artifact.
5. Only a reviewed green x=0 result can earn a separate x=.08 authorization.

The launcher cannot start x=.08 after x=0. Its x=.08 path requires both a
separate authorization and the exact SHA-256 of a reviewed green x=0 receipt.

## Still not proven

- No serial T247 policy replay has run.
- The physical Xbox pause mapping has not been exercised by this candidate.
- T247 does not have grounded-walking clearance.
- A readiness result does not authorize torque, motion, Gate 5, or grounded
  replay by itself.

The frozen readiness and command packet are in
`artifacts/gates/phase_7_hardware/gate_5_policy/`.
