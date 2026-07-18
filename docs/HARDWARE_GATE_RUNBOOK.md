# Staged Hardware Gate Runbook

Gate 1 is `PASS_REVIEWED`. Gate 2 remains `NOT_RUN` because its authorized
torque-off preflight failed the bus gates before torque enable. Gates 3-5 remain
`NOT_RUN`. Each invocation requires a fresh, explicit authorization from Rob and
a physically suspended or benched robot. Authorization for one gate does not
authorize the next.

## Common preflight

1. Record repository commit, config SHA-256, policy SHA-256 if applicable, board image/kernel, Python version, serial driver, baud, USB topology, CPU isolation, scheduler, and operator.
2. Confirm hands clear, robot supported, power cutoff reachable, and `start_paused=true`.
3. Run `taskset -c 0-7 setup/verify_rt_setup.sh 7 80` and `setup/verify_serial_path.sh /dev/ttyACM0`; attach output. An SSH login inherits housekeeping-only affinity after `isolcpus`, so the explicit initial mask is required to reproduce the reviewed service configuration. RT verification must show exact isolation membership plus successful affinity and `SCHED_FIFO` tests.
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

Current status: `NOT_RUN_BLOCKED_PREFLIGHT`. The ID-13-last wire-order repair
removed the reproduced CRC mechanism, but the repeated torque-off preflight had
one device-status reply, `0.125%` failures, and `7.703526 ms` max bus time. The
50 Hz tick p99.9 was green at `20.101307 ms`. Torque was never enabled. See the
Gate 2 preflight artifact before proposing any transport change.

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

- Verify all 14 IDs before torque enable.
- Slowly move to home, then run SyncWrite plus grouped position/speed read and round-robin telemetry.
- Required: tick p99 <= 21 ms, p99.9 <= 22 ms, zero failure bursts, transaction failure < 0.1%, zero device alarms, total bus time max < 5 ms.
- Hard tick >40 ms or configured consecutive failures immediately torque off.

The moving probe requires a third, gate-specific assertion in addition to the
two common hardware assertions:

```bash
runtime_timing_probe --bus serial --config ~/duck_config.json \
  --require-realtime --rt-cpu 7 --rt-priority 80 \
  --enable-torque --moving-gate-authorized \
  --watchdog-failures 2 \
  --hardware-authorized --suspended-or-benched \
  --amplitude-rad 0 --ticks 10000 \
  --output gate2.jsonl --summary gate2-summary.json
```

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

## Gate 3 — IMU and contacts

- No policy.
- Capture labeled upright, nose-forward, nose-back, left-tilt, right-tilt samples.
- Verify `imu_upside_down` against labels, not intuition.
- Verify left/right switches independently; raw false must map to contact true.
- Confirm timestamp age stays within the pre-registered freshness limit.

Collect each physical state as a separate labeled artifact so the operator can
reposition the suspended/benched robot between runs. The probe never opens the
servo bus, enables torque, writes a target, or runs a policy:

```bash
probe_sensors --backend x5 --label upright --config ~/duck_config.json \
  --samples 250 --hardware-authorized --suspended-or-benched \
  --output gate3-upright.jsonl --summary gate3-upright-summary.json
```

Repeat only after deliberate repositioning for `nose_forward`, `nose_back`,
`left_tilt`, and `right_tilt`. Capture switch states separately with
`no_contacts`, `left_contact`, `right_contact`, and `both_contacts`. Every summary
reports sample age, stale counts, timestamp repeats, axis distributions, contact
fractions, config hash, and `imu_upside_down`. Orientation/contact correctness
stays `REVIEW_REQUIRED`; the script does not manufacture a pass from unlabeled
numbers.
The summary also preserves both hardware assertions. Its data-candidate field
only covers completeness/freshness/timestamps; the operator must still review
the physical label, so it is never automatic orientation/contact clearance.

## Gate 4 — Sine sweeps

- Suspended; one approved joint/group at a time.
- Frequencies: 0.25 and 0.5 Hz. Amplitude: 0.03 rad.
- Required simultaneously: tracking p95 <= 0.011 rad and all Gate 2 timing limits green.

Run 0.25 Hz and 0.5 Hz as separate reviewed artifacts. Example after explicit
authorization for the named joint:

```bash
runtime_timing_probe --bus serial --config ~/duck_config.json \
  --require-realtime --rt-cpu 7 --rt-priority 80 \
  --enable-torque --moving-gate-authorized \
  --watchdog-failures 2 \
  --hardware-authorized --suspended-or-benched \
  --sine-joint left_hip_yaw --sine-hz 0.25 --amplitude-rad 0.03 \
  --ticks 10000 --output gate4-025.jsonl --summary gate4-025-summary.json
```

Timing schema v2 records all 14 sent targets, actual positions, and absolute
errors. The summary calculates tracking p95 directly; a timing-only artifact
with torque disabled reports no valid tracking samples and cannot pass Gate 4.
Only exact 0.25/0.5 Hz, 0.03 rad runs can set the Gate 4 candidate field.

## Gate 5 — Suspended policy replay

- Golden observation/action comparison must already pass.
- Run `x=0.0`, review, then separately authorize `x=0.08`.
- Full telemetry includes observation, actions, sent targets, implied target velocity, envelope events, joint state/staleness, sensor ages, bus classes, current, voltage, temperature, and tick timing.
- At `x=0.08`: transaction failures <0.1%, zero bursts, tick p99 <=21 ms, tick p99.9 <=22 ms.

The operational serial runtime is reserved for this gate. It refuses to start
unless the config has `start_paused=true`, the run has a finite tick count, and
the exact fixed command is either `0` or `0.08`. Example for the first,
separately authorized replay:

```bash
open_duck_x5_runtime --bus serial --config ~/duck_config.json \
  --policy ~/candidate-101.onnx --controller xbox \
  --fixed-command-x 0 --max-active-ticks 600 --max-ticks 900 \
  --require-realtime --rt-cpu 7 --rt-priority 80 \
  --gate5-authorized --hardware-authorized --suspended-or-benched \
  --telemetry gate5-x0.jsonl
```

The operator unpauses with the preserved controller action only after the home
hold is visually verified. Review and close the `x=0` artifact before Rob
separately authorizes a new invocation using `--fixed-command-x 0.08`. A 115-D
or stateful candidate is rejected by the frozen 101/14 host and cannot be used
as a substitute export.

During serial Gate 5 the controller is pause/unpause-only. The authorized X
command is fixed, all lateral/yaw/head command fields are zero, and the phase
factor is 1.0; joystick drift or LB cannot mutate the replay.

After the runtime closes, independently validate and summarize the complete
stream before reviewing any threshold:

```bash
summarize_control_run --input gate5-x0.jsonl \
  --output gate5-x0-summary.json
python tools/hash_artifacts.py
python tools/hash_artifacts.py --check
```

The 900-tick total cap bounds the paused operator window; the run completes only
after 600 valid policy ticks. Reaching the total cap first is a safety halt.
Mock summaries are informational, and serial summaries remain
`REVIEW_REQUIRED` even when their recomputed candidate booleans are green.

Passing Gate 5 ends this workstream. It does not authorize grounded replay or policy deployment.
