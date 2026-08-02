# Policy Deployment Status

Status date: 2026-08-02

## Current state

`T247 GATE-5 x=0 ATTEMPT 1 HALTED BEFORE POLICY; TORQUE-OFF REPAIR PREFLIGHT NEXT`

The policy-search and runtime-integration work remain green. T247 is still the
unchanged winner; T250/T251 were evidence and integration labels, not newer
policies. The first authorized x=0 invocation entered and held home, but halted
while paused on a 92.776 ms watchdog overrun. It executed zero active policy
ticks, confirmed torque-off, released the UART, and restored the governor.

The late transaction began 17.58 ms after the kernel created a replacement
Xbox Bluetooth HID instance. The Linux controller implementation used pygame
in a second Python thread, so hotplug processing could hold the interpreter
lock and starve the RT servo thread. The same code also accepted bytes after
the four-millisecond deadline and labeled the 90.701 ms grouped read `OK`.

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
| Controller isolation | The known-good Xbox identity passed 10,000/10,000 direct 50 Hz reads, one A edge, zero disconnects, and an unchanged device inode with no UART or servo access |

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

1. Run the preregistered controller-present 10,000-tick torque-off timing probe.
2. Only if it passes, freeze and review a replacement x=0 launcher.
4. Obtain fresh explicit authorization for that exact suspended retry.
5. Independently summarize and review the x=0 artifact.
6. Only a reviewed green x=0 result can earn a separate x=.08 authorization.

The launcher cannot start x=.08 after x=0. Its x=.08 path requires both a
separate authorization and the exact SHA-256 of a reviewed green x=0 receipt.

## Still not proven

- No active serial T247 policy tick has run.
- The controller-isolation repair has not yet passed while sharing the process
  with the real torque-off serial transaction loop.
- T247 does not have grounded-walking clearance.
- A readiness result does not authorize torque, motion, Gate 5, or grounded
  replay by itself.

The frozen readiness and command packet are in
`artifacts/gates/phase_7_hardware/gate_5_policy/`.
