# NOT RUN — Hardware Gate 5: Suspended Policy Replay

Hardware Gate 5 has not run. No T247 policy binary has been copied into the
production runtime tree, no policy has opened the servo bus, and no
policy-driven torque or motion has occurred.

The offline policy blocker is cleared: T249B passed all 20 R2 conditions and
all 320 cells. The offline native-runtime blocker is also cleared: T250 passed
25/25 exact real-asset integration checks with zero numeric delta. The frozen
101-D production contract remains unchanged; the candidate uses a separate,
default-disabled 115-D state-coherent host.

The current blocker is T251. Its isolated no-motion RDK-X5 CPU preflight ran
once and is held on all three frozen compute-tail limits (p99 `3.459200 ms`,
p99.9 `54.642409 ms`, max `55.288782 ms`). The result requires attribution
without changing thresholds. Even a later passing correction would earn only
preregistration for opt-in production integration. The live sensor/bus/safety
integration and its no-motion timing evidence must pass before Gate 5 can be
prepared.

After those blockers clear, suspended x=0 and x=0.08 replays require the
separately frozen Gate 5 contract, explicit authorization, complete runtime
JSONL, reviewed hashes, zero telemetry loss, fresh inputs, and the existing
torque-off/watchdog safety paths. Grounded replay remains prohibited.
