# NOT RUN — Hardware Gate 4: Sine Tracking

No suspended sine sweep has been run. The offline scope is frozen to logical
`left_hip_yaw` (servo ID 20), 0.03 rad amplitude, and separate 10,000-tick
populations at 0.25 Hz followed by 0.5 Hz only after a first-stage pass.

Tracking p95 must be <= 0.011 rad while every Gate 2 timing, bus, burst, failure,
and telemetry-completeness requirement remains green.

See `PRE_REGISTRATION.md`. Hardware execution still needs a fresh, exact moving
authorization after the source/archive/launcher hashes are published and CI is
green.
