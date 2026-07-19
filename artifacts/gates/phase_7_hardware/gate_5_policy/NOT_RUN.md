# NOT RUN — Hardware Gate 5: Suspended Policy Replay

No policy has been run on the X5 from this repository. The legacy 101-D golden
vector passes, and the stateful 115-D winner handoff has been independently
hash-checked and CPU-replayed. That handoff is explicitly not compatible with
the frozen v1 interface: it requires a versioned v2 assembler, recurrent state,
P30 observer, projected-reference suffix, and a different phase reset value.
The 512000-step checkpoint was formally selected and the separate default-off
v2 implementation passed its frozen 2,400-tick CPU matrix. The prior per-build
COM-measurement route was rejected: no scale, caliper, static COM entry, or
component worksheet is required.

Gate 5 is still blocked because the policy repository has not yet published a
passed variable-configuration support envelope or `robot_clearance: true`, the
automatic supported-configuration calibration is physically `NOT_RUN`, the
winner-v2 code has no reviewed serial/runtime-CLI integration, and the no-servo
X5 CPU preflight plus frozen Gate 5 launcher do not yet exist.

After all of those blockers clear, `x=0` and `x=0.08` require separate authorization,
600 valid policy ticks under a finite total cap, complete runtime JSONL, control summaries, reviewed hashes,
and zero telemetry loss. A serial summary is always `REVIEW_REQUIRED`; software
does not grant robot clearance. Grounded replay remains prohibited.
