# USB 10,000-Tick Torque-Off Attribution Pre-Registration

Status before execution: `AUTHORIZED_NOT_RUN`

Rob authorized repeating the existing all-14 USB timing exchange without servo
activation. This is a transport-attribution run, not Gate 2 motion clearance.
Torque must be disabled before serial verification, remain disabled for the
entire sample, and be disabled again during cleanup. No policy inference, gain
write, torque enable, home entry, or moving test is permitted.

## Frozen setup

- adapter: WCH/QinHeng `1a86:55d3`, `/dev/ttyACM0`, `cdc_acm`;
- baud: 1,000,000 bit/s;
- wire SyncRead order: frozen IDs with 13 last;
- scheduler: verified isolated CPU 7, `SCHED_FIFO 80`;
- rate and window: exactly 10,000 attempted ticks at 50 Hz;
- transaction timeout: 4 ms;
- watchdog: two consecutive failed sweeps or a hard overrun above 40 ms;
- target amplitude: exactly 0 rad; and
- evidence: per-tick JSONL, summary, application transaction trace, hashes,
  source commit/archive hash, config hash, and final cutoff state.

The full-sweep probe necessarily emits one 14-target SyncWrite per tick so its
bus population matches the future runtime and UART A/B. Those goal packets are
sent only while torque is disabled and cannot be interpreted as motion or
torque authorization.

## Frozen populations and statistics

`bus_total_ms` is **not** a per-servo or per-transaction population. One
observation is the elapsed monotonic time for one complete tick sweep:

1. one broadcast 14-target SyncWrite;
2. one Feetech `0x82` SyncRead request followed by the 14 position/speed status
   packets as one contiguous response burst; and
3. one extended current/voltage/temperature read for the round-robin servo.

`bus_total_ms.max` is preregistered as the sample maximum across all 10,000
completed tick sweeps. `p99` and `p99.9` use that same 10,000-sweep population.
The summary must name this population and its observation count explicitly.

`group_round_trip_ms` is separately defined as one `0x82` instruction plus the
complete 14-response burst. Its maximum, p99, and p99.9 are also reported over
the completed tick population. It is not fourteen sequential host round trips.

The finite-window maximum describes only this preregistered 10,000-tick sample;
it is not claimed as a timeless physical maximum. A shorter run cannot replace
it or decide the USB-versus-UART comparison.

## Frozen decision outputs

The run is evidence-complete only if it records all 10,000 ticks, reports zero
telemetry drops, verifies RT isolation, and ends with final torque-off `ok`.
Report without reinterpretation:

- complete-sweep bus max and whether it is strictly below 5 ms;
- complete-sweep bus p99 and p99.9;
- grouped `0x82` max, p99, and p99.9;
- tick-period p99 and p99.9 against 21/22 ms;
- each transport failure class, rate, and bursts;
- device-alarm and voltage-alarm reply counts separately; and
- all three application-stage timing distributions.

Device alarms do not become transport failures. They still set
`zero_device_alarms=false`, prevent a Gate 2 candidate, and do not authorize an
EEPROM, supply, torque, or policy change. The upcoming direct-UART result must
use the same 10,000-tick population and statistics for a valid A/B.
