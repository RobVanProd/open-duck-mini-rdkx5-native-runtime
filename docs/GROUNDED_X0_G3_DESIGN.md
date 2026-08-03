# Grounded x=0 G3 design

Status: `DESIGN_FROZEN_BLOCKED_ON_EXPLICIT_AUTHORITY_AMENDMENT`

G2 proved the physical B-button path can complete torque disable in 0.197709
ms and that all 14 torque-enable registers are zero afterward. That earns an
offline G3 design review. It does not authorize grounded motion.

## The x=0 run still moves

The reviewed suspended T247 x=0 trace was reduced again before designing G3.
Its 250 calibration ticks move four leg chains into a symmetric stance at up to
1.499996 rad/s. The final action is:

```text
[0, 0, -.5, .25, .25, 0, 0, 0, 0, 0, 0, .5, .25, .25]
```

The 600 locomotion ticks then hold that stance. The sent target changes by as
much as 0.100000143 rad during calibration. All 850 suspended samples reported
no foot contact, so the suspended pass contains no evidence about load-bearing
stability. Grounded x=0 is a bounded standing test, not a no-op and not walking.

## Missing safety mechanisms

The current hardware guard truthfully supports only
`--suspended-or-benched`. The repository instructions explicitly place
grounded replay outside authority. The runtime also has no automatic body-tilt
or both-feet-lost cutoff. Reusing the suspended assertion on the floor would be
false, and relying only on human B-button reaction would omit an automatic
fall detector.

No grounded launcher is therefore created by this design.

## Proposed default-off guard

After a separately approved authority amendment, G3 implementation will add a
mutually exclusive grounded assertion that is valid only for the frozen T247
x=0 command and exact 850-active-tick duration. Existing suspended behavior
will remain unchanged.

Before torque enable, 50 torque-off samples establish a per-run normalized
gravity baseline and require both foot contacts. No policy is staged and no
goal target is written during this readiness window. The stability guard then
runs during home entry, paused hold, calibration, and locomotion, before each
later goal write.

The guard thresholds come from the reviewed nine-label Gate 3 capture, not a
parameter search. Relative to its upright gravity vector, the smallest
operator-labeled tilt was nose-forward at 32.851061755 degrees. That becomes
the one-sample hard cutoff. Half of it, 16.425530877 degrees, becomes the
three-consecutive-tick cutoff. Three ticks reuse the existing watchdog's frozen
consecutive-failure count. Three consecutive invalid acceleration samples or
three consecutive ticks with both contacts false also trip. Every trip raises
the safety exception before another target write, and the existing torque guard
disables torque.

## Physical arrangement

The robot's feet are placed on a clean, level, non-slip floor. Its existing
stand is positioned as a visibly non-contact fall catch around the body; the
stand must not carry robot weight at readiness. The operator remains present
with the known Xbox controller and B immediately available, with hands clear
before torque enable. People, pets, loose cables, and obstacles stay outside
the fall envelope.

No scale, caliper, millimeter placement, or manual center-of-mass value is
required.

## Evidence ladder

1. `G3-O1`: offline implementation and mock fault injection. Prove the default
   remains disabled, each guard fault prevents later writes, every exit torques
   off, and all existing suspended behavior remains unchanged.
2. `G3-S1`: a new, explicitly authorized suspended T247 x=0 revalidation with
   the guard enabled. It must complete the same 250+600 sequence with every
   timing, bus, controller, and safety gate green.
3. `G3`: only after both reviews pass, request exact authorization for one
   grounded x=0 standing run. There is no x=.08 or automatic follow-on path.

## Current stop point

Implementation is blocked by the repository's explicit grounded-authority
boundary. The exact authority-amendment text is frozen in
`artifacts/gates/grounded_validation/GROUNDED_X0_G3_AUTHORITY_AND_SAFETY_DESIGN_20260803.json`.
Approving it authorizes only offline, default-disabled implementation and
preparation of a future suspended revalidation. It does not authorize robot
access, torque, motion, a grounded run, x=.08, or walking.
