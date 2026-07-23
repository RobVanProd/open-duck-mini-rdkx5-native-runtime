# Direct UART 10,000-Tick Torque-Off A/B Result

Status: `COMPLETE_REVIEWED_BLOCKED`

The preregistered direct-UART run completed all 10,000 ticks at 50 Hz through
X5 UART1 `/dev/ttyS1`. The robot remained on its stand. Torque was disabled
before startup verification, never enabled, and disabled again during cleanup;
final torque-off was `ok`. No policy, home move, gain write, or nonzero target
amplitude ran, and no telemetry record was dropped.

The guarded startup received all 14 servo replies, proving that the powered
wiring, adapter UART mode, 1 Mbit/s framing, and RX/TX path function. USB serial
was absent throughout.

## Frozen result

| Population | mean | p95 | p99 | p99.9 | sample max |
| --- | ---: | ---: | ---: | ---: | ---: |
| Complete UART sweep | 5.363831 ms | 7.476066 | 7.789979 | 7.961047 | **8.353692** |
| One `0x82` all-14 burst | 3.747957 ms | 5.006685 | 5.047493 | 5.220183 | **5.347762** |
| One extended read | 0.744718 ms | 1.074523 | 1.120927 | 1.172257 | **1.203435** |

The complete sweep was at or above 5 ms on 4,588 of 10,000 ticks. Its maximum
therefore fails the unchanged `<5 ms` gate. The grouped `0x82` transaction alone
was at or above 5 ms 669 times and also exceeded 5 ms at p99.9 and maximum.

Tick determinism remains green: p99 `20.102866 ms`, p99.9 `20.127047 ms`, and
max `20.158971 ms`. This does not trigger the frozen Python-to-Rust escalation
criterion.

## USB versus UART

Removing the CH343 USB path produced no material complete-sweep improvement:

| Statistic | USB | UART | UART - USB |
| --- | ---: | ---: | ---: |
| Complete mean | 5.440859 ms | 5.363831 ms | -0.077027 ms |
| Complete p99.9 | 8.060332 ms | 7.961047 ms | -0.099285 ms |
| Complete max | 8.293083 ms | 8.353692 ms | +0.060609 ms |
| Group mean | 3.575249 ms | 3.747957 ms | +0.172708 ms |
| Group p99.9 | 5.136984 ms | 5.220183 ms | +0.083199 ms |
| Group max | 5.200234 ms | 5.347762 ms | +0.147528 ms |

UART reduced write-call and extended-read time, but the group TX-return to first
RX increased from USB mean `614 us` to UART mean `1,038 us`. Group response span
remained about 2 ms and the Python group-parse tail remained substantial: UART
mean/p99.9 `644/1,961 us`. The CH343/cdc_acm USB adapter is therefore not the
governing cause of the `<5 ms` failure.

## Transport failures and byte accounting

UART reported 145 failed outcomes among 160,000 expected (`0.090625%`), below
but close to the frozen `<0.1%` limit. There were 142 timeouts and three partial
responses across 52 isolated ticks, with zero CRC failures and zero temporal
read bursts. All logical failures belonged to late wire-order IDs 11-14:
ID 11 had 6, ID 12 had 41, ID 13 had 52, and ID 14 had 46.

Kernel UART counters are especially diagnostic. UART1 moved from `tx:0 rx:0`
to exactly `tx:800094 rx:1570140`, which matches the expected byte totals for
startup, 10,000 complete sweeps, and cleanup. The physical UART driver therefore
received the expected byte volume. The logical failures occur because late
responses cross the fixed 4 ms user-space collection deadline and are then
classified or flushed, not because the wire omitted 145 packets. Increasing
the deadline cannot make the strict `<5 ms` complete-sweep gate pass.

## Safety and decision

There were 146,432 separate voltage-alarm replies, so
`zero_device_alarms=false` independently blocks Gate 2. No alarm was masked and
no EEPROM or power change was made.

The direct-UART hypothesis is closed as a remedy for the bus budget. Gate 2
remains blocked, later gates remain unauthorized, and Rust is not triggered by
the frozen loop-timing rule. Further work must review the transaction/parser
architecture and the `<5 ms` design budget explicitly; it must not silently
relax the gate or reinterpret this result as success.

The raw timing and transaction streams remain on the X5 at
`/home/sunrise/duck-evidence/uart10k-torque-off-20260718` and are intentionally
not committed. Their board hashes and compact reviewed summary are preserved
here.
