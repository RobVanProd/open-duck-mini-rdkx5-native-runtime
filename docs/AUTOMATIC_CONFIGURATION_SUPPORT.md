# Automatic Configuration Support

Status: `OFFLINE_EXTRACTION_AND_DECISION_IMPLEMENTED — PHYSICAL_COLLECTION_NOT_RUN`

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

`validate_configuration_support` verifies one complete evidence chain:

- an `open_duck_x5.automatic_configuration_profile.v2` generated profile;
- its immutable excitation JSONL and metadata inputs;
- the exact `duck_config.json` whose soft offsets define physical home; and
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

Before comparison, the validator regenerates the profile from the supplied
trace, metadata, and configuration. The profile must reproduce structurally
and numerically (maximum absolute numeric difference `1e-9`) and its three
SHA-256 identities must match those raw inputs. Supplying a hand-edited profile
with plausible hash strings cannot produce the full-chain PASS status.

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
  --trace excitation.jsonl \
  --metadata excitation-metadata.json \
  --configuration duck_config.json \
  --output configuration-support-result.json
```

The command exits zero only for
`PASS_AUTOMATIC_CONFIGURATION_INSIDE_POLICY_ENVELOPE`. Missing hardware,
incomplete evidence, or an out-of-envelope response produces a hold. Invalid
or manually measured evidence is rejected.

## Implemented trace-to-profile extraction

`build_automatic_configuration_profile` converts immutable raw excitation
evidence into the profile above. It accepts:

- `open_duck_x5.configuration_excitation_metadata.v1` JSON; and
- contiguous `open_duck_x5.configuration_excitation_tick.v1` JSONL.

The metadata freezes 50 Hz, the complete tick count, one contiguous stage per
joint in frozen joint order, fit horizon, minimum excitation, current-sample
coverage, hardware inventory, authorization, supported state, zero telemetry
drops, final torque-off, the exact configuration SHA-256, and the physical home
vector derived from frozen home plus that configuration's soft offsets. It has
no accepted physical-parameter field.

Every raw row contains the stage label, 14 sent targets, 14 measured positions,
per-joint current samples or nulls, timestamp-aligned gyro and acceleration,
all servo statuses/staleness, and IMU/contact staleness. The extractor rejects
gaps, mixed stage labels, nonfinite data, stale or failed samples, simultaneous
cross-joint excitation, insufficient current coverage, target span above
`0.06 rad`, or target velocity above the frozen `0.25 rad/s` ceiling.

For each joint it fits the discrete first-order response
`actual[t] = a*actual[t-1] + b*target[t-delay] + c` across a bounded delay
search, then reports delay, steady-state gain, time constant, tracking p95, and
current p95. It calculates body pitch/roll-rate p95 and acceleration-norm p95
directly from the same timestamped rows. The generated profile is immediately
revalidated against the strict automatic-profile contract before it is written.

```bash
build_automatic_configuration_profile \
  --trace excitation.jsonl \
  --metadata excitation-metadata.json \
  --configuration duck_config.json \
  --output automatic-profile.json
```

Synthetic tests recover an injected two-tick delay, `0.9` gain, and known time
constant for all 14 joints, then pass the resulting profile through the full
73-metric policy-envelope validator.

## Physical collector still required

No physical excitation collector has been run or authorized by this work. The
offline extractor consumes its future output but cannot access hardware. The
collector's future implementation must preserve this sequence:

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
