# Hardware Gate 2 Preflight Result

Status: `SUPERSEDED_TIMING_PREFLIGHT_PASS_GATE_2_NOT_RUN`

Gate 2 was explicitly authorized for a suspended/benched all-14 home hold with
no policy. Torque-off preflight did not satisfy the frozen bus gates, so torque
was never enabled, the home move did not begin, and the 10,000-tick moving hold
was not run. `NOT_RUN.md` therefore remains authoritative for Gate 2 itself.

A later separately authorized one-variable governor A/B supersedes the timing
blocker recorded here: under `performance`, the torque-off 10,000-tick sweep
passed with a 4.821428 ms maximum and restored `schedutil`. Gate 2 itself remains
not run and requires fresh moving-gate authorization. See
`cpu_governor_ab/RESULT.md`.

## Safety and provenance

- final deployed source commit: `9cd4ca0`
- deployed archive SHA-256:
  `7e41efeee1aeee562ae53111f22cc6fec044681db82d126e6f9a6c40eb894c16`
- config SHA-256:
  `131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b`
- device: WCH `1a86:55d3`, USB full-speed 12 Mbit/s, Linux `cdc_acm`
- `/sys` latency timer: unsupported
- RT provenance: isolated CPU 7, `SCHED_FIFO 80`, background CPUs 0-6
- every executed bus diagnostic established and finished with torque off
- no policy inference, goal movement, home entry, or torque enable occurred

The first attempted torque-off preflight stopped before serial open because the
RT guard used the nonexistent `os.get_native_id`. Commit `6ba0e32` corrected it
to `threading.get_native_id`, and the real X5 then verified the complete thread
partition. This failure caused no servo packet.

## Initial all-14 torque-off exchange

Fifty ticks with the original frozen wire order completed with:

- tick p99.9: `20.105812 ms`
- bus max: `7.639308 ms` (`FAIL`, required below 5 ms)
- four CRC failures, all on servo 13
- transaction failure rate: `0.5%` (`FAIL`, required below 0.1%)
- zero bursts, zero partial bytes, zero unexpected packets, zero telemetry drops
- final torque-off: `ok`

Machine-readable result: `preflight_initial_summary.json`.

## Servo 13 causal isolation

An individual torque-off probe then read servo 13 for 2,000 ticks with zero
failures, zero bursts, p99.9 round trip `1.016509 ms`, and final torque-off
`ok`. The servo and its individual response path are therefore not sufficient
to reproduce the CRC.

A guarded grouped-read order diagnostic produced:

| Wire order | Completed | CRC result | Group-read max |
| --- | ---: | --- | ---: |
| frozen, ending `..., 13, 14` | 239 | 5 on ID 13; stopped on consecutive failed ticks | 4.964103 ms |
| fully reversed, with `14, 13` | 500 | 0 | 4.439309 ms |
| rotated, still containing `13, 14` | 500 | 10 on ID 13 | 4.484809 ms |

Rob confirmed the known physical-chain requirement that ID 13 be requested
last. Commit `9cd4ca0` changes only the wire SyncRead order to end `..., 14, 13`;
the frozen logical joint/action/servo order is unchanged and replies remain
routed by ID.

Machine-readable individual result: `diagnostic_id13_summary.json`. The guarded
order-diagnostic source SHA-256 is
`fa2031505881fbf1eb40efffc2abeefdc6a06fa49fc909001380c3a7264dca67`.

## Repeated preflight with ID 13 last

The same 50-tick all-14 torque-off exchange then completed with:

- zero CRC failures
- one device-status reply on servo 13
- transaction failure rate: `0.125%` (`FAIL`)
- bus time at or above 5 ms on 25 of 50 ticks
- bus mean/max: `5.339127 / 7.703526 ms` (`FAIL`)
- tick p99/p99.9: `20.101217 / 20.101307 ms` (`PASS`)
- zero bursts, partial bytes, unexpected packets, and telemetry drops
- final torque-off: `ok`

Machine-readable result: `preflight_id13_last_summary.json`.

## Rejected combined-read diagnostic

A torque-off diagnostic tested replacing the per-tick four-byte state read plus
one extended read with one 15-byte grouped response. Across 500 ticks, bus
mean/p99.9/max was `5.133325 / 6.656727 / 6.730143 ms`, with multiple later-ID
timeouts and CRCs under the unchanged 4 ms deadline. This alternative is not
selected. Its guarded source SHA-256 is
`ce0af5b599697cbe5dc0c2ece6120645ff13e20e22d4ac5b943236689755702b`.

## Decision boundary

The Python RT loop's tick timing is green; this evidence does not trigger the
pre-registered Rust escalation, and a native extension would not by itself
remove the measured USB transaction latency. The current WCH device is bound to
generic `cdc_acm`; the stock X5 `ch341` module does not claim product `55d3`.

Gate 2 remains stopped. Continuing requires a separately reviewed transport
decision such as a different low-latency adapter/direct UART path, or an explicit
contract review. The existing `<5 ms` budget and telemetry cadence must not be
silently relaxed. Gates 3-5 remain unauthorized.

## Vendor-driver follow-up

The official WCH CH343 Linux driver was subsequently tested under separate
authorization and rolled back. It produced zero failures in the same 50-tick
torque-off preflight but total bus mean/max remained
`5.437868 / 7.490049 ms`. It therefore does not resolve the bus-budget blocker.
See `CH343_EXPERIMENT.md` and `preflight_ch343_summary.json`. The board is back
on `cdc_acm`; Gate 2 remains `NOT_RUN_BLOCKED_PREFLIGHT`.

## Software-only USB latency follow-up

Rob clarified that no external logic analyzer was available or required. An
authorized application-instrumented plus Linux `usbmon` diagnostic was deployed
from commit `a50d32d22b7e60167a0087fd29ea02141628b1f5`. The probe established
torque off, received all 14 startup replies in the reviewed wire order, and then
halted because every servo reported status `0x01` (input-voltage error). The
50-tick loop never began, no goal target was written, and final cleanup sent a
second all-14 torque-off packet.

The startup SyncRead completed all fourteen USB responses in `2.130 ms`, with
successive response completions separated by `123-147 us`. This rules out a
one-millisecond USB-frame delay per servo in this exchange, but it is not a
completed Gate 2 timing result. See `software_usbmon_voltage_halt/RESULT.md`.
Another run is blocked until the servo supply condition is checked and a fresh
torque-off diagnostic is explicitly authorized.

Rob inspected the visible connections, rebooted the robot, and authorized one
retry. The retry independently reproduced status `0x01` on all fourteen startup
replies and halted before the timing loop. Its fourteen-response USB interval
was `2.125 ms`; cleanup again completed with torque off and no target write.
See `software_usbmon_voltage_halt_retry/RESULT.md`. Repeating the same capture is
now closed. The next useful diagnostic is a separately authorized torque-off
read of present-voltage telemetry without ignoring the device status.

The separately authorized all-14 register-62 diagnostic then completed without
transport failures. Every servo reported status `0x01` while measuring
`8.2-8.4 V` (mean `8.257 V`). Initial and final torque-off were `ok`, and no
goal write occurred. The rail is present and consistent; the leading unresolved
cause is a configured maximum-voltage threshold below the measured rail. See
`voltage_diagnostic/RESULT.md`. Gate 2 remains blocked pending a read-only model
and configured voltage-limit audit.

That audit is now complete. Every servo returned model/version `0x0309`, maximum
input voltage `8.0 V`, and minimum input voltage `4.0 V`. Combined with the
measured `8.2-8.4 V` rail, this confirms a common supply-above-configured-maximum
root cause for the persistent all-servo `0x01` status. See
`voltage_limit_diagnostic/RESULT.md`. No EEPROM or supply change was made. Gate 2
remains blocked until the physical servo supply is brought into the supported
range and a torque-off status/voltage read is clean.

## 2026-07-18 voltage-alarm configuration complete

Subsequent model documentation and owner authorization selected the installed
STS3215 8.4 V upper limit. The guarded torque-off configuration is complete:
all 14 servos read raw maximum/minimum `84,40`, device status 0, and present
voltage 8.2-8.4 V. All known locks and final torque-off verified; no motor was
energized. See `voltage_limit_8v4_complete/RESULT.md`.

This supersedes only the voltage-alarm portion of the blocker above. The later
fixed-length SyncRead collector A/B passed its exact 140-byte receive contract
but measured complete-sweep mean/p99.9/max of
`5.655528/8.067290/8.352496 ms`. Gate 2 remains blocked by the unchanged
`<5 ms` maximum; see `sync_read_collector_ab/RESULT.md`.

## 2026-07-18 CPU-governor timing preflight passes

The frozen governor arm changed only policy0 from `schedutil` to `performance`
for the exact same 10,000-tick torque-off population. Complete-sweep
mean/p99.9/max became `4.115062/4.522262/4.821428 ms`, tick p99/p99.9 became
`20.002755/20.005297 ms`, and failures, bursts, alarms, and drops were zero.
The runner restored `schedutil` and final torque-off was `ok`.

This clears the independent torque-off timing preflight. It does not turn the
historical stopped home hold into a pass: no torque or motion occurred, and a
new authorization is still required for Gate 2 itself. See
`cpu_governor_ab/RESULT.md`.
