# Automatic Configuration Support

Status: `OFFLINE_DECISION_LAYER_IMPLEMENTED — PHYSICAL_COLLECTION_NOT_RUN`

The robot must tolerate supported assembly variation without requiring the
operator to measure or enter a center of mass. This design separates two facts
that should not be conflated:

1. The policy must pass a preregistered simulation domain covering plausible
   mass, X/Y/Z COM, inertia, and optional-component combinations.
2. A physical robot may automatically demonstrate that its observable response
   lies inside the policy's supported response envelope.

The second step does not claim to recover an exact, uniquely identifiable COM.
Stationary IMU, encoder, and binary-contact readings cannot do that. It instead
uses machine-collected actuator and body-response quantities that can be
observed directly: delay, gain, time constant, tracking error, current, body
pitch/roll rate, and acceleration norm.

## Implemented offline validator

`validate_configuration_support` compares two JSON files:

- an `open_duck_x5.automatic_configuration_profile.v1` profile produced by a
  future automatic supported-excitation collector; and
- an `open_duck_x5.supported_configuration_envelope.v1` artifact produced by
  the policy repository after its robustness gate passes.

The validator is strict and fail-closed. It requires:

- source method `automatic_supported_excitation`;
- `manual_measurements_used=false`;
- explicit motion authorization, supported/benched state, and final torque-off
  confirmation in the collected evidence;
- the frozen 14 required servo IDs, BNO055, and both contacts;
- 50 Hz, a complete sample population, and zero stale samples, transaction
  failures, or telemetry drops;
- all five observable response metrics for every frozen joint;
- all three body-response metrics;
- a policy domain spanning at least `[-50 mm,+50 mm]` torso X-COM plus
  nondegenerate mass, Y/Z COM, and three-axis inertia variation;
- coupled and held-out policy samples plus at least two supported optional-part
  configurations; and
- every automatically observed metric inside the policy-provided bounds.

The profile schema has no field for an entered mass, COM, inertia, scale
reading, caliper reading, or component inventory. Extra fields are rejected.
The result keeps robot clearance, Gate 5, deployment, and motion authority
false even when the response comparison passes; it is one input to a later
review, not a launcher.

Example offline invocation:

```bash
validate_configuration_support \
  --profile automatic-profile.json \
  --envelope policy-supported-envelope.json \
  --output configuration-support-result.json
```

The command exits zero only for
`PASS_AUTOMATIC_CONFIGURATION_INSIDE_POLICY_ENVELOPE`. Missing hardware,
incomplete evidence, or an out-of-envelope response produces a hold. Invalid
or manually measured evidence is rejected.

## Physical collector still required

No physical excitation collector has been run or authorized by this work. Its
future implementation must preserve this sequence:

1. torque-off inventory of required servos and sensors;
2. halt without torque if any contract-required component is missing;
3. separately authorized, supported/benched, no-policy excitation with frozen
   amplitude, duration, order, watchdog, and stop thresholds;
4. direct capture of servo state/current and timestamp-aligned IMU response;
5. automatic metric extraction with immutable raw-trace SHA-256; and
6. redundant torque-off before emitting a complete profile.

Missing shells, covers, mounts, or other supported non-locomotion pieces must
be represented in the policy domain rather than entered manually. Missing a
contract-required leg, neck/head actuator, IMU, or contact sensor cannot be
silently hidden from the frozen policy interface; walking remains disabled,
while torque-off diagnostics can still report the missing hardware.

This module does not modify the frozen 101-D v1 observation contract or the
separate 115-D winner-v2 contract, does not load ONNX, and has no serial, GPIO,
I2C, torque, or motion path.
