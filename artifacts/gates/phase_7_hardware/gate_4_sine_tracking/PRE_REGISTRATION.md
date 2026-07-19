# Gate 4 pre-registration — left hip yaw sine tracking

Status: `FROZEN_OFFLINE_NOT_AUTHORIZED_FOR_EXECUTION`

This package freezes the complete Gate 4 population before any moving result is
observed. It does not clear or execute hardware. A fresh, exact moving-test
authorization is required after the source archive and launcher hashes are
published and CI is green.

## Physical scope

- Supported/benched robot only; hands clear before the launcher starts.
- UART `/dev/ttyS1`, 1,000,000 baud.
- No policy or ONNX inference.
- One moving joint only: logical `left_hip_yaw`, servo ID 20.
- The other 13 targets remain at the frozen physical home pose, including the
  reviewed `duck_config.json` offsets.
- Five-second measured-position-to-home entry at low startup gains before each
  moving population.
- Sine amplitude: exactly `0.03 rad`.
- Frequency order: exactly `0.25 Hz`, then `0.5 Hz` only if the first population
  independently passes.
- Peak commanded sine rates are `0.047124 rad/s` and `0.094248 rad/s`.
- Torque off at the end of every probe, signal, exception, watchdog trip, or
  launcher halt.

## Frozen populations

The launcher accepts paths and acknowledgements only. Device, baud, joint,
frequency, amplitude, duration, scheduler, watchdog, and ordering have no CLI
override.

1. `preflight`: 10,000 ticks at 50 Hz, amplitude zero, torque never enabled.
2. `sine_0_25`: 10,000 ticks at 50 Hz, 0.03 rad at 0.25 Hz. This covers exactly
   50 cycles over 200 seconds.
3. `sine_0_5`: 10,000 ticks at 50 Hz, 0.03 rad at 0.5 Hz. This covers exactly
   100 cycles over 200 seconds and is blocked unless stage 2 passes.

All three stages require isolated CPU 7, `SCHED_FIFO` priority 80, and the
performance governor. The launcher verifies an initial `schedutil` governor and
restores it on every exit path.

## Advancement thresholds

Each moving population must meet all thresholds simultaneously:

- tracking absolute error p95 `<= 0.011 rad` over all 10,000 selected-joint
  samples;
- tick period p99 `<= 21 ms`;
- tick period p99.9 `<= 22 ms`;
- complete tick-sweep maximum `< 5 ms`;
- transaction failure rate `< 0.1%`;
- zero grouped-read bursts;
- zero device/voltage alarms, partial data, unexpected packets, telemetry drops,
  or missing selected-joint tracking samples;
- complete record stream and confirmed final torque-off.

The independent validator rehashes the JSONL, checks every tick number and
monotonic timestamp, reconstructs the exact 14-target waveform from the frozen
config, recomputes per-row tracking errors and the gate-setting percentiles, and
checks the source/config/runtime provenance. Summary booleans alone cannot pass.

## Stop rules

- Any failed preflight blocks all motion.
- Any failed 0.25 Hz probe or independent validation blocks 0.5 Hz.
- A hard tick overrun, two consecutive failed bus ticks, any servo alarm,
  telemetry failure, signal, or exception halts the active stage and reaches the
  torque-off cleanup path.
- Unexpected physical motion, a wrong joint/side/sign, loss of support, or an
  operator concern requires immediate interruption; the artifact remains a halt.
- The launcher returns only `REVIEW_CANDIDATE`. Human review is required before
  Gate 4 can become `PASS_REVIEWED`.

## Frozen identities

These values are filled only after the implementation commit is archived twice
with matching SHA-256 and the launcher is frozen in a separate commit:

- source commit: `__GATE4_SOURCE_COMMIT__`
- source archive SHA-256: `__GATE4_ARCHIVE_SHA256__`
- config SHA-256: `131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b`
- launcher: `setup/run_gate4_sine_tracking.sh`
- validator: `src/open_duck_x5/gate4_validation.py`

## Required execution authorization after freeze

The offline approval that selected `left_hip_yaw` does not execute this gate.
After hashes and CI are published, Rob must be physically present and explicitly
authorize this exact supported moving sequence: torque-off preflight, 0.25 Hz,
then 0.5 Hz only after a pass. No policy and no grounded motion are in scope.
