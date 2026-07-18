# Direct UART 10,000-Tick Torque-Off A/B Pre-Registration

Status before execution: `AUTHORIZED_NOT_RUN`

This freezes the direct-UART comparison before `/dev/ttyS1` is opened. It is a
transport A/B against the completed USB sample, not Gate 2 motion clearance.
Rob confirmed on 2026-07-18 that the robot is on its stand and directed the
torque-off comparison to continue.

## Frozen setup

- endpoint: `/dev/ttyS1`, X5 UART1 on physical pins 8/10;
- Linux driver: `dw-apb-uart` at `34070000.serial`;
- USB serial adapter: absent;
- adapter control mode: UART position A, as physically set by Rob;
- baud and framing: 1,000,000 bit/s, 8 data bits, no parity, 1 stop bit;
- wire SyncRead order: frozen logical IDs routed from wire order ending 14,13;
- scheduler: initial affinity 0-7, housekeeping 0-6, isolated CPU 7 under
  `SCHED_FIFO 80`;
- rate/window: exactly 10,000 attempted ticks at 50 Hz;
- timeout/watchdog: 4 ms transaction timeout and two consecutive failed sweeps;
- target: configured home with amplitude exactly 0 rad; and
- policy, gain write, home move, and torque enable: prohibited.

The guarded startup must broadcast torque-off before verification. If all 14
fresh replies are not received, the probe stops and attempts final torque-off;
the 10,000-tick population does not begin. During a valid run, the normal
all-14 goal SyncWrite is emitted only while torque remains disabled so the
population matches USB and the future runtime.

## Frozen populations

The comparison reuses the USB definitions exactly:

- `bus_total_ms`: one all-14 goal SyncWrite, one `0x82` all-14 position/speed
  response burst, and one round-robin extended read per completed tick;
- `group_round_trip_ms`: one `0x82` request plus the complete contiguous
  14-response burst; and
- `max`, p99, and p99.9: sample statistics over exactly the completed 10,000-tick
  population.

A shorter wiring check cannot decide the A/B. If startup succeeds but the run
halts before 10,000 records, the artifact is incomplete and no comparison is
made.

## Frozen outputs and decision rule

Record the same summary fields, application transaction stages, raw hashes,
source/config hashes, RT partition, device-alarm counts, transport taxonomy,
cutoff status, and record counts as the USB run. Compare UART versus USB without
changing the `<5 ms` complete-sweep gate.

UART clears the transport blocker only if the evidence is complete and
`bus_total_ms.max < 5 ms`, alongside tick p99 <=21 ms, tick p99.9 <=22 ms,
transaction failures <0.1%, zero read bursts, and final torque-off `ok`.
Device alarms remain a separate failing safety gate and cannot be converted to
transport failures or ignored. Passing this torque-off A/B still does not
authorize torque, motion, policy inference, or a later gate.

## Required invocation assertions

Rob has confirmed the physical support state and authorized this exact scope.
The command must include both
`--hardware-authorized --suspended-or-benched`, must not include
`--enable-torque` or `--moving-gate-authorized`, and must name `/dev/ttyS1`.
