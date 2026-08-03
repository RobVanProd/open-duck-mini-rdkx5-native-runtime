# G-series safety gate runbook

This is the short operator path for the remaining G-series work. A completed
offline or suspended gate never authorizes the next gate by itself.

## Current state

| Gate | Scope | State | What it proved |
|---|---|---|---|
| G1 | Controller-only B mapping | `PASS_REVIEWED` | The known Xbox B event is mapped without servo access. |
| G2 | Suspended no-policy home hold + B | `PASS_REVIEWED` | B caused torque-off in 0.197709 ms and all 14 register-40 values read zero. |
| G3-O1 | Offline G3 implementation | `PASS_REVIEWED` | Honest grounded authority, default-off IMU/contact guard, and fault injection are green. |
| G3-S1 | Suspended T247 x=0 guard revalidation | `PREREGISTERED_NOT_RUN` | Nothing yet; it needs a new exact authorization and operator presence. |
| G3 | Grounded T247 x=0 standing | `BLOCKED` | It cannot be prepared or run until G3-S1 passes independent review. |

No robot command is authorized by this document.

## Tomorrow: G3-S1 only

The operator places the robot securely on its stand, clears hands, connects the
known Xbox controller, and confirms B is immediately available. Then provide
this exact authorization:

> I am physically present; the robot is securely supported on its stand, hands
> are clear, and the known-good Xbox controller is connected. I authorize the
> frozen G3-S1 suspended T247 x=0 guard revalidation on /dev/ttyS1: 50
> torque-off guard-readiness samples, five-second home entry, one startup
> readiness exchange, and exactly 850 active policy ticks, followed by the
> independent all-14 register-40 torque-off readback. No grounded motion, no
> x=.08, no walking, and no automatic follow-on.

Only after that exact authorization, run:

```bash
sudo setup/run_g3_s1_suspended_guard_revalidation.sh \
  --source-root /home/sunrise/open-duck-x5-g3-s1 \
  --asset-root /home/sunrise/open-duck-x5-gate5-t247-assets \
  --config /home/sunrise/duck_config.json \
  --imu-calibration /home/sunrise/gate3/sensor-matrix-20260718-readybarrier/calibration/imu_calibration.json \
  --output-dir /home/sunrise/duck-evidence/g3-s1-YYYYMMDD \
  --hardware-authorized --suspended-or-benched --g3-s1-moving-authorized
```

The launcher has one runtime invocation and no configurable command. It refuses
source drift, wrong assets, a dirty tracked worktree, the wrong controller,
missing CPU isolation, a busy serial port, or a pre-existing output directory.
It restores the CPU governor, independently disables and reads torque register
40 on all 14 servos, writes hashes, and never starts another gate.

## G3-S1 review

Do not rely on the launcher exit code alone. Review all of:

1. `candidate-review.json` reports every check true.
2. `summary.json` meets p99 ≤ 21 ms, p99.9 ≤ 22 ms, bus max < 5 ms,
   failure rate < 0.1%, and zero bursts/stale samples/dropped telemetry.
3. `control.jsonl` contains exactly one passing `grounded_readiness`, exactly
   one passing `startup_readiness`, no `grounded_safety_trip`, and guard
   telemetry on every control tick.
4. `torque-off-readback.json` is `PASS` with all 14 register-40 values zero.
5. The operator reports no fall, collision, wrong side/sign, unexpected jerk,
   or concerning sound.
6. Every file matches `sha256sums.txt`.

Any failed item halts G3. There is no retry or automatic parameter change.

## After a reviewed G3-S1 pass

Only then may the repository prepare a single grounded x=0 standing launcher.
That later launcher must use the three honest grounded assertions, reject the
suspended assertion, retain the same 50-sample both-feet readiness and automatic
guard, and require a new exact grounded authorization while the operator is
present. It must still have no x=.08, walking, retry, or automatic follow-on.

The grounded launcher is intentionally absent today.
