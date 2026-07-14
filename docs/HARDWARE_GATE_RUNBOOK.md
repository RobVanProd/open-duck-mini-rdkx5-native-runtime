# Staged Hardware Gate Runbook

All gates are `NOT_RUN`. Each invocation requires a fresh, explicit authorization from Rob and a physically suspended or benched robot. Authorization for one gate does not authorize the next.

## Common preflight

1. Record repository commit, config SHA-256, policy SHA-256 if applicable, board image/kernel, Python version, serial driver, baud, USB topology, CPU isolation, scheduler, and operator.
2. Confirm hands clear, robot supported, power cutoff reachable, and `start_paused=true`.
3. Run `setup/verify_rt_setup.sh 5 80` and `setup/verify_serial_path.sh /dev/ttyACM0`; attach output. RT verification must show exact isolation membership plus successful affinity and `SCHED_FIFO` tests.
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

## Gate 2 — Fourteen-servo home hold, no policy

- Verify all 14 IDs before torque enable.
- Slowly move to home, then run SyncWrite plus grouped position/speed read and round-robin telemetry.
- Required: tick p99 <= 21 ms, p99.9 <= 22 ms, zero failure bursts, transaction failure < 0.1%, total bus time max < 5 ms.
- Hard tick >40 ms or configured consecutive failures immediately torque off.

The moving probe requires a third, gate-specific assertion in addition to the
two common hardware assertions:

```bash
runtime_timing_probe --bus serial --config ~/duck_config.json \
  --require-realtime --rt-cpu 5 --rt-priority 80 \
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
  --require-realtime --rt-cpu 5 --rt-priority 80 \
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
  --require-realtime --rt-cpu 5 --rt-priority 80 \
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
