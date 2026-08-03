# Policy Deployment Status

Status date: 2026-08-02

## Current state

`T247 SUSPENDED GATE 5 COMPLETE: x=0 AND x=.08 PASS_REVIEWED`

The policy-search and runtime-integration work remain green. T247 is still the
unchanged winner; T250/T251 were evidence and integration labels, not newer
policies. The readiness-cued suspended x=0 arm completed exactly 250 calibration
plus 600 locomotion ticks. Tick p99/p99.9 were 20.058568/20.115872 ms, bus
p99.9/max were 3.836193/3.919508 ms, and all 56,960 transactions succeeded.
There were zero bursts, stale samples, alarms, telemetry drops, or target-rate
envelope events. Runtime and independent register readback confirmed torque
off, independent replay matched the board summary exactly, and the operator
reported that everything looked and sounded normal.

The separately frozen x=.08 arm then completed the same exact 250+600 active
sequence. Tick p99/p99.9 were 20.126557/20.137626 ms, bus p99.9/max were
3.898666/4.008135 ms, and all 46,224 transactions succeeded. There were zero
bursts, stale samples, alarms, telemetry drops, or target-rate envelope events.
The operator reported that it looked and sounded clean. Runtime and independent
register readback again confirmed torque off, and the local independent replay
validated all 2,893 records and reproduced the board summary exactly.

## What is green

| Layer | Evidence |
| --- | --- |
| Offline behavior | T249B: 20/20 robustness conditions and 320/320 cells pass |
| Policy/runtime contract | T250 exact two-stage 115-D/14-action integration passes |
| X5 policy compute | Exact x=0 and x=.08 routes pass 35/35 with zero rate excess |
| Production host wiring | 18/18 mock real-asset checks pass, including pause and injected-write failure |
| Independent summary | T247 stage, route, ABI, asset, duration, and safety validation passes |
| Robot runtime | Hardware Gates 1-4 are `PASS_REVIEWED` |
| Gate 5 x=0 | `PASS_REVIEWED`: exact 250+600 active ticks, all automatic gates green, normal operator observation, torque off independently verified |
| Gate 5 x=.08 | `PASS_REVIEWED`: exact 250+600 active ticks, all 20 summary gates and 15/15 candidate checks green, clean operator observation, torque off independently verified |
| Controller isolation | The known-good Xbox identity passed 10,000/10,000 direct 50 Hz reads, one A edge, zero disconnects, and an unchanged device inode with no UART or servo access |
| Startup repair offline contract | One pre-serial controller drain, a one-shot separately recorded full-shape readiness exchange, bounded fixed-slot anomaly routing, unchanged measured tick population, and fail-closed home/controller checks pass tests |

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

## Completed sequence

The x=0 and x=.08 arms were launched separately under exact authorization.
Each produced one clean readiness `PASS`, ran only after the explicit GO cue,
completed exactly 850 active policy ticks, exited normally, and independently
verified torque off. The reviewed runtime/policy is ready for RDK-X5 handoff.

## Still not proven

- T247 does not have grounded-walking clearance.
- The reviewed suspended results do not authorize another motion run or grounded
  replay by themselves.

The frozen readiness and command packet are in
`artifacts/gates/phase_7_hardware/gate_5_policy/`.
