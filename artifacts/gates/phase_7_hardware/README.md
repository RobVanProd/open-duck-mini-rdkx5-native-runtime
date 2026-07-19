# Phase 7 Hardware Gates

Gates 1 and 2 are `PASS_REVIEWED`. Gate 2 completed its frozen 10,000-tick
torque-off preflight, five-second home entry, and 10,000-tick home hold under
the `performance` governor, then confirmed torque-off and restored `schedutil`.
Gates 3-5 remain `NOT_RUN`. They are sequential; passing or authorizing one gate
does not authorize the next. Every invocation requires Rob's authorization for
that exact gate and command, plus a physically suspended or benched robot.

Each gate directory keeps its own status so partial progress cannot be mistaken
for complete robot clearance. Grounded replay is outside this repository.
