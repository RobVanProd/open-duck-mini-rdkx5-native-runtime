# CPU Governor Torque-Off A/B Pre-Registration

Status: `NOT_AUTHORIZED_NOT_RUN`

This freezes a one-variable causal test of the remaining exact-collector timing
tail. It does not authorize opening `/dev/ttyS1`.

## Causal claim under test

The reviewed exact-collector run received all 140 bytes before its response
deadline, but its parse tail correlated `-0.953669` with application read-call
count. A lower read-call count means more time blocked in `select()` before the
single Python parse. The X5's only CPU-frequency policy covers CPUs 0-7 and was
configured as `schedutil`, with a 300 MHz minimum and 1.5 GHz maximum. The
isolated 50 Hz control core may therefore wake and parse below maximum
frequency.

The A/B changes only that policy to `performance` for the duration of the
already-reviewed exact-length collector population. It uses the same source,
serial path, packet order, transaction tracing, timeout, telemetry cadence,
RT priority, and 10,000-tick population as
`sync_read_collector_ab/RESULT.md`. The prior `schedutil` run is arm A; this
preregistered run is arm B.

## Frozen setup

- robot support: stand or suspended/benched, reconfirmed immediately before;
- source commit: `8c73aae2110f10a294e1dcf333c41bfc9d2f3a88`;
- source archive SHA-256:
  `a90070d00e8f0eca704005aa241c36e7ab4aa782ca7f8af41253d3d4be41de77`;
- endpoint: `/dev/ttyS1`, 1,000,000 bit/s, 8-N-1;
- exact response collector: 140 bytes before one generic parse;
- wire order: `20,21,22,23,24,30,31,32,33,10,11,12,14,13`;
- exactly 10,000 attempted sweeps at 50 Hz;
- isolated CPU 7, `SCHED_FIFO 80`, initial affinity 0-7;
- one SyncWrite, one all-14 position/speed SyncRead, and one round-robin
  extended read per tick;
- zero amplitude with torque disabled; no config, policy, home entry, or motion;
- transaction trace v2 enabled exactly as in arm A;
- governor precondition: exactly `schedutil` on policy0;
- arm-B governor: exactly `performance` on policy0.

The wrapper must record governor and min/max frequency before the change,
verify `performance` before starting the probe, and restore the exact original
governor in an EXIT/INT/TERM trap after the probe. Restoration and final
torque-off are mandatory even when the probe fails.

## Frozen decisions

The same gates remain in force: complete-sweep sample maximum `<5 ms`, tick
p99 `<=21 ms`, tick p99.9 `<=22 ms`, failures `<0.1%`, zero read bursts, zero
alarms, zero telemetry drops, and final torque-off `ok`.

Arm B supports the governor hypothesis only if it reduces both complete-sweep
mean and p99.9 by at least 0.5 ms relative to arm A and does not worsen the
maximum. Gate 2 clears only if every unchanged gate passes; a relative
improvement is not enough. If arm B fails, stop. Do not run the fixed-frame
parser, remove instrumentation, change timeout/order/telemetry, enable torque,
or relax the bus threshold within this authorization.

## Authorization required

Execution requires a new explicit authorization for this named CPU-governor
torque-off A/B and a fresh confirmation that the robot is on its stand or
suspended/benched. The probe invocation must contain
`--hardware-authorized --suspended-or-benched` and must not contain
`--enable-torque` or `--moving-gate-authorized`.
