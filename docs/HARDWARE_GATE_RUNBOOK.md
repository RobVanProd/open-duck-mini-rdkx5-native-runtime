# Staged Hardware Gate Runbook

Gates 1 through 4 are `PASS_REVIEWED`. Gate 2 completed its frozen 10,000-tick
torque-off preflight, five-second home move, and 10,000-tick home hold under the
verified temporary `performance` governor, then confirmed torque-off and
restored `schedutil`. Gate 3 completed the corrected nine-label BNO055/contact
matrix with no servo path. Gate 4 completed its frozen two-frequency sine
sequence. Gate 5 attempt 1 halted while paused after zero active policy ticks;
it did not pass. Authorization for one gate or attempt does not authorize the
next.

## Common preflight

1. Record repository commit, config SHA-256, policy SHA-256 if applicable, board image/kernel, Python version, serial driver, baud, USB topology, CPU isolation, scheduler, and operator.
2. Confirm hands clear, robot supported, power cutoff reachable, and `start_paused=true`.
3. Run `taskset -c 0-7 setup/verify_rt_setup.sh 7 80` and `setup/verify_serial_path.sh /dev/ttyS1`; attach output. An SSH login inherits housekeeping-only affinity after `isolcpus`, so the explicit initial mask is required to reproduce the reviewed service configuration. RT verification must show exact isolation membership plus successful affinity and `SCHED_FIFO` tests. Timing gates must also verify policy0 is `performance` before serial startup and restore the prior governor through the reviewed launcher.
4. Pre-register duration, commands, failure threshold, consecutive-failure watchdog count, and stop conditions in the gate artifact.
5. Use both CLI acknowledgements: `--hardware-authorized --suspended-or-benched`.
6. Stop on unexpected motion, wrong joint/side/sign, hard overrun, any burst of read failures, or operator concern.
7. A missing telemetry tick, queue overflow, or writer failure invalidates the run; it cannot be reported as `COMPLETE`.

## Gate 1 — Bus echo and one servo

- Torque remains off unless a specifically approved single-servo position step is part of the authorization.
- Ping one known ID; read position; read extended telemetry; measure at least 10,000 transactions at the intended timeout.
- Report timeout, CRC, partial, device-error, and unexpected-ID counts separately.
- Do not advance if the serial driver/tunable is unknown or the response framing is inconsistent.

The dedicated Gate 1 probe establishes torque-off, pings the selected frozen
ID, and then times only its present-position transaction. It never sends a goal
position:

```bash
probe_single_servo --bus serial --servo-id 20 --ticks 10000 \
  --watchdog-failures 2 \
  --hardware-authorized --suspended-or-benched \
  --output gate1-id20.jsonl --summary gate1-id20-summary.json
```

Its summary preserves all zero/nonzero error classes and failure bursts. This
single-servo result does not satisfy Gate 2's all-14 timing requirement.
It also binds the raw JSONL SHA-256, both hardware assertions, final torque-off
status, and unexpected response-length count. `gate1_candidate=true` still
means `REVIEW_REQUIRED`; it never authorizes Gate 2.

Reviewed 2026-07-15 result: servo 20 completed all 10,000 reads with zero
failures, zero bursts, zero response-length mismatches, p99.9 round trip
`0.998007 ms`, tick p99.9 `20.090855 ms`, and final torque-off `ok`. See the
Gate 1 artifact directory. Gate 2 remains unauthorized.

## Gate 2 — Fourteen-servo home hold, no policy

Current status: `PASS_REVIEWED`. The chronology below retains the failed and
superseded diagnostics that led to the passing configuration; statements that
Gate 2 was blocked describe those historical stages, not the current gate
decision. The ID-13-last wire-order repair removed the reproduced CRC
mechanism, but the earlier repeated torque-off preflight had one device-status
reply, `0.125%` failures, and `7.703526 ms` max bus time. The 50 Hz tick p99.9
was green at `20.101307 ms`. Torque was never enabled in that preflight.

The separately authorized official WCH CH343 driver experiment produced zero
transaction failures but total bus mean/max remained
`5.437868 / 7.490049 ms`. It was rejected and fully rolled back to `cdc_acm`.
Do not repeat that driver experiment as an unmeasured preference change.

The separately authorized latency diagnostic is documented in
`USBMON_LOGIC_ANALYZER_DIAGNOSTIC.md`. Rob clarified that the intended scope is
the on-device application trace plus `usbmon`; no external analyzer exists or
is required. Label it `software-usbmon` and do not claim physical-wire timing.

The first software-only capture halted at startup because the then-current
parser classified all 14 status-`0x01` replies as invalid samples. It sent only
the initial and final
all-14 torque-off writes plus one SyncRead; it never entered the timing loop or
wrote a goal position. The captured startup exchange delivered all 14 responses
in `2.130 ms`, so it already rejects the hypothesized one-millisecond-per-servo
USB floor. The historical stop was correct under its preregistered parser and is
not retroactively promoted to a Gate 2 result. See
`artifacts/gates/phase_7_hardware/gate_2_all14_home/software_usbmon_voltage_halt/RESULT.md`.

After a connection inspection and robot reboot, one explicitly authorized retry
reproduced `0x01` on all 14 replies and again stopped before the loop. The second
fourteen-response interval was `2.125 ms`. Do not repeat the same capture; a
present-voltage register read is the next distinct torque-off diagnostic and
requires separate authorization. See
`artifacts/gates/phase_7_hardware/gate_2_all14_home/software_usbmon_voltage_halt_retry/RESULT.md`.

Rob subsequently authorized that distinct read-only diagnostic. Its frozen
scope is register 62 only, one byte per servo, with torque-off before and after,
the physical order ending `14,13`, and no position or configuration write. The
diagnostic preserves a voltage byte from a valid device-error response for
evidence only; the then-current operational parser rejected it as stale. D023
later superseded that parser classification while retaining the alarm as a
separate safety condition. See
`artifacts/gates/phase_7_hardware/gate_2_all14_home/VOLTAGE_DIAGNOSTIC_PRE_REGISTRATION.md`.

The authorized read completed all 14 responses: every servo reported status
`0x01` and measured `8.2-8.4 V`. This proves the common rail is present but does
not establish whether the units are a 7.4 V variant with an 8.0 V maximum or
have another configured limit. Do not change supply or EEPROM values. A new
authorization is required to read model/version registers 3-4 and voltage-limit
registers 14-15. See
`artifacts/gates/phase_7_hardware/gate_2_all14_home/voltage_diagnostic/RESULT.md`.

Rob authorized that exact all-14 read and broader autonomous read-only diagnosis
while motors remain de-energized. The frozen first step reads only addresses 3
and 14, two bytes each, with torque-off before/after and zero EEPROM writes. See
`artifacts/gates/phase_7_hardware/gate_2_all14_home/VOLTAGE_LIMIT_DIAGNOSTIC_PRE_REGISTRATION.md`.

The read completed with identical raw version bytes `0x03,0x09`, configured
maximum `8.0 V`, configured minimum `4.0 V`, and a live `8.2-8.4 V` rail. It
proved the configured-threshold relationship, but not a servo SKU or an
incorrect physical supply. Subsequent provenance review confirmed that Frank's
documented build follows the upstream two-cell-series, nominal-7.4 V design; a
charged 2S pack normally reaches this measured range. D023 therefore replaces
the old power-fault conclusion with separate transport-validity and
device-alarm semantics. Do not mask the alarm or raise EEPROM limits. See
`artifacts/gates/phase_7_hardware/gate_2_all14_home/voltage_limit_diagnostic/RESULT.md`.

The corrected software preserves a checksum-valid alarm-bearing payload as
fresh, records the raw per-servo device status separately, and reports both
device-alarm and voltage-alarm reply counts. Runtime startup and any
torque-capable probe still reject an alarm before torque enable. A future
explicitly authorized torque-off diagnostic can measure the grouped bus without
conflating the alarm with a transport failure, but it cannot pass the
`zero_device_alarms` gate. No power, EEPROM, torque, or policy operation follows
from this software correction. See
`docs/POWER_AND_DEVICE_STATUS_RECONCILIATION.md`.

Read-only attribution on 2026-07-15 reconfirmed that the adapter is WCH/QinHeng
`1a86:55d3`, `/dev/ttyACM0`, bound to `cdc_acm`. It is not FTDI and exposes no
`latency_timer`, so an FTDI 16 ms timer write is neither available nor a valid
test. Before the planned direct-UART A/B, the USB comparison window is now
frozen at 10,000 torque-off ticks. `bus_total_ms` is the sample distribution of
complete tick sweeps—14-target SyncWrite, one `0x82` all-14 position/speed burst,
and one extended read—not a distribution of individual servo transactions.
The grouped-read distribution separately measures one request plus the complete
14-response burst. See `USB_ADAPTER_ATTRIBUTION_20260715.md` and
`USB_10K_TORQUE_OFF_PRE_REGISTRATION.md` in the Gate 2 artifact directory.

That frozen USB run is complete. All 10,000 torque-off ticks and transaction
traces were recorded with final cutoff `ok`. Complete-sweep
mean/p99.9/max was `5.440859/8.060332/8.293083 ms`, with 5,103 sweeps at or
above 5 ms. The `0x82` request plus complete response burst had
mean/p99.9/max `3.575249/5.136984/5.200234 ms`. Tick p99/p99.9 remained green at
`20.101184/20.105310 ms`. Four isolated transport failures among 160,000
expected outcomes yield `0.0025%` with zero bursts. USB therefore fails the
complete-sweep bus gate while Python loop determinism passes. See
`usb_10k_torque_off/RESULT.md`. The next transport A/B is direct X5 UART using
the identical window after Rob performs and verifies the wiring change; it is
not authorized by the USB result.

Rob subsequently removed USB and connected the adapter UART header to X5 pins
8/10 plus ground. Read-only attribution found `/dev/ttyS1` on
`34070000.serial`, driven by `dw-apb-uart`, with UART1 RX/TX pinmux active, no
owner, and zero TX/RX counters. The CH343 is absent from `lsusb`. Rob then
confirmed that the robot is on its stand and directed the preregistered
10,000-tick torque-off A/B to continue. See
`UART_ADAPTER_ATTRIBUTION_20260718.md` and
`UART_10K_TORQUE_OFF_PRE_REGISTRATION.md`.

The UART A/B completed all 10,000 ticks with final torque-off `ok`. Complete
sweep mean/p99.9/max was `5.363831/7.961047/8.353692 ms`; the grouped `0x82`
burst was `3.747957/5.220183/5.347762 ms`. This is not materially better than
USB and fails the same `<5 ms` gate. Tick p99/p99.9 stayed green at
`20.102866/20.127047 ms`. UART had 145/160,000 logical failures (`0.090625%`),
zero CRCs, and zero temporal bursts; exact expected kernel TX/RX byte counts
localize the late-ID timeouts to the 4 ms user-space collection deadline rather
than omitted wire bytes. See `uart_10k_torque_off/RESULT.md`.

Direct UART is closed as the USB-latency remedy. Gate 2 remains stopped. Do not
increase the deadline, relax the bus gate, remove round-robin telemetry, or
escalate to Rust without a new explicit reviewed decision consistent with the
frozen native-escalation rule.

The next software candidate changes the receive collector, not the transport:
the normal four-byte SyncRead now accumulates its known 140-byte response train
before parsing once, and its four-millisecond response deadline starts after the
request write. This is offline-tested only. Transaction trace v2 must show
`mode=exact_length_then_parse`, `parse_calls=1`, and
`bytes_before_first_parse=140` on every normal complete train. The candidate may
be tested on hardware only under the exact scope in
`SYNC_READ_COLLECTOR_AB_PRE_REGISTRATION.md`; until that complete artifact is
reviewed, the earlier USB/UART result remains authoritative and Gate 2 remains
`NOT_RUN_BLOCKED_PREFLIGHT`.

The owner subsequently authorized a separate torque-off EEPROM correction after
confirming the STS3215 upper rating is 8.4 V and that the robot is on its stand.
This is not a Gate 2 timing run. Its frozen scope is in
`VOLTAGE_LIMIT_8V4_CONFIGURATION_PRE_REGISTRATION.md`: preflight all limits,
change only register 14 from raw 80 to 84, use servo 20 as a clean-alarm canary,
verify and relock every servo individually, and retain an fsync'd journal. No
minimum-limit, target, torque-enable, policy, or motion write is permitted.
Gate 2 remains blocked even if the voltage alarm clears.

The first configuration run halted after IDs 20-22 read back 8.4 V; ID 22 lost
both its limit-write and emergency-relock acknowledgements, although final
limit/status reads were clean and final torque-off succeeded. Do not rerun the
uniform-state command. Follow
`VOLTAGE_LIMIT_8V4_RECOVERY_PRE_REGISTRATION.md`: verify/relock the existing
8.4 V units, then resume only at the first raw-80 unit. An acknowledgement loss
counts as recovered only when an immediate exact register readback proves the
write landed.

That recovery verified locks on IDs 20-22, updated IDs 23 and 24, and halted on
ID 30 after its write ACK and first independent read both timed out. Emergency
relock read back 1; the final audit read ID 30 at raw `84,40` with a clear
alarm. The remaining exact recovery is frozen in
`VOLTAGE_LIMIT_8V4_FINAL_RECOVERY_PRE_REGISTRATION.md`. It adds up to three
read-only verification attempts and never retransmits a write. Existing raw-84
units remain read/lock/status verification only.

The final recovery completed from commit `da28f532`: all 14 units now read raw
`84,40`, device status 0, and 8.2-8.4 V; all known locks are 1 and final
torque-off is `ok`. See `voltage_limit_8v4_complete/RESULT.md`. This clears the
voltage alarm only. The subsequently authorized fixed-length collector A/B
completed all 10,000 sweeps and passed its receive contract, but complete-sweep
mean/p99.9/max was `5.655528/8.067290/8.352496 ms`. Gate 2 therefore remains
blocked at that stage by the unchanged `<5 ms` maximum. See
`sync_read_collector_ab/RESULT.md`; no moving command is authorized.

The separately authorized 10,000-tick CPU-governor A/B then changed only
policy0 from `schedutil` to `performance`. Complete-sweep
mean/p99.9/max improved to `4.115062/4.522262/4.821428 ms`; tick p99/p99.9 was
`20.002755/20.005297 ms`, with zero failures, bursts, alarms, or drops. The
runner restored `schedutil`. This clears the torque-off timing preflight and
selects a verified temporary `performance` governor for the eventual moving
Gate 2 launcher. It does not retroactively authorize or complete the moving
home hold. See `cpu_governor_ab/RESULT.md`.

- Verify all 14 IDs before torque enable.
- Slowly move to home, then run SyncWrite plus grouped position/speed read and round-robin telemetry.
- Required: tick p99 <= 21 ms, p99.9 <= 22 ms, zero failure bursts, transaction failure < 0.1%, zero device alarms, total bus time max < 5 ms.
- Hard tick >40 ms or configured consecutive failures immediately torque off.

The moving probe requires a third, gate-specific assertion in addition to the
two common hardware assertions. Do not invoke `runtime_timing_probe` directly
for Gate 2. The frozen launcher first runs the complete source-matched
torque-off preflight and cannot reach torque enable unless the tested validator
accepts every timing and safety gate:

```bash
sudo setup/run_gate2_home_hold.sh \
  --source-archive /home/sunrise/open-duck-x5-a5b5344.tar.gz \
  --config /home/sunrise/duck_config.json \
  --output-dir /home/sunrise/duck-evidence/gate2-home-hold-a5b5344 \
  --hardware-authorized --suspended-or-benched --moving-gate-authorized
```

This command is documentation, not authorization. Its complete frozen scope is
`GATE2_HOME_HOLD_EXECUTION_PRE_REGISTRATION.md`.

Without `--enable-torque`, the serial probe establishes torque-off before it
writes any target packet. It cannot accidentally become a moving test merely
because torque was left enabled by an earlier process.

Serial all-14 probes refuse to run without `--require-realtime`. Their summary
must contain the verified control/background native-thread partition; a timing
summary without that record is invalid for Gate 2 or the Python-to-Rust decision.
The summary must also bind the raw JSONL SHA-256 and show the two hardware
assertions, moving-gate assertion, complete record stream, and final torque-off
status. A serial candidate remains `REVIEW_REQUIRED` even if every numeric gate
is green.

Reviewed result: the frozen performance-governed sequence passed both its
10,000-tick torque-off preflight and 10,000-tick home hold. Home-hold tick
p99/p99.9 was `20.002683/20.008892 ms`, complete-sweep maximum was
`4.721847 ms`, all 160,000 expected transaction outcomes were successful, and
there were zero bursts, alarms, stale samples, or dropped telemetry records.
Final torque-off was `ok` and the governor returned to `schedutil`. See
`artifacts/gates/phase_7_hardware/gate_2_all14_home/RESULT.md`.

## Gate 3 — IMU and contacts

Current status: `PASS_REVIEWED`. The
separately authorized BNO055 calibration prerequisite completed and passed
independent integrity review. The first matrix attempt then halted at the
`upright` validator because row 0 was read before the sensor worker's first
publication. No later label, servo access, torque, target write, or policy ran
in that attempt. The corrected matrix subsequently completed all nine labels.

- No policy.
- Capture labeled upright, nose-forward, nose-back, left-tilt, right-tilt samples.
- Verify `imu_upside_down` against labels, not intuition.
- Verify left/right switches independently; raw false must map to contact true.
- Confirm timestamp age stays within the pre-registered freshness limit.

Collect each physical state as a separate labeled artifact so the operator can
reposition the suspended/benched robot between runs. Do not invoke the probe
label by label. The frozen launcher verifies source, config, calibration,
dependency, I2C ownership, and typed operator confirmation; it validates each
label before allowing the next. It never opens the servo bus, enables torque,
writes a target, or runs a policy:

```bash
bash setup/run_gate3_sensor_matrix.sh \
  --source-archive /home/sunrise/open-duck-x5-gate3-aac7410f241a5419af2257ba9635e6755d7b5ae8.tar.gz \
  --config /home/sunrise/duck_config.json \
  --calibration-dir /home/sunrise/gate3/calibration-20260718 \
  --output-dir /home/sunrise/gate3/sensor-matrix-20260718-readybarrier \
  --hardware-authorized --suspended-or-benched
```

The halted attempt's older source and `sensor-matrix-20260718` output must not
be reused. Its output remains preserved and is reduced under
`startup_stale_halt_20260718/`. The corrected command above was the exact
authorized 2026-07-19 execution and must not be rerun into its existing output.

The launcher prompts in frozen order for `upright`, `nose_forward`,
`nose_back`, `left_tilt`, `right_tilt`, `no_contacts`, `left_contact`,
`right_contact`, and `both_contacts`. Every summary reports sample age,
sensor-worker errors, timestamp repeats, axis distributions, contact fractions,
config/source hashes, and `imu_upside_down`. It also proves the BNO055 chip ID
is `0xa0` and that all three captured offset triplets read back exactly before
NDOF sampling begins. Corrected capture additionally waits at most 2.0 seconds
for an initial complete IMU/contact publication and verifies it is fresh before
starting the exact 250-row population. A timeout stops before label evidence.

The X5 backend requires a strict JSON calibration profile. The readiness audit
found no saved legacy profile, so this robot's own BNO055 was calibrated rather
than guessing or copying offsets. Rob was physically present and supported the
robot throughout the separately authorized no-servo capture. The exact
historical command was:

```bash
calibrate_imu --backend x5 --config ~/duck_config.json \
  --output-dir ~/gate3/calibration-20260718 \
  --imu-bus 5 --imu-address 0x28 \
  --timeout-seconds 600 --poll-seconds 0.25 --stable-full-samples 5 \
  --hardware-authorized --suspended-or-benched \
  --manual-calibration-authorized
```

Keep the supported robot still until gyro reaches 3. Then slowly hold multiple
stable orientations for accelerometer calibration and rotate it through all
three axes for magnetometer calibration. The tool prints all four component
levels. It waits for five consecutive `system/gyro/accelerometer/magnetometer =
3/3/3/3` samples, captures the three contract offset triplets, closes I2C,
reopens the sensor with the candidate profile, and requires exact identity,
axis-map, unit, operation-mode, and offset readback. Only then does it atomically
publish `imu_calib_data.pkl`, `imu_calibration.json`, the bounded status JSONL,
and a summary. Ctrl-C, timeout, or verification failure publishes no candidate
directory. The legacy-compatible pickle exists only to preserve source-hash
provenance; all new runtime consumers use the strict JSON file.

Executed calibration result: 1,318 status rows over `330.934491 s`, ending in
five consecutive `3/3/3/3` samples. Accelerometer, gyroscope, and magnetometer
offsets were `[118, 0, 33]`, `[1, 0, -2]`, and `[-421, -125, 360]`; all nine
values read back exactly in a fresh production-driver session. Profile SHA-256
is `e7518b0df8614c1d399c789fd26aa9888043ebacfccc98ef75a5010a4b8c34be`.
No servo endpoint, torque, target write, or policy was used.

If an authentic legacy `imu_calib_data.pkl` is later recovered, the restricted
primitive-only converter remains available for comparison:

```bash
convert_imu_calibration --legacy-pickle /path/to/imu_calib_data.pkl \
  --output /path/to/imu_calibration.json
```

The launcher validates all nine labeled directories as one frozen matrix before
it can finish. The standalone command remains available for independent review:

```bash
validate_gate3_sensors --run-root gate3 --output gate3-review.json
```

The validator independently rehashes every JSONL file, checks exactly 250 fresh
monotonic rows per label, binds one config/calibration/source population, and
checks the four contact patterns. Orientation/contact correctness remains
`REVIEW_REQUIRED`; neither the probe nor validator manufactures clearance from
unreviewed labels.

Reviewed result: all 2,250 rows were fresh with zero worker errors. Upright
gravity was positive Z; nose-forward/back were opposed on X by `11.85624 m/s²`;
left/right tilt were opposed on Y by `15.09248 m/s²`; and the four
dedicated contact means were exactly `[0,0]`, `[1,0]`, `[0,1]`, and `[1,1]`.
Rob confirmed every physical label. The 67-entry board checksum set and an
independent current-validator pass are recorded under
`artifacts/gates/phase_7_hardware/gate_3_sensors/matrix_20260719/`. Gate 3 is
`PASS_REVIEWED`; this does not authorize Gate 4.

## Gate 4 — Sine sweeps

- Suspended/benched; the frozen joint is `left_hip_yaw` (servo ID 20).
- Frequencies: 0.25 then 0.5 Hz. Amplitude: 0.03 rad.
- Populations: a 10,000-tick torque-off preflight and 10,000 ticks at each
  frequency. The 0.5 Hz population is blocked unless 0.25 Hz passes.
- Required simultaneously: tracking p95 <= 0.011 rad and all Gate 2 timing limits green.

Use the frozen launcher only after its published source/archive hashes have
green CI and Rob gives fresh authorization for the exact moving sequence:

```bash
sudo setup/run_gate4_sine_tracking.sh \
  --source-archive /home/sunrise/open-duck-x5-gate4-<commit>.tar.gz \
  --config /home/sunrise/duck_config.json \
  --output-dir /home/sunrise/duck-evidence/gate4-left-hip-yaw-<date> \
  --hardware-authorized --suspended-or-benched --moving-gate-authorized
```

Timing schema v2 records all 14 sent targets, actual positions, and absolute
errors. The summary calculates tracking p95 directly; a timing-only artifact
with torque disabled reports no valid tracking samples and cannot pass Gate 4.
The independent Gate 4 validator rehashes and reconstructs both sine streams;
only exact 0.25/0.5 Hz, 0.03 rad runs can produce `REVIEW_CANDIDATE`. See
`artifacts/gates/phase_7_hardware/gate_4_sine_tracking/PRE_REGISTRATION.md` for
the complete frozen thresholds and stop rules.

Reviewed result: the exact frozen sequence completed on 2026-07-19. Both
10,000-tick moving populations passed: tracking p95 was `0.006940 rad` at
0.25 Hz and `0.009892 rad` at 0.5 Hz; worst tick p99.9 was `20.010044 ms` and
worst bus maximum was `4.574218 ms`, with zero transaction failures, bursts,
alarms, or telemetry drops. Torque-off and governor restoration were confirmed.
Rob observed smooth motion with nothing weird. Gate 4 is `PASS_REVIEWED`; this
does not authorize Gate 5.

## Gate 5 — Suspended T247 policy replay

**HOLD:** Do not invoke `setup/run_t247_gate5_single_arm.sh`. Attempt 1 on
2026-08-02 halted while paused after zero active policy ticks. A Bluetooth Xbox
HID reconnect was aligned within 17.58 ms of a 90.701 ms grouped-read stall;
the watchdog confirmed torque-off. The old launcher remains historical evidence
and is not a retry command.

T247 still uses its reviewed, default-disabled 115-D two-stage path; the default
101-D v1 path and the candidate policy weights remain unchanged. Before a retry
can be preregistered, the thread-free Linux controller backend must pass its
controller-only screen and a controller-present 10,000-tick torque-off timing
probe. See `T247_CONTROLLER_ISOLATION_REPAIR_PREREGISTRATION_20260802.json`.

The sequence is strict:

1. Run only x=0 after explicit authorization for that exact suspended run.
2. Independently summarize, hash, and review the complete x=0 artifact.
3. Request separate authorization for x=.08 only if x=0 is reviewed green.
4. Run x=.08 as a new launcher invocation. Never chain the two arms.

Each arm contains exactly 850 valid active ticks: 250 calibration ticks and 600
locomotion ticks. The 3,850 total-tick cap allows at most 60 seconds for the
paused operator window. The runtime enters home over five seconds and then
holds paused until the controller's preserved A-edge toggle unpauses it.

The following attempt-1 command is retained only for provenance and must not be
rerun:

```bash
cd /home/sunrise/open-duck-x5-gate5-t247
sudo setup/run_t247_gate5_single_arm.sh \
  --source-root /home/sunrise/open-duck-x5-gate5-t247 \
  --asset-root /home/sunrise/open-duck-x5-gate5-t247-assets \
  --config /home/sunrise/duck_config.json \
  --imu-calibration /home/sunrise/gate3/sensor-matrix-20260718-readybarrier/calibration/imu_calibration.json \
  --output-dir /home/sunrise/duck-evidence/gate5-t247-x0-20260801 \
  --fixed-command-x 0 \
  --hardware-authorized --suspended-or-benched \
  --gate5-moving-authorized
```

Do not run that command. A replacement launcher requires completed no-motion
repair evidence, a new preregistration, and fresh explicit authorization for
the exact x=0 motion. The historical launcher validates the source tree, config, IMU profile, policy,
calibrator, observer fit, reference table, route manifests, and context router
before changing the governor or opening the UART. It requires `/dev/ttyS1`,
isolated CPU 7, `SCHED_FIFO` priority 80, the temporary `performance` governor,
and the Xbox controller. It restores the original `schedutil` governor on
normal, failure, and signal exits.

During serial Gate 5 the controller is pause/unpause-only. The authorized X
command is fixed; lateral, yaw, and head commands are zero; and the phase factor
is 1.0. Controller drift, head-mode input, or sprint input cannot mutate the
replay.

Full JSONL contains the 115-D observation, action, target, implied velocity,
envelope events, joint state and staleness, sensor ages, route/stage, bus error
classes, current, voltage, temperature, and timing. The launcher runs the
independent summarizer after torque-off and governor restoration. A serial
summary stays `REVIEW_REQUIRED`; the launcher never promotes a gate.

Both arms require all structural and safety checks plus transaction failures
below 0.1%, zero read bursts, tick p99 at most 21 ms, tick p99.9 at most 22 ms,
bus maximum below 5 ms, zero stale required samples, zero device alarms, zero
telemetry drops, and confirmed torque-off. At x=.08, the existing tracking and
behavior comparison is the direct decision against the old runtime baseline.

The x=.08 launcher additionally requires a hash-verified
`PASS_REVIEWED_T247_GATE5_X0` receipt. Passing suspended Gate 5 ends this
workstream; it does not authorize grounded replay.
