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

The current state is `HALTED_PRE_POLICY_NO_MOTION_REVALIDATION_REQUIRED`.
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

The x=.08 arm remains blocked. It requires a separately reviewed green x=0
receipt, the receipt's exact SHA-256, and separate explicit authorization.
Grounded replay remains prohibited.
