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
