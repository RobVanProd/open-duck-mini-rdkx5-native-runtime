# Phase 7 Hardware Gates

Gate 1 is `PASS_REVIEWED`. Gate 2 is `NOT_RUN_BLOCKED_PREFLIGHT`: its authorized
torque-off preflight failed the bus gates before torque enable. Gates 3-5 remain
`NOT_RUN`. They are sequential; passing or authorizing one gate does not
authorize the next. Every invocation requires Rob's authorization for that exact
gate and command, plus a physically suspended or benched robot.

Each gate directory keeps its own status so partial progress cannot be mistaken
for complete robot clearance. Grounded replay is outside this repository.
