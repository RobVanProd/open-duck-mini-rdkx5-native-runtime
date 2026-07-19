# Design Decisions

## D001 — Measurement before optimization

Accepted. The timing probe and failure taxonomy precede hardware optimization. Zero reported errors is not an acceptance metric.

## D002 — Python first, native only by gate

Accepted. Policy and servo transaction start in Python. A Rust extension is allowed only after an authorized RT/isolation run misses tick p99 or p99.9 gates. Only the transaction crosses FFI. The serial all-14 probe refuses to run without verified `SCHED_FIFO`, control-core affinity, and exclusion of every background native thread from that core.

## D003 — One direct bus stack

Accepted. Runtime and parity tools share the direct STS3215 implementation. pypot and rustypot are audit references, not runtime dependencies.

## D004 — Reject stale observations

Accepted. The frozen 101-vector has no staleness slots. A stale required input invalidates the tick; it is never silently reused for inference.

## D005 — Preserve deployed phase order confirmed by golden evidence

Accepted for the runtime contract. The corrected-knee board capture passes all 101
observation elements and proves the observation phase equals the prior tick's
post-advance phase. Prior training/MuJoCo code advanced phase before constructing its
observation, so policy hardware gates remain blocked until the selected candidate's
training/export source proves semantic parity.

## D006 — No grounded execution surface

Accepted. Hardware CLIs require suspended/benched assertion. The runtime exposes no grounded mode from this workstream.

## D007 — Incomplete telemetry invalidates a run

Accepted. Bounded queues remain off the hot thread, but pool exhaustion, queue
overflow, and writer I/O failure are fatal evidence errors. A run with an
unrecorded tick or envelope event cannot remain `COMPLETE`.

## D008 — Reserve serial runtime for the exact Gate 5 scope

Accepted. Gate 1/2/4 use their dedicated probes. Serial policy execution also
requires a per-invocation Gate 5 assertion, a 101/14 policy, `start_paused=true`,
a finite duration, and exact `x=0` or `x=0.08`; each command is authorized and
reviewed separately.

## D009 — Recompute Gate 5 evidence from a complete JSONL stream

Accepted. The runtime records hashed startup provenance and contiguous tick/event
records. An offline summarizer recomputes timing, bus failures, bursts, command,
staleness, telemetry coverage, and envelope events rather than trusting runtime
counters. Mock runs cannot become hardware evidence, and serial summaries always
require human review.

## D010 — Separate paused wall-clock bounds from policy duration

Accepted. `--max-ticks` is the hard total-loop cap and
`--max-active-ticks` is the required number of valid policy ticks. Gate 5 uses a
bounded paused startup window and cannot silently shorten a 600-tick replay.

## D011 — Make the Gate 5 controller pause-only

Accepted. Exact fixed-command replay cannot depend on joystick drift, head mode,
or LB state. Serial Gate 5 retains the physical pause/unpause edge but zeros all
non-X commands and fixes phase speed at 1.0. General controller parity remains
unchanged outside that gate.

## D012 — Make shutdown cutoff-first and evidence-bearing

Accepted. The runtime issues its redundant final torque-off before closing any
worker, sensor, controller, serial, or telemetry resource. The terminal event
records whether cutoff was attempted, its explicit bus status, and any error.
The offline summarizer cannot report a complete run or Gate 5 candidate without
`torque_off_status=ok`. This does not claim the physical rail has decayed; that
latency still requires Phase 6 hardware evidence.

## D013 — Make the RT preflight test the claimed scheduler state

Accepted. `verify_rt_setup.sh` uses exact Linux CPU-list parsing and a
short-lived process that must enter the requested CPU affinity and `SCHED_FIFO`
priority. Merely finding the core number as a substring or printing the current
non-RT scheduler cannot produce `result=PASS`.

## D014 — Keep ONNX inference on the RT control thread

Accepted. The CPU session uses sequential execution with one intra-op and one
inter-op thread, and disables worker spinning. The default ONNX Runtime pool can
span the physical cores; waiting on those SCHED_OTHER workers would reintroduce
unbounded housekeeping latency into the SCHED_FIFO loop. The session settings
are recorded in startup and policy-handoff evidence. Authorized timing still
decides whether this configuration is sufficient.

## D015 — Bind timing comparisons to complete reviewed evidence

Accepted. Timing summaries carry the raw JSONL SHA-256, RT and authorization
provenance, moving-gate scope, final torque-off status, and explicit Gate 2/4
candidate fields. The comparison builder rejects halted or incomplete input and
protects its source path. Mock output stays informational; serial output is
always `REVIEW_REQUIRED`, never an automatic `HARDWARE_RESULT`.

## D016 — Apply complete-evidence rules to Gate 1

Accepted. The single-servo summary binds its raw stream, authorization
assertions, final cutoff status, ping, per-class failures, bursts, and exact
two-byte response framing. Only a serial run with all of those checks can become
a Gate 1 review candidate, and the candidate does not advance Gate 2.

## D017 — Keep Gate 3 physical labels human-reviewed

Accepted. Sensor summaries bind raw data, config, and both hardware assertions,
and can identify a complete fresh timestamp stream. They cannot infer whether
the operator actually held the robot upright, tilted it in the named direction,
or pressed the named switch. The data candidate therefore remains subordinate
to explicit label review.

## D018 — Separate logical servo order from measured SyncRead wire order

Accepted. The frozen logical/action order remains IDs
`20-24,30-33,10-14`. Torque-off hardware diagnostics reproduced CRCs on ID 13
whenever its grouped response preceded ID 14, while an individual 2,000-read ID
13 run and a grouped order with 14 before 13 were clean. Rob confirmed that ID
13 must be last on this physical chain. SyncRead therefore requests the same IDs
in wire order ending `14,13`; response packets are still routed into frozen
logical order by their ID. This transport-only repair cannot change observation
or action semantics and does not waive the Gate 2 bus-time threshold.

## D019 — Reject the CH343 vendor driver as the Gate 2 latency remedy

Accepted. The official WCH driver at pinned upstream commit `9e6eb31` built
against the exact `6.1.83` headers and was live-bound under an explicit,
rollback-first authorization. It produced a clean 50-tick torque-off transaction
stream, but total bus mean/max was `5.437868 / 7.490049 ms` versus the unchanged
`<5 ms` gate. Tick p99.9 remained green. The module was fully removed and the
adapter restored to `cdc_acm`. The driver is not retained merely because it
changed the error counter; it did not solve the governing latency measurement.

## D020 — Stop USB timing capture on an all-servo voltage fault

Accepted. The software-only application plus `usbmon` capture received valid
framing from every servo, but each packet reported device status `0x01`, the
protocol's input-voltage error bit. The startup verifier must continue treating
those samples as invalid; it may not suppress the device error to manufacture a
timing result. The trace proves that no goal-position packet or torque enable was
sent and that final torque-off completed. A new diagnostic requires the servo
supply condition to be checked and fresh explicit authorization.

After visible connection inspection and a robot reboot, one authorized retry
reproduced status `0x01` on all fourteen replies. Repeating the same capture is
closed; the next distinct step is an explicit torque-off present-voltage read,
not suppression of the status byte.

## D021 — Preserve device-error telemetry for a read-only voltage diagnosis

Accepted. A diagnostic-only register API may preserve parameters from a valid
device-error packet while still classifying it as `device`; the operational
runtime continues to discard that payload and mark the sample stale. The
authorized register-62 run measured `8.2-8.4 V` on all 14 servos while every
response asserted voltage error. No EEPROM or supply change follows from this
alone. Model/version and configured voltage-limit reads require a distinct
authorization.

## D022 — Treat the all-servo voltage status as a real supply-limit mismatch

Accepted. All 14 servos read back identical model/version `0x0309`, maximum
input voltage `8.0 V`, and minimum `4.0 V`; their live register-62 voltage is
`8.2-8.4 V`. The persistent status `0x01` is therefore neither a baud/parser
artifact nor a single-servo fault. Runtime startup must continue rejecting it.
Do not raise EEPROM limits to make the error counter green. Correct the physical
supply first, then require a clean torque-off voltage/status capture before any
Gate 2 retry.

## D023 — Separate transport validity from device alarms and correct power provenance

Accepted. Frank Fu's build article delegates the hardware construction to the
upstream Open Duck Mini v2 instructions. The upstream editable wiring diagram
specifies two 18650 cells in series, a 7.4 V BMS/output, and a 7.4 V motor-board
input. The installed servos were also confirmed by the owner as 7.4 V units.
The observed 8.2-8.4 V rail is therefore consistent with a charged 2S pack; the
later 3S/12.6 V reconstruction was not the provenance of this robot. Registers
3-4 are retained as raw version bytes and must not be presented as a confirmed
servo SKU.

A checksum-valid, correctly sized reply with status byte `0x01` is now recorded
as a successful transport transaction plus a separate raw device alarm. Its
position, speed, or telemetry payload remains fresh and observable. Timeouts,
checksum failures, and partial packets remain transport failures and stale the
affected sample. This prevents a valid alarm reply from being mislabeled as a
serial failure without hiding the alarm or laundering the device-alarm count.

Safety stays fail-closed. Runtime startup and every torque-capable probe reject
any device alarm before torque enable or target writes. A torque-off diagnostic
may use valid alarm payloads to measure transport timing, but
`zero_device_alarms` remains false and the run cannot become a Gate 1, Gate 2,
Gate 4, or Gate 5 candidate. No EEPROM limit, power wiring, torque, or policy
change is authorized by this decision. Gate 2 also remains blocked by its
independent `<5 ms` total-bus-time requirement.

This decision supersedes only D020-D022's interpretation that alarm-bearing
payloads must be stale and that the documented 2S supply is physically wrong.
The raw captures, voltage readings, configured 4.0/8.0 V thresholds, and alarm
bytes remain valid historical evidence. See
`docs/POWER_AND_DEVICE_STATUS_RECONCILIATION.md`.

## D024 — Attribute the USB adapter and freeze the timing population

Accepted. Read-only X5 inventory identifies the adapter as QinHeng/WCH
`1a86:55d3`, `/dev/ttyACM0`, bound to `cdc_acm`. It is not FTDI, exposes no
`/dev/ttyUSB0`, and has no sysfs `latency_timer`; the FTDI default-16-ms timer is
not an available causal knob. The prior CH343 vendor-driver result remains the
relevant USB-driver A/B, and direct UART is the next transport A/B when Rob is
present to rewire it.

`bus_total_ms` is frozen as one observation per complete tick sweep: one
14-target SyncWrite, one `0x82` SyncRead with a contiguous 14-response burst,
and one round-robin extended read. It is not a per-servo or per-transaction
maximum. `group_round_trip_ms` separately covers the single `0x82` request and
complete response burst. The USB attribution window is exactly 10,000 attempted
ticks at 50 Hz; `max`, p99, and p99.9 are computed over the completed-tick
population and reported with its observation count. A 50- or 250-tick run may
debug the harness but cannot decide the USB-versus-UART comparison.

The authorized USB run remains torque-off throughout. It emits the normal
14-target SyncWrite only to preserve the full runtime bus population; it does
not enable torque, enter home, move, or infer a policy. See the adapter
attribution and 10,000-tick pre-registration artifacts under Gate 2.

## D025 — USB fails the complete-sweep budget over the frozen 10,000-tick window

Accepted. The torque-off USB run completed all 10,000 ticks with verified
`SCHED_FIFO 80` on isolated CPU 7, final torque-off `ok`, no halt, and no
telemetry drops. Tick p99/p99.9 passed at `20.101184/20.105310 ms`, so the
Python-to-Rust escalation criterion remains false.

The complete-sweep bus population measured mean/p99.9/max
`5.440859/8.060332/8.293083 ms`; 5,103 of 10,000 sweeps were at or above 5 ms.
The single `0x82` request plus 14-response burst measured
`3.575249/5.136984/5.200234 ms`. The `<5 ms` complete-sweep gate therefore fails
decisively over the preregistered window. Four isolated transport failures among
160,000 expected outcomes (`0.0025%`) pass the failure-rate and burst gates but
do not change the bus-time result.

Application tracing shows the responses already arrive as a burst rather than
fourteen host round trips. The remaining USB result combines adapter/driver
turnaround, response-stream duration, and Python parsing tail. Direct X5 UART is
selected as the next controlled transport A/B after Rob performs the physical
wiring change; it must repeat the same 10,000-tick population and statistics.
No wiring change, torque, motion, Rust escalation, or later gate is authorized
by this decision.

## D026 — Attribute direct UART before opening the port

Accepted. After Rob removed the USB cable and moved the Waveshare adapter to its
UART connection, read-only inventory identified `/dev/ttyS1` as X5 UART1:
device-tree alias `serial1` resolves to `34070000.serial`, the active driver is
`dw-apb-uart`, and pinctrl assigns `lsio_uart1_rx/tx` to `uart1grp`. The CH343
USB device is absent, no process owns `/dev/ttyS1`, and its kernel counters were
`tx:0 rx:0`; attribution therefore caused no UART traffic.

The UART A/B is frozen at the same 10,000 complete-sweep population and
statistics as USB. Rob subsequently confirmed that the robot is on its stand
and directed the torque-off comparison to continue. No shorter wiring check may
be substituted for the comparison window, although a failed guarded startup may
stop before the population begins.

## D027 — Direct UART does not clear the complete-sweep bus budget

Accepted. The `/dev/ttyS1` torque-off A/B completed all 10,000 ticks with final
cutoff `ok`, no halt, and no telemetry drops. Complete-sweep
mean/p99.9/max was `5.363831/7.961047/8.353692 ms`, versus USB
`5.440859/8.060332/8.293083 ms`. The negligible mean/tail improvement and
slightly worse maximum fail the unchanged `<5 ms` gate. The grouped `0x82`
burst was worse on UART at mean/p99.9/max
`3.747957/5.220183/5.347762 ms`.

UART produced 145 logical failures among 160,000 expected outcomes
(`0.090625%`): 142 timeouts and three partial packets, isolated across 52 ticks
and concentrated on late wire-order IDs 11-14. Kernel UART counters increased
by exactly the expected `800094 TX` and `1570140 RX` bytes, with zero parsed CRC
failures. The physical driver received the expected byte volume; late replies
crossed the fixed 4 ms user-space collection deadline. Extending that deadline
cannot satisfy a strict complete-sweep maximum below 5 ms.

Tick p99/p99.9 remained green at `20.102866/20.127047 ms`; the frozen native
escalation criterion is not triggered. The CH343/cdc_acm USB adapter is closed
as the governing cause, and direct UART is closed as its remedy. Any next step
must explicitly review the transaction/parser architecture and bus budget; it
may not silently relax the gate, remove required telemetry, or jump to Rust by
preference.

## D028 — Test the fixed-length SyncRead collector before changing architecture

Accepted as an offline implementation decision; hardware result remains
`NOT_RUN`. Feetech's protocol fixes each four-byte all-servo state reply at ten
bytes and requires replies in the request's ID order. The normal fourteen-servo
response train is therefore exactly 140 bytes. The prior collector instead
parsed and compacted after every nonblocking read and started its fixed response
deadline before input flush and request transmission. Application parsing was
therefore interleaved with arrival of the later responses, and the next input
flush could discard a late remainder.

The Python bus now collects the expected 140 bytes into its preallocated buffer,
then parses the normal train once. The response deadline begins after the
SyncRead request write returns. Unexpected, duplicate, missing, corrupt, and
partial trains retain the existing explicit taxonomy and enter only a bounded
recovery path. Logical/action order remains frozen; wire order still ends
`14,13`; telemetry cadence, timeout value, bus gate, and Rust escalation rule are
unchanged.

Transaction trace v2 records collector mode, parse-call count, and bytes present
at the first parse. Offline tests cover every one-byte fragmentation boundary,
wire-order generation, out-of-order ID routing, unexpected-packet recovery,
omitted-ID timeout, CRC, partial response, and a request write longer than the
response timeout. These tests establish the software mechanism but cannot pass
Gate 2. The next hardware action is only the separately preregistered matched
10,000-tick torque-off A/B; no torque, motion, policy, threshold relaxation, or
additional hardware follows from this decision.

## D029 — Set the STS3215 maximum-voltage alarm to its documented 8.4 V limit

Accepted for one guarded, torque-off configuration run; hardware result remains
`NOT_RUN`. The owner's motor specification and Feetech's STS3215 product manual
identify 8.4 V as the upper supported voltage. The installed charged-2S rail
was measured at 8.2-8.4 V while all fourteen servos held a configured 8.0 V
maximum, exactly accounting for their common voltage-alarm bit.

D023 correctly prevented an unreviewed EEPROM change; this decision supersedes
only that prohibition now that the servo voltage limit, 2S power provenance,
exact stored values, and owner authorization are established. It does not
change the supply, ignore an alarm, or reinterpret the result as a timing pass.

The update changes only register 14 from raw 80 to raw 84. Register 15 remains
raw 40. A dedicated tool requires read-before-write across all 14 IDs, a
servo-20 canary, individual unlock/write/readback/relock transactions, a
post-write present-voltage/status check, a final all-servo audit, and an fsync'd
journal. Unexpected or mixed values halt before any EEPROM write. A persistent
canary voltage alarm halts before the remaining 13 units. Every crash path
attempts relock and all-servo torque off; no torque enable, goal target, policy,
or motion command exists in this operation.

The configuration result must be reviewed separately. Gate 2 remains blocked
by the independent `<5 ms` complete-sweep bus budget, and the fixed-length
collector A/B remains a different, separately controlled torque-off test.

## D030 — Recover acknowledgement loss by exact register readback

Accepted after the first D029 run halted safely. IDs 20-22 read back raw
`84,40` with a clear voltage alarm, proving ID 22's maximum write landed despite
its missing acknowledgement. The emergency relock acknowledgement was also
missing, so no further write is allowed until register 55 is independently
read and, if necessary, relocked.

The recovery accepts only the measured mixture of raw `80,40` and `84,40`.
Already-targeted units are never rewritten: their lock and voltage status are
verified first. A lock value 0 is changed only to 1 and read back. The first
remaining raw-80 unit becomes the recovery canary. For unlock, limit, and
relock writes, a transport-level acknowledgement failure is recoverable only
when an immediate independent read returns the exact requested value; otherwise
the sequence halts and follows the relock/torque-off path.

This is a fail-closed refinement of configuration evidence, not retry-based
error suppression. It changes no runtime transaction taxonomy, timing gate,
policy contract, torque behavior, or motion authority.

## D031 — Retry only independent configuration readback, never the write

Accepted after the first D030 recovery halted safely. ID 30's maximum write ACK
timed out, then its first independent limit read timed out; the final audit read
raw `84,40`, proving the single write landed. Its emergency relock ACK was
partial, while the immediate lock read returned 1. The final state is fully
known and all touched units are locked.

The next recovery permits exactly three attempts for a required configuration
read. Each attempt flushes stale input, transmits a new READ instruction, and is
journaled. It does not retransmit an unlock, maximum, or relock write. A write
ACK error is recoverable only after exact readback; a wrong value or three
failed reads remains a hard halt. This bounded read-only mechanism addresses
the observed response loss without chasing an empty error counter or changing
the operational runtime's failure taxonomy.

## D032 — Accept the verified all-14 8.4 V alarm configuration

Accepted as configuration evidence only. The final recovery verified lock 1
and clear voltage status on the six already-targeted units, then updated only
the eight remaining raw-80 units. Final reads returned raw `84,40`, device
status 0, and 8.2-8.4 V on every servo. Initial/final torque-off were `ok`, all
known unlocked units were relocked, and the operation issued no torque enable,
goal position, minimum-limit, policy, or motion command.

Three maximum-write acknowledgements and their first independent readbacks were
lost; each second read returned exact `84,40`. No write was retransmitted. This
supports the bounded configuration-readback rule but does not alter runtime
error classification or establish timing determinism.

The voltage-alarm blocker is cleared. Gate 2 remains blocked by the independent
authoritative complete-sweep maximum above 5 ms. Only the separately
preregistered fixed-length collector A/B can replace that timing evidence.

## D033 — Attribute the legacy collector failure before another hardware run

Accepted as read-only analysis of the preserved USB and direct-UART 10,000-tick
traces. The old incremental collector started its deadline before request setup
and parsed/compacted after every short read. On UART, failed ticks averaged
2.29 application reads versus 7.39 on clean ticks, while the late wire-order
IDs 11-14 accounted for all 145 grouped failures. Fewer reads correlated with
larger chunks, longer parse tails, and lost late logical responses; kernel byte
counters had already shown that the physical driver received the expected
volume.

The analysis supports the preregistered exact-length collector as a causal
test, not as a presumed pass. Direct UART was 77 us faster in mean complete
sweep than USB but added 424 us to request-return-to-first-response latency and
did not change the maximum materially. Adapter bandwidth and servo-count
capacity are therefore not selected as the remaining cause.

## D034 — Exact-length collection fixes late IDs but not the bus budget

Accepted as a reviewed torque-off hardware result. All 10,000 response trains
were collected to exactly 140 bytes and parsed once; the last observed response
completed at least 791 us before the post-write deadline on every tick. Grouped
failures fell from 145 to one CRC, with zero bursts, zero alarms, zero drops,
and final torque-off `ok`. This proves the `…12,14,13` all-servo bus is capable
of returning its complete ordered response train inside the receive deadline.

The unchanged complete-sweep gate still failed: mean/p99.9/max was
`5.655528/8.067290/8.352496 ms`. Exact collection reduced mean receive span by
367 us but increased the post-receive generic parse tail by 717 us; the state
decode then added another 577 us mean and 1.170 ms max. The repaired collector
is accepted for correctness but closed as a sufficient timing remedy.

The next offline candidate is a fixed-frame parser/decoder specialized to the
known 14 × 10-byte ordered SyncRead train, retaining the generic parser only for
explicit anomaly recovery. It must preserve every status, checksum, ID-routing,
staleness, and instrumentation invariant and be benchmarked before a separately
authorized torque-off A/B. Tick p99/p99.9 passed, so the preregistered Rust
escalation criterion remains false.

## D035 — Do not spend a serial run on parser speed alone

Accepted after source-bound CPU-only benchmarking on the X5. The fixed-order
parser preserves status, staleness, position, and velocity outputs and is
1.92× faster without transaction tracing. Under the ten-chunk instrumentation
matching the hardware diagnostic, it saves 259 us mean. That improvement is
smaller than the measured 656 us mean deficit and cannot reasonably clear the
8.352 ms maximum by itself.

The fixed parser remains the correct normal-path implementation with generic
anomaly recovery, but it is not independently promoted to another 10,000-tick
serial run. This prevents sampling another predictable gate failure merely
because the implementation is faster in isolation.

## D036 — Test RT CPU frequency before changing bus architecture again

Accepted and executed as a one-variable hardware hypothesis. In the
exact-collector trace, group parse tail and
read-call count correlate at `-0.953669`: fewer wakeups precede dramatically
slower parsing. The entire CPU cluster remains on `schedutil` with a 300 MHz to
1.5 GHz range, so the isolated 50 Hz loop can wake below maximum frequency.

The continuous CPU benchmark showed no governor benefit because it keeps the
core busy. The falsification must therefore use the matched 50 Hz serial
population: rerun the accepted exact collector while changing only policy0 to
`performance`, then restore `schedutil`. A material relative improvement is
preregistered, but Gate 2 still requires the absolute `<5 ms` maximum. Failure
stops the branch; it does not authorize a parser/no-instrumentation combination
or a threshold change.

The authorized 10,000-tick arm B changed only policy0 to `performance` and
passed. Complete-sweep mean/p99.9/max fell from
`5.655528/8.067290/8.352496 ms` to
`4.115062/4.522262/4.821428 ms`; tick p99/p99.9 was
`20.002755/20.005297 ms`, with zero failures, bursts, alarms, or drops. The
runner restored `schedutil`. This passes both the preregistered causal threshold
and the absolute bus budget, identifying CPU-frequency scaling as the remaining
host-tail cause for this probe. It is torque-off preflight evidence, not moving
Gate 2 clearance.

## D037 — Require a verified performance governor for subsequent timing gates

Accepted from D036. Any subsequent Gate 2 timing run must verify policy0 is
`performance` before serial startup and preserve evidence of that state. A
reviewed fail-closed launcher must restore the prior governor on normal exit,
failure, or signal. The standalone A/B runner is not reused as a moving runner,
and no moving gate is authorized by this decision.

Implemented offline in `setup/run_gate2_home_hold.sh`. The launcher freezes the
source/config hashes and first runs a complete source-matched 10,000-tick
torque-off preflight under `performance`. A tested validator checks both direct
statistics and summary gates; only a pass can reach the five-second home entry
and 10,000-tick hold. The home-entry loop now feeds the same hard-overrun
watchdog as the hold. Execution remains `NOT_AUTHORIZED_NOT_RUN` under the
separate current pre-registration.

## D038 — Apply the hard-overrun watchdog during full-runtime home entry

Accepted from the completion audit. The Gate 2 probe already enforced the
`>40 ms` hard-overrun rule while moving home, but the policy runtime only began
observing that rule after home entry. The full runtime now measures each
home-entry period and work duration with the same watchdog instance used by the
control loop. A trip propagates through `TorqueGuard`, disables torque, and is
covered by an injected-overrun cutoff test. This changes no home trajectory,
gain, policy, observation, action, or timing threshold.

## D039 — Accept the performance-governed all-14 home hold as Gate 2

Accepted as a reviewed hardware result. The exact frozen launcher first ran a
10,000-tick torque-off preflight and permitted the moving stage only after the
independent validator passed. The five-second measured-position-to-home entry
then completed under the same hard-overrun watchdog, followed by a 10,000-tick
home hold with no policy and zero target amplitude.

Preflight and home-hold tick p99/p99.9 were respectively
`20.002520/20.006060 ms` and `20.002683/20.008892 ms`. Complete-sweep maxima
were `4.532473 ms` and `4.721847 ms`. All 320,000 expected responses across the
two stages succeeded, with zero bursts, stale samples, alarms, unexpected or
partial responses, and telemetry drops. Final torque-off was `ok`, the serial
endpoint was released, and the launcher restored `schedutil`.

The extra all-joint review found a worst hold p95 error of `0.005516521 rad`.
This is recorded but was not used as a post-hoc Gate 2 threshold. Extended
telemetry observed 6.9-8.4 V and 29-42 C with zero alarm replies. Gate 2 is
`PASS_REVIEWED`; Gate 3 and every policy or grounded operation remain outside
this decision's authority.

## D040 — Require inherited BNO055 calibration and identity proof

Accepted offline before Gate 3. The preserved policy runtime loads
`imu_calib_data.pkl` and applies accelerometer, gyroscope, and magnetometer
offset triplets. The first sensor probe omitted that path, so it could have
produced fresh, correctly shaped, but contract-different IMU evidence.

Hardware sensor startup now requires a strict JSON profile converted through a
primitive-only restricted unpickler. The profile binds the legacy pickle hash;
the driver verifies chip ID `0xa0`, writes all three triplets in configuration
mode, and requires exact register readback before entering NDOF. Gate 3 also
records sensor-worker errors and installed source hashes. Its nine-label
validator can establish data integrity only; physical orientation and switch
labels remain `REVIEW_REQUIRED` under D017. No board access is authorized by
this decision.

## D041 — Block Gate 3 on the missing physical calibration

Accepted from the authorized non-moving readiness inventory. The preserved
runtime contains a calibration script and CWD-relative load path, but no
`imu_calib_data.pkl` or other IMU calibration artifact exists anywhere under
`/home/sunrise`. The powered BNO055 identifies correctly as `0xa0` but reports
calibration `0x00` and remains in its default axis/unit configuration. There are
no valid offsets to convert.

Offsets will not be guessed or copied from a different robot. Gate 3 stays
blocked—not failed—until this physical BNO055 is calibrated and the resulting
profile is hashed and read back exactly. The same inventory verified BCM22 as
X5 GPIO 388 and BCM27 as GPIO 379 through temporary input-only claims, then
confirmed clean release. No servo device, torque, target, or policy was touched.

## D042 — Capture this robot's calibration transactionally before Gate 3

Accepted offline to resolve D041 without guessing offsets or weakening the
frozen sensor contract. The new `calibrate_imu` path is isolated from every
servo, torque, target, and policy module. Its X5 backend requires the two normal
hardware acknowledgements plus an exact manual-calibration acknowledgement
because Rob must physically support and reorient the robot.

The candidate is not based on a single momentary status value. The BNO055 must
report system, gyroscope, accelerometer, and magnetometer level 3 for five
consecutive samples. The tool then captures the three inherited offset
triplets, closes the device, and applies them through the production BNO driver
in a fresh session. Exact chip identity, frozen axis mapping, units, NDOF mode,
and offset-register readback are mandatory. Output is staged and published as
one directory only after verification succeeds; interruption, timeout, failed
readback, or a pre-existing destination produces no accepted candidate.

The output includes a primitive legacy-compatible pickle solely to preserve
the existing source-format/hash contract, a strict JSON runtime profile, a
bounded status stream, and a source-bound review summary. Mock output remains
informational. An X5 capture is only `REVIEW_REQUIRED`; it cannot clear Gate 3
or authorize any policy operation.

## D043 — Accept the physical calibration data, not Gate 3

Accepted as a separately authorized, no-servo prerequisite result. Rob was
physically present and manually reoriented the supported robot. The BNO055
stream reached all-four level 3 and sustained `0xff` for the preregistered five
samples. Across 1,318 rows and 330.934491 seconds, the captured accelerometer,
gyroscope, and magnetometer offset triplets were `[118, 0, 33]`, `[1, 0, -2]`,
and `[-421, -125, 360]`.

A fresh production-driver session reapplied and read back all nine values
exactly with the frozen identity, NDOF, axis, sign, and unit registers. An
independent verifier reconstructed the status stream and rehashed the primitive
source, strict profile, raw status, summary, frozen source archive, and source
modules. Profile SHA-256 is
`e7518b0df8614c1d399c789fd26aa9888043ebacfccc98ef75a5010a4b8c34be`;
source SHA-256 is
`a3552b357dc2d0e6a876c8e8406134ab36fa6e88a7b7f444c9f9d25122a9da08`.

The board lacked the declared `smbus2` dependency, so version 0.6.1 was
installed reversibly in Sunrise's user site from a locally hashed wheel. No
servo endpoint was opened; torque, goal writes, policy loads, and inference
counts remained zero. This decision clears D041's missing-profile blocker only.
The nine labeled Gate 3 matrix remains separately unauthorized and not run.

## D044 — Reject the first Gate 3 label and require sensor publication readiness

Accepted from the first separately authorized nine-label attempt. The frozen
launcher captured the requested 250 `upright` rows, then stopped before the
second label because the per-label validator found stale IMU and contact data
at row 0. The runner recorded `HALTED_LABEL_VALIDATION`, no completed labels,
no servo-bus access, no torque, no goal writes, and no policy activity.

The raw stream hash is
`0236adf1481dcdd7e921451ffa00fe0b90ef7c5f2d1fc1a048e63d8e30214454`.
Only row 0 is stale and carries zero device timestamps. Row 1 is already fresh
at 6.413058 ms IMU age and 6.065933 ms contact age; every later row is fresh,
and the worker reports zero device errors. This identifies a startup race
between background-worker creation and the ticker's immediate first release,
not a calibration, label, I2C, or GPIO failure.

The accepted correction is a bounded 2.0-second initial-publication barrier.
The probe and runtime wait for a complete immutable sample, read it once, and
reject it if already stale before starting the capture ticker or reaching
servo verification and torque enable. Timeout is fail-closed and creates no
probe evidence. The failed output remains immutable; corrected execution uses
a new frozen source archive, a new output directory, green CI, and new explicit
authorization. Gates 4 and 5 remain blocked.

## D045 — Accept the corrected nine-label sensor matrix as Gate 3

Accepted from the separately authorized, supported-robot run on 2026-07-19.
The corrected source commit `aac7410f241a5419af2257ba9635e6755d7b5ae8`
waited for a complete fresh publication before defining each 250-row capture.
All nine labels completed, all 2,250 IMU/contact rows were fresh, every sensor
worker reported zero errors, and all 67 board-side checksum entries reproduced.

Rob physically confirmed each label immediately before capture. Independent
raw reduction found upright mean acceleration `[0.38476, 0.91704, 9.79360]
m/s²`; nose-forward/back X means `-5.00064/+6.85560 m/s²`; and left/right
tilt Y means `-7.88388/+7.20860 m/s²`. The corresponding opposing separations
were `11.85624` and `15.09248 m/s²`. The four dedicated contact populations
were exactly `[0,0]`, `[1,0]`, `[0,1]`, and `[1,1]` across 1,000 samples.

The upright orientation capture recorded four simultaneous true samples per
contact, a mean of `0.016`. This is retained in the review rather than erased;
it does not override the preregistered contact decision, which is based on the
four dedicated, physically confirmed populations and passed exactly.

The runner proves no servo bus, torque, goal write, policy load, or inference.
After completion I2C was unowned, both GPIO claims were released, and the
screen session had exited. The automated packet remains deliberately
`REVIEW_REQUIRED` with `gate3_passed=false` under D017. The separate human
review resolves the unambiguous physical labels and promotes Gate 3 to
`PASS_REVIEWED`. This does not authorize Gate 4, a policy, or grounded work.

## D046 — Accept the policy handoff as a versioned v2 requirement, not v1 compatibility

Accepted as an offline interface decision. Policy commit
`ad1cd8e9b9fdacd26a5453318411dafe423588b4` provides a hash-bound package with
manifest SHA-256
`ba7143f5c653c0bb2f3f27930a7997dd5a2b90e3258bca516b7240bd0f21abd7`.
The package checker and an independent full 2,400-tick CPU replay pass within
the frozen `1e-6` tolerance; both protected graphs are unambiguously stateful
115-D policies.

This evidence does not change the frozen 101x14.v1 contract. Winner-v2 requires
P30 observer state at `obs[83:97]`, projected-reference `obs[101:115]`, explicit
14-D recurrent action state, graph-owned bounds/guard/deadband, no head overlay,
and an asserted-identity host limiter. Observe-before-advance ordering matches,
but reset does not: v1 begins phase at `[0,0]`, while v2 requires `[1,0]`.
Substitution changes tick-0 moving output by up to `0.04923201` normalized
action, so v1's phase object cannot be reused unmodified.

Only a separately specified, default-off, versioned v2 implementation and
golden verifier may follow. No single policy checkpoint is selected, the
real-build COM calculator still lacks 46 inputs, policy-side robot clearance
is false, and no Gate 5, deployment, RDK-X5, or robot action is authorized.

## D047 — Accept the policy-side 512000 checkpoint selection

Accepted as an offline asset-selection decision, not deployment authority.
Policy evidence commit `e0badd7aa79ff791212b8d3822f9eefdc4c162e0`
preregistered and ran one native-quantized sibling matrix. Both checkpoints
passed all eight cells; the frozen first criterion selected 512000 on lower
worst tracking p95 (`0.1809259653` versus `0.1818299592 rad`). Reward and
training curves carried no weight.

The selected ONNX SHA-256 is
`99d3afce0dfac127816c6327665c35b3c403e005f25cd0a505dfcb37f01304de`.
The 1024000 graph remains audit-only. This closes D046's checkpoint-selection
blocker only; it does not clear runtime-v2, COM, Gate 5, or the robot.

## D048 — Hold runtime-v2 on reviewed semantics, not forced bit identity

Accepted as an offline implementation disposition. The isolated/default-off
115-D transaction matches all four golden observation tensors bit-exactly and
passes its semantic, frozen-observation ONNX, x=0, and fault-injection checks.
It also exposed that handoff metadata labels action histories one tick too new:
the golden contract is `t-2/t-3/t-4`, while stateful `previous_action` is
`t-1`. The policy repository committed the metadata-only correction, and this
runtime independently reproduced its v1.1 manifest and all 2,400 history rows.

On this CPU, fully recursive float32 feedback reaches `2.3841858e-6` for the
selected graph even though its target error stays `5.9604645e-7 rad`. No host
rounding, output projection, or post-hoc relaxation is accepted. Runtime-v2
remains held until a prospective cross-CPU recursive metric is reviewed. V1
remains unchanged and Gate 5 remains `NOT_RUN`.

## D049 — Prefer the contracted direct-reaction torso-COM route

Accepted as an operator-data route only. Policy commit `e5e9fb8` contracts a
powered-off two-support measurement of the complete torso-fixed deployment
assembly. Its exact blank template SHA-256 is
`30229a80df15292bc36bcb143c28c46838bf826856ebd00cf156e2654c93af55`.
It uses three unload/reload trials, simultaneous support reactions, an
independent same-specimen mass, conservative uncertainties, and a minimum
complete-uncertainty support separation of `0.060 m`.

The 46-field component inventory remains a fallback. Neither blank template is
a measurement result. Physical completion and the policy calculator decision
remain required; this decision authorizes no RDK-X5 access, torque, policy, or
motion.

## D050 — Accept the post-preregistered recursive wire-closure pass

Accepted as an offline CPU result, not X5 or robot clearance. Policy commit
`182459eb4d5eb422a6936b7744f5730d22a9bb27` prospectively froze a separate
recursive metric derived from half one native STS3215 position count
(`0.0007669904 rad`), while preserving the original `1e-6` same-input ONNX
rule. It assigned zero formal weight to the earlier runtime maximum and forbids
rounding, quantization, output projection, or graph changes.

The formal new 2,400-tick invocation passes as
`PASS_RECURSIVE_BIT_EXACT_WIRE_CLOSURE`. On the selected 512000 graph, maximum
logical-target and P30 differences are `5.9604645e-7` and `5.6025073e-7 rad`.
After adding the frozen real soft offsets and running the exact checked-in
`rad_to_raw_position`, all 16,800 selected STS goal words are identical: zero
count mismatches and zero maximum count difference. Saturation, measured-rate,
envelope, and inherited-5.24 classifications remain unchanged. The 1024000
sibling is reported but non-gating.

The full result SHA-256 is `e1842ca6...049b14`. The same deterministic
invocation emits the requested reduced four-cell decision packet with SHA-256
`4d403623...85ace`; that packet binds the full result hash and records every
cell's platform/provider, decision gates, maxima, per-joint values, and raw
word comparison.

This closes the Windows CPU recursive-numeric blocker only. Policy-side
independent reproduction, physical torso COM, robot clearance, frozen assets,
and the same no-servo X5/AArch64 CPU metric remain required. V1 is unchanged;
Gate 5 remains `NOT_RUN`.

## D051 — Accept independent CPU closure and freeze offline asset identities

Accepted as an offline identity decision only. Policy commit
`fab1feaa8d136fed0ab33d5590d0eec88ef90d8f` independently checked the formal
Windows result and reconciled it with a separate Linux CPU replay. Both decide
`PASS_RECURSIVE_BIT_EXACT_WIRE_CLOSURE`; the selected raw STS goals are
bit-exact on both platforms. This closes the reviewed CPU recursive-numeric
blocker.

The hash-only offline asset lock pins the selected 512000 ONNX, corrected v1.1
handoff manifest, P30 fit, projected reference, policy contracts, live board
config hash and semantics, physical offsets, runtime implementation/conversion,
and both sides' formal evidence. Its SHA-256 is
`4da893b39c98d155fb0a0154a47dc46453a72b92d9d9855b5563746fa34de940`.
The policy binaries remain external and are not committed here. The verifier
checks 7 runtime files, 2 runtime evidence files, 6 external package files,
and the policy acceptance result.

This does not freeze a Gate 5 launcher or grant X5/robot authority. Powered-off
torso COM, policy `robot_clearance=true`, the same no-servo X5/AArch64 replay,
and a separately reviewed Gate 5 launcher remain required.

## D052 — Hold the stale asset lock and correct exact-observation reporting

Accepted. Policy commit `bc4132b8a7a9db28e32bb873747c164b3a3abb4d`
found that the reduced recursive report labeled teacher-forced observation as
`<=1e-6`; the preregistered requirement is exact zero. All four committed
values are already exactly `0.0`, so this does not change the formal full
result, policy graph, thresholds, or accepted wire-closure decision.

The runtime changed only the reduced gate to exact equality and regenerated
the reduced report directly from unchanged full-result SHA-256
`e1842ca6...049b14`, without ONNX inference or formal outcome rerun. Corrected
reduced SHA-256 is `1292772e...65dc5e`.

Asset-lock SHA-256 `4da893b3...de940` is now historical and must not be
promoted. The asset-lock verifier rejects that exact revoked hash before
examining the lock. Policy must independently validate the correction and
commit its final result identity before the runtime regenerates the final
lock. Physical COM, X5, Gate 5, deployment, and robot clearance remain
blocked.

## D053 — Regenerate the revalidated offline asset lock for policy review

Accepted. Policy commit `4c99b5e3be203af419536382f11f3cce98283ba2`
independently reproduced corrected reduced SHA-256 `1292772e...65dc5e`, reran
the complete 2,400-tick Linux CPU matrix, confirmed exact-zero teacher-forced
observation closure, and committed acceptance-result SHA-256
`5380897c...b7ddc`. The formal result remains byte-identical at
`e1842ca6...049b14`.

Accepted as the runtime-side replacement-lock candidate. The regenerated
offline asset lock has SHA-256 `48fd6d81...f64ef31`; its
verifier passes 12 committed runtime files, two runtime evidence files, six
policy-package files, and the exact policy acceptance result. Superseded lock
SHA-256 `4da893b3...de940` remains explicitly revoked.

Policy-side review of the replacement lock remains required before final asset
freeze. Powered-off torso COM, policy `robot_clearance=true`, no-servo
X5/AArch64 replay, a separately reviewed Gate 5 launcher, and separately
authorized suspended replay also remain required. No hardware or motion
authority is granted.

## D054 — Close the two-repository winner-v2 offline asset freeze

Accepted. Policy commit `4521cd8fdcf5603dfb1405417ce38cd2f031fd84`
independently reviewed replacement-lock SHA-256 `48fd6d81...f64ef31`
against runtime commit `290fe4726a0310c1a368767ce900340a52eba412`.
All 46 policy checks pass, the issue list is empty, and the exact policy review
result has SHA-256 `53351707...aadea`.

The runtime preserves an exact byte-identical snapshot of that result and a
non-circular closure artifact with SHA-256 `281382bb...83110`. Its executable
verifier binds the reviewed lock, runtime verification, policy review,
selected ONNX, corrected handoff, live config, and formal/reduced results, and
returns `PASS_FINAL_OFFLINE_ASSET_FREEZE`.

This closes the offline asset-freeze gate. Powered-off real-build torso COM,
policy `robot_clearance=true`, no-servo X5/AArch64 replay, a separately
reviewed Gate 5 launcher, and separately authorized suspended replay remain.
No hardware or motion authority is granted.

## D055 — Replace per-build COM measurement with variable-configuration robustness

Accepted. Open Duck Mini is expected to be disassembled, reassembled, and
operated with supported optional non-locomotion pieces present, absent, or
repositioned. A millimeter-specific torso COM measurement for one assembly is
therefore not a valid deployment prerequisite. The direct-reaction and
component-level worksheets are retained as historical records but are no
longer selected advancement routes. No scale, caliper, disassembly, manual COM
entry, or equipment purchase is required from the operator.

The reviewed winner-v2 asset freeze remains valid evidence for the exact
candidate. It does not erase the policy-side X-COM break-radius result: the raw
bracket passes through `-22.65625 mm/+5.46875 mm` and fails at
`-23.4375 mm/+6.25 mm`. That sensitivity is now classified as a policy blocker,
not a request to characterize one build more precisely. The candidate remains
at `robot_clearance=false` and Gate 5 remains `NOT_RUN`.

The selected route is a policy-side, preregistered CPU-only gate over a
supported configuration envelope including torso mass, X/Y/Z COM, inertia,
coupled variations, and optional-component combinations. The X envelope must
at minimum include the already tested `[-50 mm,+50 mm]` range. A failing
candidate must be retrained or replaced; it cannot advance through a per-build
measurement waiver. Any new graph or package requires a new two-repository
asset freeze.

Runtime startup remains fail-closed for missing contract-required actuators or
sensors. A future automatic supported-calibration mode may estimate effective
dynamic response without manual physical measurements, but physical excitation
still requires separate motion authorization. This decision grants no robot,
RDK-X5, torque, motion, deployment, or Gate 5 authority.

## D056 — Implement the automatic configuration-support decision layer

Accepted offline only. `configuration_support.py` defines strict versioned
contracts for a machine-collected supported-excitation profile and a
policy-provided robust configuration envelope. It intentionally validates
observable response quantities instead of claiming that stationary sensors can
identify an exact torso COM. Profile fields cover per-joint delay, gain, time
constant, tracking, current, and body IMU response. Static entered mass, COM,
inertia, scale, caliper, and component measurements have no accepted field.

The policy envelope must bind an exact ONNX and preregistration, require no
per-unit physical measurement, record a passed robustness gate, cover at least
`[-50 mm,+50 mm]` torso X-COM, span nominal mass/Y/Z/inertia, include coupled
and held-out samples, and identify multiple supported optional-part
configurations. The validator checks all 73 observable metrics and fails closed
for missing contract hardware, incomplete/faulted telemetry, or any response
outside the policy bounds.

This implements only the offline decision layer. The physical excitation
collector remains `NOT_RUN` and must be separately reviewed before any motion.
A passing comparison still carries `robot_clearance=false`, `gate5=false`,
`runtime_deployment=false`, and `motion=false`. Neither the frozen 101-D v1 nor
the separate 115-D winner-v2 policy contract changes.

## D057 — Generate the automatic profile from raw response evidence

Accepted offline only. `configuration_profile.py` defines strict metadata and
tick-stream schemas for future supported excitation. It requires a complete
50 Hz population, the frozen hardware inventory, one contiguous stage per
joint in frozen order, fresh/ok servo and sensor data, automatic round-robin
current coverage, explicit motion authority, supported state, zero telemetry
drops, and confirmed final torque-off. It rejects every extra metadata or tick
field, including attempted static COM/mass/inertia input.

The extractor enforces isolated single-joint excitation, no more than
`0.06 rad` target span and `0.25 rad/s` target velocity, then fits bounded-delay
first-order response directly from targets and measured positions. It derives
all 70 joint metrics and three body metrics required by D056 and validates the
generated profile before writing it. Synthetic evidence recovers the injected
two-tick delay, `0.9` gain, and analytic time constant for every joint. Fault
tests reject discontinuity, staleness, cross-joint excitation, excessive rate,
and insufficient current coverage.

The emitted v2 profile binds the raw trace, metadata, and exact
`duck_config.json` by SHA-256. Metadata physical home must equal frozen home
plus the config's ordered soft offsets. The final support validator regenerates
the entire profile from those three inputs and rejects any structural mismatch
or numeric difference above `1e-9`; hash strings alone are not evidence.

This is not a physical collector or motion launcher. No serial, GPIO, I2C,
torque, policy, robot, or RDK-X5 path was added. Physical collection remains
`NOT_RUN` and separately authorized. The frozen policy contracts are unchanged.
