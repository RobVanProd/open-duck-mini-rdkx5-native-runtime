# NOT RUN — Hardware Gate 3: IMU and Contacts

No labeled X5 sensor samples have been collected. Separate artifacts are
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

Gate 3 itself is still `NOT_AUTHORIZED_NOT_RUN`. Calibration satisfies a
prerequisite; it does not substitute for the nine labeled orientation/contact
captures or authorize a later gate.
