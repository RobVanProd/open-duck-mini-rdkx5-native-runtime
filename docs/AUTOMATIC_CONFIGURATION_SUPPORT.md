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

- an `open_duck_x5.automatic_configuration_profile.v4` generated profile;
- its immutable excitation JSONL and metadata inputs;
- the exact `duck_config.json` whose soft offsets define physical home; and
- an `open_duck_x5.supported_configuration_envelope.v1` artifact produced by
  the policy repository after its robustness gate passes and frozen before the
  physical response is collected.

The validator is strict and fail-closed. It requires:

- source method `automatic_supported_excitation`;
- `manual_measurements_used=false`;
- explicit motion authorization, supported/benched state, and final torque-off
  confirmation in the collected evidence;
- the frozen 14 required servo IDs, BNO055, and both contacts;
- 50 Hz, a complete sample population, and zero stale samples, transaction
  failures, or telemetry drops;
- tick p99 at most `21 ms`, tick p99.9 at most `22 ms`, and complete-sweep bus
  maximum strictly below `5 ms` from the raw tick population;
- all five observable response metrics for every frozen joint;
- all three body-response metrics;
- a policy domain spanning at least `[-50 mm,+50 mm]` torso X-COM plus
  nondegenerate mass, Y/Z COM, and three-axis inertia variation;
- coupled and held-out policy samples plus at least two supported optional-part
  configurations; and
- every automatically observed metric inside the policy-provided bounds.

Before comparison, the validator verifies that the envelope file SHA-256 is the
same identity precommitted in the physical metadata/profile. It then
regenerates the profile from the supplied trace, metadata, and configuration.
The profile must reproduce structurally
and numerically (maximum absolute numeric difference `1e-9`), its three
raw-input SHA-256 identities must match, and its fourth identity must match the
precommitted envelope. Supplying a hand-edited profile
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

- `open_duck_x5.configuration_excitation_metadata.v3` JSON; and
- contiguous `open_duck_x5.configuration_excitation_tick.v2` JSONL.

The metadata freezes 50 Hz, the complete tick count, one contiguous stage per
joint in frozen joint order, fit horizon, minimum excitation, current-sample
coverage, hardware inventory, authorization, supported state, zero telemetry
drops, final torque-off, the exact configuration SHA-256, and the physical home
vector derived from frozen home plus that configuration's soft offsets. Serial
metadata also requires the already-frozen policy-envelope SHA-256. It has no
accepted physical-parameter field.

Every raw row contains the stage label, tick and bus timing, 14 sent targets,
14 measured positions, per-joint current samples or nulls, gyro, acceleration,
contact values, separate monotonic IMU/contact sample timestamps, all servo
statuses/staleness, and IMU/contact staleness. The extractor rejects
gaps, mixed stage labels, nonfinite data, stale or failed samples, simultaneous
cross-joint excitation, insufficient current coverage, target span above
`0.06 rad`, target velocity above the frozen `0.25 rad/s` ceiling, backward
sensor timestamps, or a timing population outside the runtime gates.

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

## Implemented guarded collector

`collect_automatic_configuration` now implements the complete collection path.
Its default is mock, its mock result is permanently marked informational, and
the final validator cannot turn a mock profile into a physical PASS. The fixed
collection is 2,814 ticks: 201 ticks for each frozen joint in frozen order,
using a smooth two-frequency signal that begins and ends at home, stays within
`0.03 rad`, and stays below `0.21 rad/s`. JSON serialization runs on a bounded,
preallocated background writer. The serial path requires isolated-core
`SCHED_FIFO`, the exact BNO055 calibration, and all four explicit assertions:
`--hardware-authorized`, `--suspended-or-benched`,
`--moving-gate-authorized`, and `--configuration-calibration-authorized`, plus
`--policy-envelope` pointing to a structurally valid, already-passed policy
envelope. The envelope is parsed and hashed before the serial bus is opened.

The collector preserves this sequence:

1. torque-off inventory of required servos and sensors;
2. halt without torque if any contract-required component is missing;
3. separately authorized, supported/benched, no-policy excitation with frozen
   amplitude, duration, order, watchdog, and stop thresholds;
4. direct capture of servo state/current and timestamp-aligned IMU response;
5. automatic metric extraction with immutable trace, metadata, and config
   SHA-256 identities; and
6. redundant torque-off before emitting a complete profile.

Example mock-only contract run:

```bash
collect_automatic_configuration \
  --bus mock --mock-no-wait \
  --config duck_config.example.json \
  --trace excitation.jsonl \
  --metadata excitation-metadata.json \
  --profile automatic-profile.json
```

The serial command is intentionally not presented as an executable gate: its
source/config/calibration/envelope hashes and exact motion authorization must
be frozen in a reviewed run artifact first. No physical collection has been run or
authorized by this work, so physical status remains `NOT_RUN`.

Missing shells, covers, mounts, or other supported non-locomotion pieces must
be represented in the policy domain rather than entered manually. Missing a
contract-required leg, neck/head actuator, IMU, or contact sensor cannot be
silently hidden from the frozen policy interface; walking remains disabled,
while torque-off diagnostics can still report the missing hardware.

The profile builder and support validator do not modify the frozen 101-D v1
observation contract or the separate 115-D winner-v2 contract and never load
ONNX. The distinct guarded collector owns the serial, GPIO, I2C, torque, and
bounded calibration-motion path described above.
