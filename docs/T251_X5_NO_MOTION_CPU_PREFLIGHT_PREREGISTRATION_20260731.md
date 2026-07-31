# T251 X5 no-motion CPU preflight preregistration

Status: `PREREGISTERED_T251_X5_NO_MOTION_CPU_PREFLIGHT`

T250 passed all 25 offline real-asset integration checks. The only earned next
step is an isolated CPU preflight on the RDK-X5. It will copy the hash-pinned
assets into `/home/sunrise/open_duck_x5_preflight/t251`, never into the
production runtime tree, and execute no serial, GPIO, I2C, controller, sensor,
torque, or motion path.

The runner must verify a single-CPU `SCHED_FIFO` process and the `performance`
governor, complete the exact 250-tick calibration and zero-tick handoff, then
execute 10,000 synthetic-state locomotion host ticks at x=0.074. The frozen
compute-only limits are p99 <= 2.0 ms, p99.9 <= 3.0 ms, and max <= 5.0 ms.
These are policy-host compute limits, not the 20 ms full-loop timing gate.

A pass earns only a preregistration for opt-in production integration. Hardware
Gate 5 remains `NOT_RUN`; no policy is deployed and no motor can be energized.

Machine-readable contract:
`artifacts/gates/phase_5_policy/t251_x5_no_motion_cpu_preflight_preregistration_20260731.json`
