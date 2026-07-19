# Phase 7 Hardware Gates

Gates 1 through 3 are `PASS_REVIEWED`. Gate 2 completed its frozen 10,000-tick
torque-off preflight, five-second home entry, and 10,000-tick home hold under
the `performance` governor, then confirmed torque-off and restored `schedutil`.
Gate 3 completed its corrected nine-label no-servo sensor matrix with all 2,250
samples fresh and the physical labels independently reviewed. Gates 4-5 remain
`NOT_RUN`. They are sequential; passing or authorizing one gate
does not authorize the next. Every invocation requires Rob's authorization for
that exact gate and command, plus a physically suspended or benched robot.

Each gate directory keeps its own status so partial progress cannot be mistaken
for complete robot clearance. Grounded replay is outside this repository.
