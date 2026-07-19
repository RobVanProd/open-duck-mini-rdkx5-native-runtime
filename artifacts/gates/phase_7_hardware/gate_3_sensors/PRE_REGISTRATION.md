# Gate 3 IMU/contact capture pre-registration

Status: `HALTED_REVIEWED_STARTUP_STALE_RERUN_NOT_AUTHORIZED`

## Scope

Gate 3 is a no-policy, no-servo-bus, no-torque sensor verification. It captures
the BNO055 and two active-low foot switches while the robot remains supported.
This document does not authorize board access or any later gate.

## Frozen capture population

Nine independent labeled captures are required, in this order:

1. `upright`
2. `nose_forward`
3. `nose_back`
4. `left_tilt`
5. `right_tilt`
6. `no_contacts`
7. `left_contact`
8. `right_contact`
9. `both_contacts`

Each capture contains exactly 250 control samples at 50 Hz from a 100 Hz sensor
worker. The stale limit is 40 ms. The IMU endpoint is `/dev/i2c-5`, address
`0x28`. Contacts are BCM 22 / physical pin 15 for left and BCM 27 / physical
pin 13 for right, with raw GPIO false mapping to contact true. The operator must
type the same label passed to the probe before each run.

## Required prerequisites

- Gate 2 remains `PASS_REVIEWED` and is not rerun.
- The live config SHA-256 remains
  `131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b`
  with `imu_upside_down=true`.
- This robot's BNO055 completes the separately preregistered guarded physical
  calibration. Five consecutive `0xff` status reads are required before its
  three offset triplets are captured; a fresh session must apply and read them
  back exactly. Both legacy-compatible source and strict JSON hashes are frozen
  before the nine labeled captures.
- BNO055 chip ID reads exactly `0xa0`.
- All accelerometer, gyroscope, and magnetometer offset triplets read back
  exactly after configuration.
- Live pin-mux inventory confirms physical pin 15 / BCM22 claims GPIO 388
  (`LSIO_UART2_TX`) and physical pin 13 / BCM27 claims GPIO 379
  (`LSIO_UART7_RX`) as inputs, then releases both cleanly.
- The exact reviewed source/archive hashes are frozen in the launcher:
  corrected source commit `aac7410f241a5419af2257ba9635e6755d7b5ae8` and
  source archive SHA-256
  `d41e516ec52558ec169c0f8f017d8959aed657a999786ed5e8e7716895ced9a0`.

The GPIO mapping and chip identity are verified by the 2026-07-18 readiness
inventory. The separately guarded physical calibration is now complete: profile
SHA-256 is
`e7518b0df8614c1d399c789fd26aa9888043ebacfccc98ef75a5010a4b8c34be`,
source SHA-256 is
`a3552b357dc2d0e6a876c8e8406134ab36fa6e88a7b7f444c9f9d25122a9da08`,
and exact fresh-session register readback passed.

The first authorized matrix attempt halted at the `upright` validator because
row 0 was captured before the worker's initial immutable publication. Row 1
and all 248 later rows were fresh, and the worker recorded zero errors. The
failed output and complete checksum list are preserved under
`startup_stale_halt_20260718/`; no later label or servo path ran. A corrected
probe must wait at most 2.0 seconds for an initial complete publication, verify
that publication is fresh, and only then instantiate the ticker that defines
the 250-row population. A timeout or stale initial publication publishes no
label evidence.

The corrected rerun launcher form is:

```bash
bash setup/run_gate3_sensor_matrix.sh \
  --source-archive /home/sunrise/open-duck-x5-gate3-aac7410f241a5419af2257ba9635e6755d7b5ae8.tar.gz \
  --config /home/sunrise/duck_config.json \
  --calibration-dir /home/sunrise/gate3/calibration-20260718 \
  --output-dir /home/sunrise/gate3/sensor-matrix-20260718-readybarrier \
  --hardware-authorized --suspended-or-benched
```

The halted source/output pair must not be reused. This corrected launcher
remains blocked until its separate launcher commit passes CI and Rob authorizes the complete
nine-label Gate 3 rerun while physically present at the supported robot.

## Data gates

Every labeled capture must have:

- exactly 250 JSONL rows and a matching raw SHA-256;
- a source-bound 2.0-second initial-publication barrier completed before the
  frozen population begins;
- zero stale IMU/contact rows;
- strictly increasing control, IMU, and contact timestamps;
- zero sensor-worker errors and at least one successful device sample;
- both hardware acknowledgements and no servo-bus, torque, target write, or
  policy access;
- identical config, calibration, and source hashes across all nine runs.
- an immutable `imu_calibration.json` copied into the run root whose hash,
  source hash, and offset triplets match every device readback.
- the complete four-file calibration capture plus its independently rederived
  review packet copied into the run root; every label's integrity packet must
  pass before the next physical state is allowed.

For the contact labels, mean `[left, right]` must be within 0.05 of `[0,0]`,
`[1,0]`, `[0,1]`, and `[1,1]` respectively. This numeric consistency check
does not replace the operator's physical-label review.

## Review and stop rules

`validate_gate3_sensors` may produce only `REVIEW_REQUIRED`. A human reviewer
must verify upright gravity, both opposing nose tilts, both opposing side tilts,
and each physically pressed switch. Gate 3 remains blocked for any ambiguous or
reversed label, identity/calibration mismatch, stale row, worker error, pin-mux
conflict, hash change, or unexpected device access. A failed label is not
silently repeated under a new name; the cause is reviewed first.
