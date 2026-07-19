# Hardware Gate 2 Result — All-14 Home Hold

Status: `PASS_REVIEWED`

The performance-governed Gate 2 sequence completed on 2026-07-18 using direct
UART `/dev/ttyS1` at 1,000,000 bit/s. The robot was on its stand, hands were
clear, and no policy was loaded. The exact frozen source, config, launcher, and
validator hashes matched the pre-registration before execution.

Stage A ran 10,000 torque-off sweeps. Its independent validator passed before
the launcher could reach Stage B. Stage B then established torque-off, verified
all 14 servos, moved from fresh measured positions to home over five seconds,
and held home for 10,000 ticks with zero target amplitude. Final torque-off was
`ok`; the probe and launcher exited; `/dev/ttyS1` was free; and the governor was
restored from `performance` to the original `schedutil` policy.

## Frozen gate results

| Metric | Stage A: torque-off preflight | Stage B: home hold | Gate |
| --- | ---: | ---: | ---: |
| Complete ticks | 10,000 | 10,000 | 10,000 |
| Tick p99 | 20.002520 ms | 20.002683 ms | <= 21 ms |
| Tick p99.9 | 20.006060 ms | 20.008892 ms | <= 22 ms |
| Tick maximum | 20.013143 ms | 20.026058 ms | report |
| Complete-sweep mean | 3.648734 ms | 3.657165 ms | report |
| Complete-sweep p99.9 | 4.048265 ms | 4.050475 ms | report |
| Complete-sweep maximum | 4.532473 ms | 4.721847 ms | < 5 ms |
| Expected/ok transactions | 160,000 / 160,000 | 160,000 / 160,000 | complete |
| Failed transactions | 0 | 0 | < 0.1% |
| Read bursts | 0 | 0 | 0 |
| Partial/unexpected responses | 0 / 0 | 0 / 0 | 0 / 0 |
| Device/voltage alarm replies | 0 / 0 | 0 / 0 | 0 / 0 |
| Telemetry records dropped | 0 | 0 | 0 |

Every tick comprised one all-14 SyncWrite, one fixed-frame all-14 SyncRead in
wire order `20,21,22,23,24,30,31,32,33,10,11,12,14,13`, and one round-robin
extended read. CPU 7 was isolated and the control thread verified
`SCHED_FIFO 80`; background workers were confined to CPUs 0-6.

## Additional review, not a post-hoc gate

The frozen Gate 2 decision required a 10,000-sample tracking population but did
not use the Gate 4 sine threshold. A separate read-only review of all 14 logged
hold errors found a worst per-joint p95 of `0.005516521 rad` on right hip roll.
All 14 p95 values were below `0.011 rad`; initial home-entry settling explains
the larger per-joint sample maxima and does not affect the preregistered Gate 2
decision.

Round-robin telemetry covered every servo 714 or 715 times per stage. During
the home hold, present voltage ranged from 6.9 to 8.4 V, temperature from 29 to
42 degrees C, and reported current from 0 to 0.182 A. These observations remain
within the stated 5.0-8.4 V motor range, and no device or voltage alarm reply
occurred. They are recorded as telemetry, not substituted for the transport or
timing gates.

## Provenance and retained data

- execution source commit:
  `a5b53442012899f89c899f5c2f8f1a110c4448f2`;
- source archive SHA-256:
  `730d53480de5cf3c64381c75984289994d4edb798e2b09aec31b1f8df7ff67f5`;
- config SHA-256:
  `131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b`;
- launcher/validator source commit:
  `22b8e2c247d834ff68372212ce19e9e1d2b2ea6e`;
- launcher SHA-256:
  `868d6ebfa29672e8a4a482819b0bc5d19e13b91468e79b964cf0636d3b732f2a`;
- validator SHA-256:
  `bd3d3cd95fd5ef957bb499c9fd9266a5d9101397c95adf02c2358bb9f8355145`;
- board evidence directory:
  `/home/sunrise/duck-evidence/gate2-home-hold-a5b5344-20260718-2124`;
- raw preflight JSONL SHA-256:
  `a8a40fc53cab83a46ea13f68435d1a5d4aad5c0788087d4dd4890be7d568d347`;
- raw home-hold JSONL SHA-256:
  `66e10ba2d9138087ca548d0e0c8dab6dc1515f8e51dab4570b2c314b065f72ce`.

The 30.5 MB of raw JSONL remains board-side and is not committed. The reviewed
machine-readable reduction and the board-generated checksum list are stored in
`performance_governed_home_hold/`. Board-side `sha256sum -c` verified every
listed file after completion.

Gate 2 passes. This result does not authorize Gate 3, policy inference, Gate 5,
grounded replay, or grounded walking.
