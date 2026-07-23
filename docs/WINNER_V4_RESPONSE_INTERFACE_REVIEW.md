# Winner-v4 Response73 Runtime Schema Review — 2026-07-20

status: `PASS_RESPONSE73_FIELD_MAP_HOLD_POLICY_CONDITIONING_READINESS`

decision: `HOLD_TRAINING_PENDING_SIGNED_X_AND_SUPPORT_MODE_CONTRACT`

JSON SHA-256: `e860ac7c93565ef6bba9bc08435565faa75cca0768dc7392f6415b66629f55f8`

Policy request: `RobVanProd/open-duck-mini-rdkx5@6a5d43cd6aacd8cc9a989182444e8a7416c35299`

Artifact: `outputs/analysis/winner_v4_response_interface_preregistration.json`

Artifact SHA-256: `562ea92c4ba9eb026263740a07fe349ed79e051f0a162e8dd476812f089b6adc`
PR: https://github.com/RobVanProd/open-duck-mini-rdkx5/pull/76

## Accepted field map

Runtime can produce the proposed `response_context[1,73]` as a separate,
preallocated, immutable float32 ONNX input without changing `obs[115]`, action,
phase, previous-action, or recurrent-state semantics. The exact order is the
five profile-v4 joint metrics for each frozen joint in logical order (70 values),
then the three body metrics. Runtime applies no scaling; normalization belongs
inside the policy graph. Missing, invalid, stale, unreproducible, or
out-of-envelope profile evidence must prevent policy arming. No default value
or stale substitution is accepted.

The committed review-only flattener proves the order is constructible and
fail-closed. It is not connected to the policy loader or control loop.

## Why training remains held

The field map is valid, but profile v4 was originally an envelope-checking
artifact, not a policy-conditioning contract. Two gaps must be resolved before
PPO:

1. Its three body metrics are absolute p95 magnitudes aggregated over the whole
   trace. They contain no explicit sign or per-joint-stage body response. The
   policy's already-preregistered signed-X endpoint screen must prove that the
   complete 73-vector does not collapse the two failure signs.
2. The profile records only `suspended_or_benched=true`. It does not identify
   whether the torso is supported, the robot is free-hanging, or the feet carry
   load. Because those boundaries can change measured response, policy must
   freeze exactly one automatic-calibration support mode and its simulator
   realization, rejecting every other mode, or prove feature invariance across
   all accepted modes.

If signed X collapses, response73 closes without training. Any sign-preserving
profile extension requires a new exact policy proposal and runtime review.

## Authority

This is schema review only. No runtime policy path was implemented. It authorizes
no training, Colab, GPU/iGPU, X5 or robot access, serial/GPIO/I2C, torque,
motion, Gate 5, deployment, or robot clearance.
