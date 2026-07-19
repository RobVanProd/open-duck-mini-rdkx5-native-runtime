# Phase 7 Hardware Gates

Gate 1 is `PASS_REVIEWED`. Gate 2 remains `NOT_RUN`, but its separately
authorized 10,000-tick torque-off timing preflight passes under the
`performance` governor and now awaits fresh moving-gate authorization. Torque
was never enabled. Gates 3-5 remain `NOT_RUN`. They are sequential; passing or
authorizing one gate does not authorize the next. Every invocation requires
Rob's authorization for that exact gate and command, plus a physically
suspended or benched robot.

Each gate directory keeps its own status so partial progress cannot be mistaken
for complete robot clearance. Grounded replay is outside this repository.
