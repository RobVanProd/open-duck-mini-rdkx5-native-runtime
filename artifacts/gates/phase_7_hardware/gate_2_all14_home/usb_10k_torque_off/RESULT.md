# USB 10,000-Tick Torque-Off Attribution Result

Status: `COMPLETE_REVIEWED_BLOCKED`

The preregistered USB window completed all 10,000 ticks at 50 Hz. Torque was
disabled before the serial verification, never enabled, and disabled again at
cleanup. Final torque-off was `ok`; there was no halt, policy inference, home
move, gain write, or telemetry drop. The amplitude was exactly zero. The normal
all-14 goal SyncWrite was emitted only while torque was disabled so the sampled
population matches the future runtime and direct-UART comparison.

The first launch attempt inherited the SSH housekeeping-only affinity and was
rejected by the RT guard before the serial device opened. The authoritative run
was then started with the reviewed `0-7` initial affinity; all background
threads were verified on CPUs 0-6 and the control loop on isolated CPU 7 under
`SCHED_FIFO 80`.

## Attribution

The adapter is WCH/QinHeng `1a86:55d3`, exposed as `/dev/ttyACM0` and bound to
`cdc_acm`. It is not FTDI, `/dev/ttyUSB0` does not exist, and the tty sysfs tree
has no `latency_timer`. The FTDI default-16-ms timer is therefore ruled out as
an available cause or falsification knob on this hardware.

The bus maximum is a complete-sweep statistic, not a per-servo transaction
maximum. Each of the 10,000 observations contains:

1. one broadcast all-14 goal SyncWrite;
2. one Feetech `0x82` SyncRead request and contiguous 14-response position/speed
   burst; and
3. one round-robin extended telemetry read.

The grouped-read statistic separately measures one `0x82` request plus that
complete 14-response burst. The implementation is already consolidated; it is
not doing fourteen host round trips per tick.

## Frozen results

| Population | mean | p95 | p99 | p99.9 | sample max |
| --- | ---: | ---: | ---: | ---: | ---: |
| Complete bus sweep | 5.440859 ms | 7.539115 | 7.821083 | 8.060332 | **8.293083** |
| One `0x82` all-14 burst | 3.575249 ms | 4.747242 | 4.911863 | 5.136984 | **5.200234** |
| One extended read | 0.821361 ms | 1.186317 | 1.226882 | 1.258384 | **1.309132** |

The complete sweep was at or above 5 ms on 5,103 of 10,000 ticks. The grouped
burst alone was at or above 5 ms on 45 ticks. The `<5 ms` complete-sweep gate
therefore fails decisively; the earlier 50- and 250-tick maxima were not
certifying evidence.

Loop determinism remains green: tick p99 was `20.101184 ms`, p99.9 was
`20.105310 ms`, and max was `20.143516 ms`. This supports the existing decision
not to escalate to Rust based on loop timing.

Four of 160,000 expected transport outcomes failed (`0.0025%`): timeouts for
IDs 13 and 14 together at tick 195, and CRC failures for ID 11 at ticks 6786
and 7809. They were isolated ticks, so the preregistered failure-rate and
zero-burst conditions pass. They do not rescue the bus-time failure.

## Transaction anatomy

The application trace confirms both physical streaming and host/software tail:

- group TX-return to first RX: mean `614 us`, p99.9 `851 us`;
- 14-response RX span: mean `2,034 us`, p99.9 `3,053 us`;
- group parse tail: mean `624 us`, p99.9 `1,774 us`;
- extended TX-return to first RX: mean `411 us`, p99.9 `590 us`; and
- extended parse tail: mean `194 us`, p99.9 `349 us`.

This is not a one-millisecond-per-servo USB floor: the responses arrive as a
burst. The complete USB path still misses the bus budget through the combined
USB/serial turnaround, response-span, and Python parsing tails. Direct UART is
now the correct controlled A/B, using the identical 10,000-tick population and
statistics after Rob performs the wiring change.

## Device alarms and evidence custody

Valid alarm-bearing payloads were kept separate from transport failures.
There were 146,900 voltage-alarm replies among 149,996 valid read replies, so
`zero_device_alarms` remains false and this cannot become a Gate 2 candidate.
No alarm was masked and no EEPROM or power change was made.

The raw 15 MB timing stream and 16 MB transaction trace remain on the X5 at
`/home/sunrise/duck-evidence/usb10k-torque-off-20260715`. They are intentionally
not committed. Their board-side SHA-256 values and compact reviewed summary are
preserved here. Gate 2 remains blocked; no later hardware gate is authorized.
