# Phase 7 Hardware Gates

Gates 1 through 4 are `PASS_REVIEWED`. Gate 2 completed its frozen 10,000-tick
torque-off preflight, five-second home entry, and 10,000-tick home hold under
the `performance` governor, then confirmed torque-off and restored `schedutil`.
Gate 3 completed its corrected nine-label no-servo sensor matrix with all 2,250
samples fresh and the physical labels independently reviewed. Gate 4 completed
its frozen left-hip-yaw 0.25/0.5 Hz sine populations with tracking and timing
gates simultaneously green. Gate 5 then completed both separately frozen T247
arms, x=0 and x=.08, with exact 250-calibration + 600-locomotion active
sequences. Both are `PASS_REVIEWED`; their independent replays, operator notes,
and all-14 torque-off readbacks are preserved under `gate_5_policy/`. The gates
were run sequentially under exact per-arm authorization. No completed gate
authorizes a new invocation or grounded motion.

The automatic configuration check has a separately frozen structure under
`automatic_configuration/`, but remains blocked on the preregistered policy
envelope, a final launcher/hash closure, and exact calibration-motion
authorization. It is not Gate 5 and has not run physically.
The checked-in launcher is hard-blocked by a non-SHA pending-envelope sentinel
before its serial-device check; tests freeze that ordering and every exposed
argument.

Each gate directory keeps its own status so partial progress cannot be mistaken
for complete robot clearance. Grounded replay is outside this repository.
