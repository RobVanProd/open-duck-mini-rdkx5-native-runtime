# Hardware Gate 2 Pre-Registration

Status: `SUPERSEDED_NOT_EXECUTABLE`

This historical pre-registration froze the original USB/source-`9cd4ca0`
attempt. That attempt stopped at torque-off preflight and never enabled torque.
Its authorization is not carried forward to the direct-UART,
performance-governed protocol. The current unexecuted specification is
`GATE2_HOME_HOLD_EXECUTION_PRE_REGISTRATION.md` and requires a new explicit
authorization.

Rob explicitly authorized the suspended/benched all-14 home-pose hold with no
policy on 2026-07-15. This authorization does not extend to Gate 3, Gate 4,
Gate 5, grounded operation, or policy inference.

## Frozen inputs and command

- source commit: `9cd4ca0`
- deployed source archive SHA-256:
  `7e41efeee1aeee562ae53111f22cc6fec044681db82d126e6f9a6c40eb894c16`
- board config: `/home/sunrise/duck_config.json`
- board config SHA-256:
  `131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b`
- serial device/baud: `/dev/ttyACM0` at 1,000,000 bit/s
- RT configuration: isolated CPU 7, `SCHED_FIFO 80`, housekeeping CPUs 0-6
- home entry: five seconds, low startup gain, from fresh measured positions
- hold: 10,000 ticks at 50 Hz, amplitude exactly `0 rad`, no inference
- transaction timeout: 4 ms
- consecutive-failure watchdog: 2 ticks
- output collection ID: `gate2-all14-home-20260715`

The exact probe invocation must include `--require-realtime`,
`--enable-torque`, `--moving-gate-authorized`, `--hardware-authorized`, and
`--suspended-or-benched`.

## Pre-registered pass conditions

All conditions must be true simultaneously:

- all 14 frozen servo IDs are fresh before torque enable;
- complete 10,000-record stream with zero telemetry drops;
- tick p99 at most 21 ms and p99.9 at most 22 ms;
- total bus time max below 5 ms;
- transaction failure rate below 0.1%;
- zero read-failure bursts and no partial/unexpected packets;
- verified RT thread partition in the summary;
- final torque-off status `ok` and no halt reason.

The run stops and attempts torque-off on a signal, stale state, writer failure,
two consecutive failed exchanges, any work/tick overrun above 40 ms, or any
startup/home error. Unexpected physical motion, wrong side/sign/joint, or
operator concern requires immediate external power cutoff.

Passing produces only a review candidate. Failure stops phase advancement. A
timing failure with RT provenance green triggers review of the pre-registered
Python-to-Rust servo-transaction escalation; no later gate is authorized.

## Causal preflight amendment

The first 50-tick torque-off preflight stopped phase advancement before any
torque enable: four grouped-read CRC failures all belonged to servo 13. A
subsequent 2,000-read individual torque-off probe of servo 13 had zero failures.
A guarded order diagnostic then reproduced CRCs when 13 preceded 14 and produced
zero CRCs when 14 preceded 13. Rob confirmed the known physical-chain behavior:
servo 13 must be requested last.

Commit `9cd4ca0` therefore changes only the wire-level SyncRead request order to
end `..., 14, 13`. The frozen logical/action order, servo mapping, thresholds,
duration, home target, and every other pre-registered condition remain
unchanged. The complete torque-off preflight must be repeated before torque can
be enabled.
