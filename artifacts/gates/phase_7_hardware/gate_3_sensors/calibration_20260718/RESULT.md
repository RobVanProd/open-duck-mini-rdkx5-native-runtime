# Gate 3 BNO055 calibration prerequisite result — 2026-07-18

Status: `REVIEW_CANDIDATE_DATA_INTEGRITY_VERIFIED`

Rob explicitly authorized the no-servo manual BNO055 calibration while
physically present at the supported robot. The guarded X5 capture ran on
`/dev/i2c-5`, address `0x28`, using the live config whose SHA-256 is
`131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b`
and whose frozen `imu_upside_down` value is true.

The stream contained 1,318 status samples over 330.934491 seconds. It ended
with the preregistered five consecutive `0xff` samples: system, gyroscope,
accelerometer, and magnetometer were all level 3. The captured triplets were:

- accelerometer: `[118, 0, 33]`
- gyroscope: `[1, 0, -2]`
- magnetometer: `[-421, -125, 360]`

The capture closed the initial device, opened a fresh production-driver
session, applied the strict profile, and read all nine values back exactly with
chip ID `0xa0`, NDOF `0x0c`, axis map `0x21`, axis sign `0x07`, and unit
selection `0x00`. An independent local verifier then reloaded the primitive
pickle through the restricted unpickler, reconstructed all 1,318 status rows,
checked the final sustained population, rehashed all four files, and matched
the frozen capture-source hashes. All nine integrity checks passed. That review
was executed from source commit
`1792d9c6975c328a7349efb5b4baec57852d39b3`; its packet SHA-256 is
`cc8c89e988e0401d33ae7bc0a47dd0be163546f82213013b62d6fc2a2497fc2c`.

The source archive reproduced SHA-256
`7e8189501dbb24ecf0301b86e5c7d787e095aad24a634a3a599b7e5d8cd864cb`
locally and on the board. `smbus2 0.6.1` was installed reversibly in Sunrise's
user site from wheel SHA-256
`650feeb27ca0ed58b07db4c10201c2a662c41305b7bf6e5fab9d888056f48180`.

No servo device was opened. Torque remained off; goal-position writes, policy
loads, and policy inference counts were all zero. This clears the missing-file
prerequisite only. The nine labeled Gate 3 sensor captures remain separately
authorized and `NOT_RUN`; calibration does not authorize Gate 3, Gate 4, or a
policy operation.
