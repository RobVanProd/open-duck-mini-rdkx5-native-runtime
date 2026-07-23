# Gate 3 BNO055 calibration prerequisite pre-registration

Status: `COMPLETE_REVIEW_CANDIDATE`

This is a prerequisite to Gate 3, not a Gate 3 sensor capture. It authorizes no
servo access, torque, goal-position write, policy load, or later gate. The
robot must remain supported while Rob manually reorients it.

## Frozen population

- Board endpoint: `/dev/i2c-5`, BNO055 address `0x28`.
- Live config: `/home/sunrise/duck_config.json`, SHA-256
  `131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b`.
- Frozen config meaning: `imu_upside_down=true`.
- Timeout: 600 seconds; polling period: 0.25 seconds.
- Acceptance requires five consecutive calibration-register values of `0xff`,
  meaning system, gyroscope, accelerometer, and magnetometer are all level 3.
- Output destination: `/home/sunrise/gate3/calibration-20260718`; it must not
  exist before the run.
- Exact command arguments include `--hardware-authorized`,
  `--suspended-or-benched`, and `--manual-calibration-authorized`.

Rob remains hands-on for the entire session. The robot is first held still for
gyro calibration, then held in multiple stable orientations for accelerometer
calibration, then rotated slowly through all three axes for magnetometer
calibration. Unexpected motion, inability to support the robot safely, an I2C
error, identity mismatch, or operator concern stops the run.

## Acceptance and evidence

After sustained full calibration, the tool reads only the three inherited
offset triplets. It returns the device to NDOF, closes it, and opens a fresh
production-driver session using the candidate. The fresh session must read
back chip ID `0xa0`, NDOF mode `0x0c`, axis map `0x21`, axis sign `0x07`, unit
selection `0x00`, and all nine offset values exactly.

Only after those checks pass may one new directory appear containing:

- `imu_calib_data.pkl`, a primitive legacy-compatible source artifact;
- `imu_calibration.json`, the strict runtime profile bound to the pickle hash;
- `calibration-status.jsonl`, the bounded per-poll status stream;
- `calibration-summary.json`, binding config, artifacts, installed source,
  authorizations, exact readback, and no-servo/no-policy proof.

Timeout, Ctrl-C, readback mismatch, or artifact error produces no candidate
directory. A completed X5 summary remains `REVIEW_REQUIRED`. Hash it with
`python tools/hash_artifacts.py` and review every field before copying the
strict JSON profile into the nine-label Gate 3 run root.

## Executed result

Rob was physically present and explicitly authorized this exact no-servo
session on 2026-07-18. The capture completed in 330.934491 seconds with 1,318
rows and five terminal `0xff` samples. Exact fresh-session readback passed.
Profile SHA-256 is
`e7518b0df8614c1d399c789fd26aa9888043ebacfccc98ef75a5010a4b8c34be`;
legacy source SHA-256 is
`a3552b357dc2d0e6a876c8e8406134ab36fa6e88a7b7f444c9f9d25122a9da08`.
See `calibration_20260718/RESULT.md`. The nine-label Gate 3 matrix remains
separately unauthorized and not run.
