# Phase 7 Hardware Gates

Gate 1 is `PASS_REVIEWED`; Gates 2-5 remain `NOT_RUN`. They are sequential:
passing one gate does not authorize the next. Every invocation requires Rob's
authorization for that exact gate and command, plus a physically suspended or
benched robot.

Each gate directory keeps its own status so partial progress cannot be mistaken
for complete robot clearance. Grounded replay is outside this repository.
