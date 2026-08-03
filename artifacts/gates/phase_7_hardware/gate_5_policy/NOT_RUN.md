# PARTIAL PASS — Hardware Gate 5: T247 x=0 reviewed; x=.08 not run

The readiness-cued suspended T247 x=0 arm completed on 2026-08-02 and is
`PASS_REVIEWED_T247_GATE5_X0`. This supersedes the pre-policy status of the
three earlier failed attempts without altering their preserved evidence.

The accepted run used one five-second home entry, one clean startup-readiness
exchange, exactly 250 calibration ticks, and exactly 600 locomotion ticks at
fixed x=0. All 56,960 transactions succeeded. Tick p99/p99.9 were
20.058568/20.115872 ms; bus p99.9/max were 3.836193/3.919508 ms. There were
zero read bursts, stale required samples, alarms, partial bytes, unexpected
packets, telemetry drops, or target-velocity envelope events. The operator
reported that everything looked and sounded normal.

Runtime cutoff and an independent all-14 torque-enable register readback both
confirmed torque off. The raw archive reproduced SHA-256
`ace166ceec085bb3d22b817e8256fcb3ef148b9313ac7f0666d6768d84c19633`
locally. Independent replay verified every member hash, all 3,564 schemas,
contiguous ticks 0-3559, exact 250+600 active-stage counts, and an exact summary
match after source-path normalization. The reviewed receipt is
`T247_X0_READINESS_CUED_PASS_REVIEWED_20260802.json`.

The x=.08 arm remains `NOT_RUN`. The reviewed x=0 receipt earns only a separate
x=.08 preregistration and launcher review; it does not authorize that run.
Grounded replay remains prohibited and robot clearance remains false.
