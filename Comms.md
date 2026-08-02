# Active Runtime ↔ Policy Handoff

This is the compact current handoff. Historical exchanges remain in
[`docs/archive/COMMS_HISTORY_THROUGH_20260722.md`](docs/archive/COMMS_HISTORY_THROUGH_20260722.md),
and the detailed deployment state lives in
[`docs/POLICY_DEPLOYMENT_STATUS.md`](docs/POLICY_DEPLOYMENT_STATUS.md).

## Current decision

`T247 GATE-5 x=0 ATTEMPT 1 HALTED PRE-POLICY; TORQUE-OFF REPAIR PREFLIGHT NEXT`

T247 remains the unchanged selected policy. T250 and T251 were contract,
attribution, and host-optimization evidence labels; they did not replace the
policy.

| Boundary | Current evidence |
| --- | --- |
| Offline behavior | T249B: 20/20 conditions, 320/320 cells pass |
| Policy ABI | Explicit two-stage 115-D/14-action T247 path; default 101-D v1 unchanged |
| X5 compute | x=0 and x=.08 exact routes pass 35/35 with zero rate excess |
| Runtime wiring | 18/18 real-asset mock checks pass, including pause and failed-write cleanup |
| Hardware | Gates 1-4 `PASS_REVIEWED`; Gate 5 attempt 1 halted pre-policy and did not pass |

## Frozen assets

| Role | SHA-256 |
| --- | --- |
| Terminal policy | `dadfb446ea7c720f274a15bc65e9171c2e74d715ccfaf58adbb408b6c1365a54` |
| Calibrator | `0f3aebfd9946a6271fdb14adec3d68d556648f270984639d372c973a7d7dc576` |
| P30 observer fit | `a58db8ffc505d2bb64cba7f5618d0e2c65904fc9f9ac37b560a1231e090f5f4f` |
| Reference table | `8102d9cd139584816d807ca635bcca6d37fa6b3c455848e00395b6d565968212` |
| Command manifest | `5621f7c6782a8346bf25f05ce7f0bc002acbe8e98872cf658f0d44773511b4cd` |
| Context router | `3b1f406fba5147a3f38ec59fc7f9c8d42dd27fa7eeb54344f447c060eb95b284` |

The external T247 asset bundle and reviewed source were staged on the X5 for
the authorized attempt. The invocation halted while paused after zero active
policy ticks. Torque-off and governor restoration were confirmed.

The halt is attributed to an in-process pygame/Bluetooth hotplug GIL stall plus
late serial data being accepted as `OK`. The selected repair removes the Linux
pygame polling thread, rejects post-deadline bytes, and enforces controller
freshness while paused. Gate 5 is held until controller-only and 10,000-tick
controller-present torque-off validation pass.

The controller-only step now passes on the original Xbox identity
`0C:35:26:2A:B8:0B`: 10,000/10,000 direct 50 Hz reads, exactly one A edge,
zero disconnects, unchanged joydev inode, and no UART or servo access. The
second identity `0C:35:26:3E:55:F6` is rejected after repeated HID-over-GATT
failures. The next launcher must verify the known-good sysfs `uniq` before it
opens the UART.

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

No training or policy modification is selected. Run the frozen 10,000-tick
controller-present torque-off probe. Only a reviewed pass can earn a replacement
x=0 launcher and fresh motion authorization. The old launcher must not be
reused. x=.08 remains blocked behind a reviewed green x=0 receipt.

Grounded replay remains outside authority.
