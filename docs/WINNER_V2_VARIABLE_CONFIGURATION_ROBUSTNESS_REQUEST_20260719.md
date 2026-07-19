# Winner-v2 Variable-Configuration Robustness Request

Status: `REQUEST_POLICY_ROBUSTNESS_REPLACEMENT — NO_PER_UNIT_COM_MEASUREMENT`

## Product requirement

Open Duck Mini is expected to be disassembled, reassembled, and tested with
optional non-locomotion parts installed, removed, or repositioned. A single
as-built torso center-of-mass value is therefore not a valid deployment
assumption. The operator will not be required to buy measuring equipment,
disassemble the robot for measurement, or enter mass, center-of-mass, or
inertia numbers.

This supersedes the powered-off direct-reaction and component-measurement
routes as advancement requirements. Their files remain only as historical
records of the rejected route.

## Why the current candidate is held

The selected winner-v2 asset set remains internally verified and hash-frozen,
but the policy-side torso-X sweep demonstrates configuration sensitivity. Its
raw bracket passes through `-22.65625 mm` and fails at `-23.4375 mm`; in the
other direction it passes through `+5.46875 mm` and fails at `+6.25 mm`.
Those results come from
`outputs/analysis/composite_winner_torso_com_break_radius_result.json`
(policy-side SHA-256
`6b84b34e7280b0f0d92109a70444d18af7b0196cd3555530b8f42e70dea54e32`).

That bracket is evidence that the candidate is too configuration-sensitive;
it is not a reason to measure one robot more precisely. The reviewed offline
asset freeze remains valid historical evidence for the exact candidate, but
the candidate is held from robot clearance and Gate 5.

## Policy-side replacement gate

Before evaluating another deployment candidate, preregister a CPU-only
supported-configuration domain that is independent of this robot's measured
COM and independent of evaluation outcomes. The gate must cover:

- torso mass variation;
- torso COM variation in X, Y, and Z;
- torso inertia variation;
- coupled mass/COM/inertia samples, not only one-axis sweeps;
- intended optional covers, head/body pieces, mounts, cooling, wiring, and
  battery arrangements, including supported present/absent combinations;
- the existing measured actuator fits, delays, sensor conditions, commands,
  checkpoints, and behavior/safety gates; and
- held-out combinations or seeds that are not used to select the policy.

At minimum, the X domain must include the already evaluated `[-50 mm,
+50 mm]` sweep so that a replacement cannot be narrower than the evidence
that exposed this failure. The policy repository must define and justify the
remaining mass, Y/Z COM, inertia, and discrete optional-component ranges from
the supported mechanical configuration envelope before observing candidate
results.

Run the current frozen candidate first. If any preregistered cell fails, do
not waive the failure with a per-build measurement; train or select a policy
with domain randomization over the same frozen envelope and rerun the complete
gate. A new policy graph or contract package requires a new two-repository
asset freeze.

## Automated configuration handling

Runtime startup continues to inventory every contract-required servo and
sensor. Missing or mismatched locomotion-critical hardware fails closed for
walking while leaving torque-off diagnostic tools available. Optional
non-locomotion pieces are handled by the policy's supported-configuration
domain rather than a static entered COM.

A separate automatic supported-calibration mode may estimate effective delay,
gain, lag, asymmetry, and inertial response from a small reviewed excitation
sequence using servo feedback, current telemetry, and the IMU. It must:

- require no ruler, caliper, scale, manual COM entry, or component inventory;
- identify effective behavior rather than claim an unobservable exact static
  COM from stationary sensors;
- compare the result with the frozen supported domain and fail closed when the
  response is outside it; and
- require separate motion authorization before any physical excitation.

This calibration can improve adaptation and detect bad assemblies. It cannot
be used to excuse a policy that only works for one millimeter-specific build.

## Authority

This request authorizes policy-side CPU simulation, evaluation, and training
only. It authorizes no robot or RDK-X5 access, serial/GPIO/I2C use, torque,
motion, Gate 5, deployment, GPU, or iGPU action. The current selected ONNX
retains `robot_clearance=false`.
