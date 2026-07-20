# Gate 3 startup-stale halt — 2026-07-18

Status: `HALTED_REVIEWED_STARTUP_STALE`

The separately authorized no-servo nine-label Gate 3 matrix began with the
frozen `upright` label and halted before the next label. The label probe
completed its requested 250 rows, but the per-label validator rejected row 0
because both IMU and contact timestamps were zero and both samples were stale.
The launcher stopped exactly as preregistered.

No servo endpoint was opened. `servo_bus_accessed=false`,
`torque_enabled=false`, `goal_position_writes=0`, `policy_loaded=false`, and
`policy_inference_count=0`. The runner recorded no completed label, so this is
not a Gate 3 candidate and does not advance the hardware sequence.

## Attribution

The raw 250-row stream remains on the X5 at
`/home/sunrise/gate3/sensor-matrix-20260718/upright/sensor.jsonl`; it is not
committed. Its SHA-256 is
`0236adf1481dcdd7e921451ffa00fe0b90ef7c5f2d1fc1a048e63d8e30214454`.
Only row 0 is stale. It has zero device timestamps and an age of
`19049442.458151 ms`. Row 1 is already a real, fresh publication: IMU age
`6.413058 ms`, contact age `6.065933 ms`, and acceleration
`[0.49, 0.89, 10.71] m/s²`. All remaining 249 rows are fresh and the sensor
worker reports 499 successes, zero errors, and no recorded error type.

This isolates a startup-publication race: `SensorHub` started its background
worker, but the first `AbsoluteTicker.wait()` returned immediately and the
probe read before `_published` received its first complete immutable sample.
The evidence does not support bad calibration, a wrong physical label, an I2C
fault, or a GPIO fault as the cause of this halt.

## Disposition

The failed root is preserved and its complete board-side checksum list passed
`sha256sum --check`. The correction must add a bounded initial-publication
barrier and prove the first sample is fresh before starting the frozen 250-row
population. The same barrier applies to runtime startup before servo
verification or torque enable. The corrected source and launcher must be
frozen and pass CI before fresh authorization is requested. The old output
directory is never reused, and the previous authorization is not treated as
permission to repeat the label.

Gate 3 remains blocked. Gates 4 and 5 remain `NOT_RUN`.
