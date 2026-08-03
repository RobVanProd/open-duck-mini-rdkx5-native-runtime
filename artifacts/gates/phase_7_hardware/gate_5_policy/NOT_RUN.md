# PASS REVIEWED — Hardware Gate 5: suspended T247 x=0 and x=.08

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

The separately frozen x=.08 arm completed on 2026-08-02 and is
`PASS_REVIEWED_T247_GATE5_X008`. It used one five-second home entry, one clean
startup-readiness exchange, exactly 250 calibration ticks, and exactly 600
locomotion ticks. All 46,224 transactions succeeded. Tick p99/p99.9 were
20.126557/20.137626 ms; bus p99.9/max were 3.898666/4.008135 ms. There were
zero read bursts, stale required samples, alarms, partial bytes, unexpected
packets, telemetry drops, or target-velocity envelope events. The operator
reported that it looked and sounded clean.

Runtime cutoff and an independent all-14 torque-enable register readback both
confirmed torque off. The raw archive reproduced SHA-256
`2a06a0f9e5489f4d751098ca0aab221bf50b4b6e9694e0cc1a2e126c019911c5`
locally. Independent replay verified every member hash, all 2,893 schemas,
contiguous ticks 0-2888, the exact 250+600 active-stage sequence, and an exact
summary match after source-path normalization. The reviewed receipt is
`T247_X008_READINESS_CUED_PASS_REVIEWED_20260802.json`.

The suspended Gate 5 sequence is complete and ready for runtime handoff.
Grounded replay remains prohibited and no further motion is authorized by this
result.
