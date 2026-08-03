# HALTED PRE-POLICY — Hardware Gate 5: Suspended T247 Policy Replay

The first authorized x=0 invocation ran on 2026-08-02 but halted while still
paused, before any calibration or policy tick. The runtime entered home and
held it, then its watchdog stopped a 92.776 ms hard overrun. Torque-off was
confirmed, `/dev/ttyS1` was released, and the governor was restored. This is
not a Gate 5 policy result: active policy ticks were exactly zero.

The offline and pre-Gate-5 evidence remains green:

- T249B offline behavior: 20/20 conditions and 320/320 cells pass.
- Exact command-routed X5 compute: 35/35 checks pass for x=0 and x=.08.
- Opt-in production runtime wiring: 18/18 mock real-asset checks pass.
- Independent T247 control-summary contract: reviewed green.
- Hardware Gates 1-4: `PASS_REVIEWED`.
- Single-arm Gate 5 launcher: correctly halted and failed closed.

The first replacement authorization was consumed by a second pre-policy halt;
Gate 5 still has zero active policy ticks.
The failed tick was causally aligned with an Xbox Bluetooth HID reconnect. The
review selected a thread-free Linux joystick backend, late-serial-deadline
rejection, and paused-controller freshness enforcement. A controller-only test
and a 10,000-tick controller-present torque-off timing probe must pass before a
new x=0 motion invocation can even be preregistered.

That probe completed all 10,000 ticks, with its timing tails and failure-rate
gates green, but it remains a frozen failure because measured tick 0 reached
5.080639 ms against the strict `<5 ms` bus maximum. Tick 0 alone used the
generic recovery parser; all 9,999 later fixed-order ticks stayed at or below
4.372012 ms. The threshold and measured population are unchanged. A bounded
fixed-slot recovery path and a separately recorded, one-shot startup readiness
AND-conjunct now pass offline tests. They require a fresh explicitly authorized
torque-off revalidation before any replacement x=0 motion attempt.
That revalidation is frozen in
`T247_STARTUP_READINESS_REVALIDATION_PREREGISTRATION_20260802.json`; its runner
has no torque-enable, policy-load, or motion path.

The revalidation passed its readiness and full 10,000-tick populations and was
independently reviewed. This closes the controller/startup timing repair only.
The replacement x=0 launcher is now frozen and reviewed; Gate 5 itself remains
without an active policy tick until fresh motion authorization is provided.

That replacement is now frozen as
`setup/run_t247_gate5_x0_replacement.sh`, SHA-256
`319b0320bde78ce73fc5a76eb716ed989adfedc176def3a572af797495519926`.
It has one hardcoded x=0 invocation, requires the accepted no-motion receipt,
pins the known-good controller before and after, requires the new readiness
event and every summary gate, and contains no second-command path. That
launcher ran once. Its five-second home entry completed, but the
startup-readiness event could not serialize the NumPy phase vector. The
evidence stream contains only `runtime_start` and `realtime_verified`; there is
no readiness record, control tick, or active policy tick. The runner failed
closed. A separate torque-off command then returned `ok`, and all 14 servos
read back register 40 as zero. The exact failed evidence is recorded in
`T247_X0_REPLACEMENT_ATTEMPT_HALTED_20260802.json`.

The phase values and policy contract are unchanged. The selected repair merely
serializes the frozen two-number phase vector to JSON-native values and makes
the schemas, semantic validator, and tests enforce that representation. The
consumed launcher and authorization cannot be reused. A new exact freeze,
green checks, clean X5 staging, and fresh suspended x=0 authorization are
required.

The repaired retry is now frozen against runtime tree
`2aba58167a82b47bdd6942da25d4913c098cbfba`, schema tree
`55580397a2d01bd6f76417f57a92c4dddee7f642`, and launcher SHA-256
`c7598541b84623581016bf0d3c68a5f8a9f64c67d7f56906085c452dea8a8c0e`.
It requires a new unused output directory and fresh explicit suspended x=0
authorization. It has not run.

That phase-JSON retry halted before its readiness bus exchange because the
operator A-button edge arrived during the explicit reject-toggle check. It
recorded zero control ticks and zero active policy ticks. Runtime cutoff and a
separate all-14 register-40 readback both passed. The exact evidence is in
`T247_X0_PHASE_JSON_RETRY_ATTEMPT_HALTED_20260802.json`.

The next retry must use a monitored readiness handshake: no A press until the
agent observes the clean readiness `PASS` record and explicitly says `GO`.
That new protocol is now frozen with launcher SHA-256
`7bcf2900bba180646e651ea10bdf03fe7c48a1be85c2be672fd4ff5e8db75b72`
and a new unused evidence directory. It remains unauthorized and has not run.

The x=.08 arm remains blocked. It requires a separately reviewed green x=0
receipt, the receipt's exact SHA-256, and separate explicit authorization.
Grounded replay remains prohibited.
