# Active Runtime ↔ Policy Handoff

This is the compact current handoff. Historical exchanges remain in
[`docs/archive/COMMS_HISTORY_THROUGH_20260722.md`](docs/archive/COMMS_HISTORY_THROUGH_20260722.md),
and the detailed deployment state lives in
[`docs/POLICY_DEPLOYMENT_STATUS.md`](docs/POLICY_DEPLOYMENT_STATUS.md).

## Current decision

`T247 GATE-5 x=0 PASS_REVIEWED; x=.08 STAGED EXACT, AUTHORIZATION NEXT`

T247 remains the unchanged selected policy. T250 and T251 were contract,
attribution, and host-optimization evidence labels; they did not replace the
policy.

| Boundary | Current evidence |
| --- | --- |
| Offline behavior | T249B: 20/20 conditions, 320/320 cells pass |
| Policy ABI | Explicit two-stage 115-D/14-action T247 path; default 101-D v1 unchanged |
| X5 compute | x=0 and x=.08 exact routes pass 35/35 with zero rate excess |
| Runtime wiring | 18/18 real-asset mock checks pass, including pause and failed-write cleanup |
| Hardware | Gates 1-4 and suspended T247 Gate 5 x=0 `PASS_REVIEWED`; x=.08 `NOT_RUN` |

## Frozen assets

| Role | SHA-256 |
| --- | --- |
| Terminal policy | `dadfb446ea7c720f274a15bc65e9171c2e74d715ccfaf58adbb408b6c1365a54` |
| Calibrator | `0f3aebfd9946a6271fdb14adec3d68d556648f270984639d372c973a7d7dc576` |
| P30 observer fit | `a58db8ffc505d2bb64cba7f5618d0e2c65904fc9f9ac37b560a1231e090f5f4f` |
| Reference table | `8102d9cd139584816d807ca635bcca6d37fa6b3c455848e00395b6d565968212` |
| Command manifest | `5621f7c6782a8346bf25f05ce7f0bc002acbe8e98872cf658f0d44773511b4cd` |
| Context router | `3b1f406fba5147a3f38ec59fc7f9c8d42dd27fa7eeb54344f447c060eb95b284` |

The readiness-cued suspended x=0 run completed exactly 250 calibration plus 600
locomotion ticks. All 56,960 transactions succeeded; tick p99/p99.9 were
20.058568/20.115872 ms; bus p99.9/max were 3.836193/3.919508 ms; every summary
gate passed; and the operator reported normal motion and sound. Runtime and an
independent all-14 register readback confirmed torque off. The accepted receipt
is `T247_X0_READINESS_CUED_PASS_REVIEWED_20260802.json`.

## Exact T247 ABI

```text
calibrator inputs:  obs[1,115], previous_action[1,14], h_in[1,64]
calibrator outputs: calibration_actions[1,14], previous_action_out[1,14], h_out[1,64]

locomotion inputs:  obs[1,115], previous_action[1,14], h_in[1,64], calibration_context[1,64]
locomotion outputs: continuous_actions[1,14], previous_action_out[1,14], h_out[1,64]
```

The handoff occurs after exactly 250 confirmed calibration writes. The final
calibrator context becomes immutable; previous-action state is carried across;
locomotion hidden state and phase initialize by the frozen contract. Every
state advance is owned by a confirmed successful servo write.

## Runtime facts the policy side must preserve

- Logical joint order and the 115-D observation mapping are frozen.
- The applied-target slot has the exact training meaning; no 101/115 adapter is
  allowed.
- The runtime selects one of six calibration-context routes, then x000 or x080
  for Gate 5; all graph outputs remain byte-exact to T247.
- The wire read order is `20,21,22,23,24,30,31,32,33,10,11,12,14,13`; logical
  policy order is unchanged.
- Gate 5 uses 250 calibration plus 600 locomotion ticks at 50 Hz.

## Next action

No training or policy modification is selected. The distinct x=.08-only
launcher is frozen, green in CI, and staged at exact commit `90b685b` against
the reviewed x=0 receipt. Obtain fresh exact suspended-motion authorization.
Do not reuse the x=0 launcher or start x=.08 automatically.

Grounded replay remains outside authority.
