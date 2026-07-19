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
been performed under this change. The calibration profile/hash and live X5 GPIO
pin-mux inventory remain pending before an exact launcher can be frozen.
