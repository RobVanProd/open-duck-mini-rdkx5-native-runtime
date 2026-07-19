# NOT PASSED — Hardware Gate 3: IMU and Contacts

No labeled X5 sensor sample has passed the frozen label validator. Separate artifacts are
required for upright, nose-forward, nose-back, left-tilt, right-tilt,
no-contact, left-contact, right-contact, and both-contact states.

The reviewer must verify `imu_upside_down`, raw-GPIO-false contact polarity,
sample freshness, and monotonic timestamps from the labeled evidence. The probe
cannot auto-promote orientation/contact correctness.

Offline implementation now additionally requires BNO055 chip-ID verification,
strict conversion of the preserved calibration pickle, exact offset-register
readback, zero sensor-worker errors, typed operator confirmation for every
label, and a single nine-label validation packet. No board sensor access has
been performed as a Gate 3 capture. The authorized readiness inventory verified
the BNO055 identity and both GPIO mappings, but initially found no saved legacy
calibration. Rob subsequently completed the separately guarded physical
calibration. Its 1,318-row stream, five terminal `0xff` samples, exact offset
readback, profile/source hashes, and no-servo proof are recorded under
`calibration_20260718/`.

The first separately authorized matrix attempt captured 250 `upright` rows but
halted because row 0 preceded the sensor worker's first publication. The
launcher reported `HALTED_LABEL_VALIDATION`; no later label ran and no servo,
torque, goal write, or policy path was used. The hash-bound reduction is under
`startup_stale_halt_20260718/`.

Gate 3 is `HALTED_REVIEWED_STARTUP_STALE_RERUN_NOT_AUTHORIZED`. The startup
barrier correction must be frozen and receive new explicit authorization before
the matrix is repeated into a new output directory. Calibration satisfies a
prerequisite; neither it nor the halted label authorizes a later gate.
