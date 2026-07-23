# Exact-Length SyncRead Collector A/B Result

Status: `EXECUTED_REVIEWED_FAIL_BUS_BUDGET`

The authorized torque-off `/dev/ttyS1` run completed all 10,000 attempted
50 Hz sweeps on the robot's stand. It used source commit `8c73aae`, isolated
CPU 7, `SCHED_FIFO 80`, the frozen SyncRead wire order
`20,21,22,23,24,30,31,32,33,10,11,12,14,13`, zero amplitude, and no policy.
The command contained both hardware acknowledgements and omitted torque-enable
and moving-gate arguments.

Two launch attempts stopped before serial initialization: the first named a
nonexistent virtual-environment interpreter, and the second inherited the SSH
housekeeping-only CPU mask. The reviewed run started with `taskset -c 0-7`,
after which the runtime verified the intended control/background partition.
Neither stopped launch is included in the 10,000-sweep population.

## Safety and completeness

- run status: `COMPLETE`; exit code `0`; no halt;
- timing rows: 10,000 of 10,000; telemetry drops: 0;
- torque enabled: false; amplitude: 0; policy: none;
- initial all-servo verification passed;
- final torque-off: `ok`;
- device alarms: 0; voltage alarms: 0;
- no process retained `/dev/ttyS1` after completion.

## Frozen gates

| Quantity | Result | Gate | Outcome |
| --- | ---: | ---: | --- |
| Tick p99 | 20.096915 ms | <= 21 ms | pass |
| Tick p99.9 | 20.134589 ms | <= 22 ms | pass |
| Complete-sweep mean | 5.655528 ms | report | — |
| Complete-sweep p99.9 | 8.067290 ms | report | — |
| Complete-sweep max | 8.352496 ms | < 5 ms | **fail** |
| Transaction failures | 1 / 160,000 (0.000625%) | < 0.1% | pass |
| Read-failure bursts | 0; maximum run 1 tick | zero | pass |
| Device alarms | 0 | zero | pass |
| Telemetry drops | 0 | zero | pass |
| Final torque-off | `ok` | required | pass |

The sole transport failure was a CRC classification for ID 22 on tick 0. It
did not form a burst or cause stale reuse. Gate 2 remains blocked solely because
the complete-sweep sample maximum is not below 5 ms. This torque-off result is
not motion clearance.

## Collector mechanism result

The repaired collector contract passed exactly:

- all 10,000 traces recorded `mode=exact_length_then_parse`;
- all 10,000 had 140 bytes before the first parse;
- all 10,000 used exactly one group parse;
- every clean train satisfied the frozen contract; and
- the last application-observed response completion preceded the post-write
  four-millisecond deadline on every tick, with minimum margin 791.362 us.

Therefore the prior late-ID failures were an application collector failure,
not a 14-servo capacity or baud-rate failure. Reordering ID 13 last remains
preserved, and the exact collector reduced grouped outcomes from 145 failures
in the legacy UART run to one CRC. It did not clear the timing budget.

## Matched legacy-UART comparison

| Quantity | Legacy incremental | Exact-length | Exact minus legacy |
| --- | ---: | ---: | ---: |
| Sweep mean | 5.363831 ms | 5.655528 ms | +0.291697 ms |
| Sweep p99.9 | 7.961047 ms | 8.067290 ms | +0.106243 ms |
| Sweep max | 8.353692 ms | 8.352496 ms | -0.001196 ms |
| Group receive span mean | 1.986245 ms | 1.618775 ms | -0.367471 ms |
| Group parse tail mean | 0.644170 ms | 1.361458 ms | +0.717288 ms |
| Group state-decode gap mean | 0.581420 ms | 0.576630 ms | -0.004789 ms |

Collecting the fixed train first shortened the observed receive span but moved
all generic packet parsing behind the final receive. The single parse tail then
grew by 0.717 ms on average and more than erased the receive-span saving. The
separate state-decode gap still costs 0.577 ms mean, 1.119 ms p99.9, and
1.170 ms max. The complete exchange has 0.653 ms mean unattributed Python gap
after named serial phases.

The group end crossed the response deadline on 4,324 ticks even though all
140 bytes completed before the deadline. That distinction localizes the
remaining budget problem to post-reception Python parsing/decoding and other
host work rather than missing wire bytes. A fixed-frame parser/decoder is the
next evidence-selected Python candidate. The tick-tail criterion remains green,
so this result does not authorize a Rust escalation.

## Provenance

- runtime source commit: `8c73aae2110f10a294e1dcf333c41bfc9d2f3a88`;
- runtime source archive SHA-256:
  `a90070d00e8f0eca704005aa241c36e7ab4aa782ca7f8af41253d3d4be41de77`;
- timing JSONL SHA-256:
  `58989aa7655d62223730c546b8082cdff310ed6e66b4327331b480d6941734f3`;
- summary SHA-256:
  `4b6d815a7a17a8f1799da7618fcbc7454be79833d189f8dcfdb9f94a50660f80`;
- transaction-trace-v2 SHA-256:
  `9176145a42634d9d3e6054ce9aed623909db0245763f93cd17bf8631e048d7c4`;
- comparison analyzer commit: `fd276d4`;
- analyzer source archive SHA-256:
  `bb863be146e8e4d0dd145148ac2866be834d539db8890e0a64ed030ab381f0d9`;
- comparison result SHA-256:
  `fce3cfb6e3b65ae8f267c4562f39bd6cf45c8c95e2e1d564be1a82c74b6d4013`.

The compact summary, comparison, and board hash lists are checked in here. Raw
10,000-row timing and transaction traces remain on the board under
`/home/sunrise/duck-evidence/sync-read-collector-ab-8c73aae-retry2` and are not
committed.
