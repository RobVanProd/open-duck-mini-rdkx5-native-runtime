# Staged Hardware Gate Runbook

All gates are `NOT_RUN`. Each invocation requires a fresh, explicit authorization from Rob and a physically suspended or benched robot. Authorization for one gate does not authorize the next.

## Common preflight

1. Record repository commit, config SHA-256, policy SHA-256 if applicable, board image/kernel, Python version, serial driver, baud, USB topology, CPU isolation, scheduler, and operator.
2. Confirm hands clear, robot supported, power cutoff reachable, and `start_paused=true`.
3. Run `setup/verify_rt_setup.sh` and `setup/verify_serial_path.sh /dev/ttyACM0`; attach output.
4. Pre-register duration, commands, failure threshold, consecutive-failure watchdog count, and stop conditions in the gate artifact.
5. Use both CLI acknowledgements: `--hardware-authorized --suspended-or-benched`.
6. Stop on unexpected motion, wrong joint/side/sign, hard overrun, any burst of read failures, or operator concern.

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

## Gate 2 — Fourteen-servo home hold, no policy

- Verify all 14 IDs before torque enable.
- Slowly move to home, then run SyncWrite plus grouped position/speed read and round-robin telemetry.
- Required: tick p99 <= 21 ms, p99.9 <= 22 ms, zero failure bursts, transaction failure < 0.1%, total bus time max < 5 ms.
- Hard tick >40 ms or configured consecutive failures immediately torque off.

The moving probe requires a third, gate-specific assertion in addition to the
two common hardware assertions:

```bash
runtime_timing_probe --bus serial --config ~/duck_config.json \
  --enable-torque --moving-gate-authorized \
  --watchdog-failures 2 \
  --hardware-authorized --suspended-or-benched \
  --amplitude-rad 0 --ticks 10000 \
  --output gate2.jsonl --summary gate2-summary.json
```

Without `--enable-torque`, the serial probe establishes torque-off before it
writes any target packet. It cannot accidentally become a moving test merely
because torque was left enabled by an earlier process.

## Gate 3 — IMU and contacts

- No policy.
- Capture labeled upright, nose-forward, nose-back, left-tilt, right-tilt samples.
- Verify `imu_upside_down` against labels, not intuition.
- Verify left/right switches independently; raw false must map to contact true.
- Confirm timestamp age stays within the pre-registered freshness limit.

## Gate 4 — Sine sweeps

- Suspended; one approved joint/group at a time.
- Frequencies: 0.25 and 0.5 Hz. Amplitude: 0.03 rad.
- Required simultaneously: tracking p95 <= 0.011 rad and all Gate 2 timing limits green.

Run 0.25 Hz and 0.5 Hz as separate reviewed artifacts. Example after explicit
authorization for the named joint:

```bash
runtime_timing_probe --bus serial --config ~/duck_config.json \
  --enable-torque --moving-gate-authorized \
  --watchdog-failures 2 \
  --hardware-authorized --suspended-or-benched \
  --sine-joint left_hip_yaw --sine-hz 0.25 --amplitude-rad 0.03 \
  --ticks 10000 --output gate4-025.jsonl --summary gate4-025-summary.json
```

Timing schema v2 records all 14 sent targets, actual positions, and absolute
errors. The summary calculates tracking p95 directly; a timing-only artifact
with torque disabled reports no valid tracking samples and cannot pass Gate 4.

## Gate 5 — Suspended policy replay

- Golden observation/action comparison must already pass.
- Run `x=0.0`, review, then separately authorize `x=0.08`.
- Full telemetry includes observation, actions, sent targets, implied target velocity, envelope events, joint state/staleness, sensor ages, bus classes, current, voltage, temperature, and tick timing.
- At `x=0.08`: transaction failures <0.1%, zero bursts, tick p99 <=21 ms, tick p99.9 <=22 ms.

Passing Gate 5 ends this workstream. It does not authorize grounded replay or policy deployment.
