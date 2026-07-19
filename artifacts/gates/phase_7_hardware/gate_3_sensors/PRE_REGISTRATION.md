# Gate 3 IMU/contact capture pre-registration

Status: `NOT_AUTHORIZED_NOT_RUN`

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
- The preserved `imu_calib_data.pkl` is converted once to the strict JSON
  schema; both source and JSON hashes are frozen before capture.
- BNO055 chip ID reads exactly `0xa0`.
- All accelerometer, gyroscope, and magnetometer offset triplets read back
  exactly after configuration.
- Live pin-mux inventory confirms physical pin 15 / BCM22 claims GPIO 388
  (`LSIO_UART2_TX`) and physical pin 13 / BCM27 claims GPIO 379
  (`LSIO_UART7_RX`) as inputs, then releases both cleanly.
- The exact reviewed source/archive hashes are frozen in the eventual launcher.

The GPIO mapping and chip identity are verified by the 2026-07-18 readiness
inventory. The calibration file/hash and configured offset readback remain
pending. Their absence blocks execution; it is not a failed Gate 3 result.

## Data gates

Every labeled capture must have:

- exactly 250 JSONL rows and a matching raw SHA-256;
- zero stale IMU/contact rows;
- strictly increasing control, IMU, and contact timestamps;
- zero sensor-worker errors and at least one successful device sample;
- both hardware acknowledgements and no servo-bus, torque, target write, or
  policy access;
- identical config, calibration, and source hashes across all nine runs.
- an immutable `imu_calibration.json` copied into the run root whose hash,
  source hash, and offset triplets match every device readback.

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
