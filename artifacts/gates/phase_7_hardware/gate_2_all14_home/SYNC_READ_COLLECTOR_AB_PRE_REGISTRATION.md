# Exact-Length SyncRead Collector Torque-Off A/B Pre-Registration

Status after review: `EXECUTED_REVIEWED_FAIL_BUS_BUDGET`

This freezes the first hardware evaluation of the Python exact-length response
collector. It tests the identified application receive mechanism against the
completed direct-UART baseline; it is not Gate 2 motion clearance and does not
authorize opening the serial device.

## Causal claim under test

At one megabit per second, the state SyncRead requests four bytes from fourteen
servos. Each fixed status packet is ten bytes, so the expected response train is
exactly 140 bytes. Feetech specifies that replies follow the ID order in the
request, and the reviewed physical order remains
`20,21,22,23,24,30,31,32,33,10,11,12,14,13`.

The direct-UART baseline received the exact expected kernel byte volume while
the old application collector reported late logical failures on IDs 11-14. The
candidate changes only response collection:

- receive the normal 140-byte train into one preallocated buffer before parsing;
- start the fixed four-millisecond response deadline after the request write;
- parse the normal response train once;
- enter bounded recovery only for unexpected, duplicate, missing, corrupt, or
  partial input; and
- preserve ID routing, staleness, device alarms, telemetry cadence, logical
  order, and all frozen timing gates.

## Frozen setup and population

- robot support: stand or suspended/benched, reconfirmed immediately before run;
- endpoint: `/dev/ttyS1`, X5 UART1 through the already-installed Waveshare UART
  connection; no USB serial adapter;
- baud/framing: 1,000,000 bit/s, 8-N-1;
- scheduler: isolated CPU 7, `SCHED_FIFO 80`, housekeeping CPUs 0-6;
- population: exactly 10,000 attempted complete sweeps at 50 Hz;
- timeout/watchdog: unchanged four-millisecond response timeout and two
  consecutive failed sweeps;
- each sweep: one 14-target goal SyncWrite, one four-byte all-14 `0x82`
  SyncRead, and one round-robin extended read;
- target: configured home with amplitude exactly zero while torque remains off;
- prohibited: torque enable, home entry, motion, gain/EEPROM/configuration
  writes, policy inference, and grounded operation.

The goal SyncWrite is retained solely to match the existing complete-sweep
population; it is transmitted only after torque-off is established and while
torque remains disabled. Startup or cleanup failure ends the run and attempts
the redundant final torque-off.

## Frozen evidence and statistics

Record 10,000 timing JSONL rows plus transaction-trace-v2 rows, source/config
hashes, RT state, UART attribution and before/after kernel byte counters, device
alarms, full transport taxonomy, watchdog state, record drops, and final cutoff
status. Transaction trace v2 must expose, per tick:

- collector mode;
- group read-call count;
- group parse-call count;
- bytes present at the first parse;
- request-write return, first/last application receive, and group-end times; and
- per-ID response-completion timestamps routed into logical order.

Report min/mean/p95/p99/p99.9/max for complete-sweep, grouped SyncRead, extended
read, receive span, and parse tail. Compare without modifying the reviewed UART
baseline or selecting a shorter favorable interval.

## Decision rules

The causal collector contract passes only if every normal complete group train
records `mode=exact_length_then_parse`, `parse_calls=1`, and
`bytes_before_first_parse=140`. An anomalous train may use additional bounded
parse calls but must retain its explicit error classification.

The bus blocker clears only if the complete 10,000-tick artifact also satisfies
all unchanged gates simultaneously:

- complete-sweep sample maximum strictly below 5 ms;
- tick p99 at most 21 ms and p99.9 at most 22 ms;
- transaction failures below 0.1%;
- zero temporal read-failure bursts;
- zero telemetry drops; and
- final torque-off `ok`.

Device alarms remain a separate failing motion-safety gate. They may be counted
in this torque-off timing diagnostic but may not be hidden, relabeled as
transport failures, or treated as Gate 2 clearance.

If the collector contract is correct but the bus gate still fails, stop and
review the captured stage distribution. Do not change telemetry cadence, split
the bus, permute more IDs, extend timeouts, enable torque, relax a threshold, or
escalate to Rust within this run.

## Authorization required before execution

Execution requires Rob to explicitly authorize this named torque-off collector
A/B and reconfirm that the robot is on its stand or otherwise suspended/benched.
The invocation must contain `--hardware-authorized --suspended-or-benched` and
must not contain `--enable-torque` or `--moving-gate-authorized`.

## Reviewed execution outcome

Rob authorized the named device test after reconfirming that the robot was on
its stand. The torque-off run completed all 10,000 sweeps with final cutoff
`ok`. The exact-length mechanism passed on all 10,000 traces: 140 bytes before
the first parse and exactly one parse. Tick tails, failures, bursts, alarms, and
telemetry gates passed, but complete-sweep mean/p99.9/max was
`5.655528/8.067290/8.352496 ms`. The unchanged `<5 ms` maximum failed.

See `sync_read_collector_ab/RESULT.md`. This result closes the exact-length
collector as a sufficient timing remedy and keeps Gate 2 blocked. Its stage
review selects a fixed-frame Python parser/decoder as the next offline
candidate; it does not authorize another hardware run or a Rust escalation.
