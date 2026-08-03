# Grounded validation handoff

## Current result

The frozen T247 policy/runtime completed both suspended Gate 5 arms:

- x=0: `PASS_REVIEWED`
- x=.08: `PASS_REVIEWED`

Those results establish policy/runtime contract fidelity, clean 50 Hz timing,
clean all-14 bus operation, and clean observed suspended motion. They do not
establish that the robot can safely support itself on the floor.

The suspended, no-policy G2 B-button cutoff revalidation is now also
`PASS_REVIEWED`. B stopped the control path and completed torque disable in
0.197709 ms, with no control exchange after detection. A separate process then
read register 40 as zero on all 14 servos. This establishes the measured
suspended emergency-stop path only; it does not authorize grounded motion.

## Why controller safety was measured before grounded design

Xbox A remains pause/unpause. Pausing holds the last commanded posture; it is
not a hard torque-off. The new B-button path raises the same safety exception as
other watchdog failures, so the existing torque guard cuts torque on every exit
path. Before relying on B near a moving robot, the physical button mapping and
then the torque cutoff must each be measured independently.

This changes no observation, action, policy, home, phase, rate, servo, or sensor
semantics. The reviewed T247 ONNX asset and suspended Gate 5 evidence remain
unchanged.

## Frozen ladder

| Stage | Scope | State | What a pass earns |
|---|---|---|---|
| G0 | Offline B-edge implementation and tests | `PASS` | Controller-only physical mapping may be requested |
| G1 | Physical Xbox B mapping; controller input only | `PASS_REVIEWED` | A separate suspended cutoff test may be preregistered |
| G2 | Suspended, no-policy home-entry B cutoff with independent torque-off readback | `PASS_REVIEWED` | Grounded x=0 may be designed and separately reviewed |
| G3 | Grounded x=0 standing only | `DESIGN_FROZEN_BLOCKED_ON_EXPLICIT_AUTHORITY_AMENDMENT`; no launcher exists | Grounded x=.08 may be designed and separately authorized |
| G4 | Grounded x=.08 only | `BLOCKED_ON_G3`; no launcher exists | Grounded validation handoff review |

There is no automatic promotion between stages. Every physical stage gets a
new preregistration, exact authorization, evidence directory, review, and stop
decision.

## G1: controller-only physical mapping

The G1 launchers are preserved as evidence. Despite their filenames, they are
not grounded robot runs. They open `/dev/input/js0` only and explicitly do not
open serial, touch servos, enable torque, load T247, or command motion.

Pass criteria are exactly one B emergency-stop edge, zero A pause edges, zero
disconnect/stale events, the frozen controller identity before and after, and
the probe's explicit no-serial/no-servo/no-torque/no-policy/no-motion fields.
The run ends immediately when B is observed or after 3000 ticks (60 seconds).

The first physical invocation halted on tick 0 before the operator could press
B. The controller was connected and unchanged, but the probe computed sample
age as `tick_start - controller_timestamp`. Because the controller timestamps
its state inside the later `read_into` call, this produced `-0.322834 ms` and a
false stale-state classification. The runtime was not affected: its controller
freshness checks already sample the monotonic clock after `read_into`. The
attempt is permanently closed; only a separately frozen replacement may run.

The corrected replacement then recorded all 3000 samples with ages from 0.011
through 0.086292 ms, zero stale/disconnect events, and zero A/B edges. The
operator subsequently reported being unavailable during the cue window, so it
does not test the physical B mapping. That attempt is also closed; a distinct
operator-return preregistration is required for the requested repeat.

The operator-return attempt then passed: the known Xbox produced exactly one B
edge at tick 456, with zero A edges, zero stale/disconnected samples, and sample
ages from 0.011959 through 0.123042 ms. This closed G1 only. G2 still required
its own frozen launcher, event-to-stop threshold, independent register-40
torque-off readback, and fresh suspended-motion authorization. The reviewed
result below closes those requirements.

## G2: suspended cutoff revalidation (pass reviewed)

The reviewed G1 pass earned this stage. Its preregistration and one-shot
launcher now freeze all of the following before execution:

1. no policy and no walking command;
2. the already reviewed five-second home entry on the stand;
3. a visible cue for one B press while the home-entry/hold path is active;
4. halt reason exactly `physical controller emergency stop requested`;
5. B detection through completion of the torque-disable write within 20 ms,
   exactly one frozen 50 Hz control period, with no control exchange after B;
6. cleanup plus an independent all-14 register-40 read proving torque is off;
7. no retry or automatic transition to grounded work.

The launcher is `setup/run_suspended_controller_b_cutoff_g2.sh`. It first runs
the full 10,000-tick torque-off timing preflight. Only a complete pass permits
the five-second home entry. It writes `HOME_HOLD_READY` only after home entry,
then waits for the operator's single B press. The expected halt is followed by
a separate process that disables torque again and reads register 40 on all 14
servos, with ID 13 last. It has no policy or grounded-motion path.

The first G2 invocation halted during the torque-off preflight after 215 clean
ticks because the Xbox joydev endpoint disappeared. Torque was never enabled,
the moving stage was never entered, and a separate post-halt register-40 read
confirmed all 14 servos torque-off. The new `/dev/input/js0` was created 13.18
seconds after the halt. The operator reported that the controller had already
been idle and likely slept. The original attempt is closed.

A replacement is frozen without changing the runtime, probe, bus, thresholds,
or G2 sequence. Its only change is an operator keep-awake protocol: move either
stick once immediately before launch and once at each 25-second cue during the
torque-off preflight, then release it to center. Controller axes cannot affect
the zero-amplitude no-policy targets. A and pre-GO B remain forbidden. The
replacement is reviewed offline but requires new exact authorization.

The separately authorized replacement completed on 2026-08-03. Its 10,000-tick
torque-off preflight passed with tick p99 20.002676 ms, p99.9 20.00480125 ms,
bus maximum 4.372636 ms, and zero failed transactions, bursts, stale samples,
or device alarms. After the five-second home entry, the operator pressed B at
the launcher-generated GO cue. Torque disable started 0.024167 ms after event
detection and completed 0.197709 ms after detection, well inside the frozen
20 ms limit. Exactly zero control exchanges followed detection. The expected
probe exit status was 2 with halt reason `physical controller emergency stop
requested`; the launcher validation passed all 12 checks. A separate no-motion
process disabled torque again and read register 40 as zero on all 14 servos in
the prescribed order with ID 13 last.

The replacement wrapper emitted eight 25-second keep-awake records. Because
the desktop command transport buffered remote stdout, some operator-facing
reminders were coalesced. The controller nevertheless remained connected and
fresh for both stages; cue cadence was not a quantitative G2 acceptance metric.
The reviewed artifact records this procedural observation explicitly.

G2 is therefore `PASS_REVIEWED`. It earns review of a possible G3 design only.
It does not authorize grounded motion, create a grounded launcher, or permit an
automatic follow-on.

The G3 design review is now frozen separately. A read-only reduction of the
suspended x=0 trace established that its 250 calibration ticks move the leg
chains at up to 1.499996 rad/s before the 600-tick static hold. It is therefore
not safe to treat x=0 as a no-motion test. The current runtime also lacks an
automatic body-tilt/contact-loss cutoff and has no honest grounded hardware
assertion. G3 implementation is blocked pending the exact, offline-only
authority amendment recorded in the design artifact. No launcher was created.

## G3/G4: grounded work (not authorized and not implemented)

Grounded testing is a new authority boundary. It must not reuse the
`--suspended-or-benched` assertion while the robot is on the floor. A reviewed
G2 pass is necessary but not sufficient: the repository authority, launcher,
support/clear-area procedure, run duration, command, stop conditions, and
operator actions must all be reviewed before G3 exists.

G3 will be x=0 only. G4 can exist only after a reviewed G3 pass and will be
x=.08 only. No other command, command sweep, or autonomous continuation is
part of this ladder.

## Frozen evidence inputs

- T247 x=0 review SHA-256:
  `9d40a3cd5c937eff84a65ea3117af9b0178eebc8af366692926fd175736fb096`
- T247 x=.08 review SHA-256:
  `0ef3c547c2939012c5f09a074520e99697a51761fbfa4bab3b293a8c503c6130`
- Emergency-stop source commit:
  `257c84fddd1ed9162498840cd00b4d90c33785a1`
- Runtime source tree:
  `6bb064e1d15c27fb6af7301cf2fe9a6b4d7fb6d4`
- G1 reviewed pass SHA-256:
  `e4fe7279b33c25a8334ff0dc8f067c9e0321b6710a39d0fc3f53016b5e3c0d13`
- G2 preregistration SHA-256:
  `414776d4792a859b27a75b7020577c5b370fc307f70a036032d250bf8f4dca83`
- G2 replacement reviewed pass SHA-256:
  `6293a79e4db58c5171a1e872b7c5d99d23154bf94f82faf90b65fc2deef1c7fe`
- G3 authority and safety design SHA-256:
  `855411116fb2102cfbde4ea3dce926c904b2842863a356c14a44e4d67218c699`

The G1 preregistration is
`artifacts/gates/grounded_validation/CONTROLLER_B_STOP_NO_SERVO_PREREGISTRATION_20260802.json`.
