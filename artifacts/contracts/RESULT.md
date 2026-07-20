# Legacy Contract Snapshot Result

Status: `PASS_DEPLOYED_CONTRACT`

Source: preserved-runtime suspended telemetry ticks 0 and 1 from
`suspended_policy_replay_x008_corrected_knee.jsonl`.

- source JSONL SHA-256:
  `22115c03b115c8df77f5d4510137b22a5fd696703d7f1190205e770072077ba4`
- frozen policy SHA-256 recorded by telemetry:
  `3c606f9381a1710cc8fecdb7442787dcbfce3ee9bc02a6f1224774ab2b3a1067`
- snapshot: `legacy-contract-snapshot.json`
- field-by-field report: `legacy-contract-report.json`

The report passes all 101 observation elements and all 14 logical and physical
targets with zero mismatch and zero maximum absolute difference. The source uses
the corrected left-knee soft offset `0.0371` rad, not the older `-1.488` value.

The adjacent pair additionally proves that deployed `obs[83:97]` equals the prior
post-slew, post-head-overlay sent logical target. In the captured pair its maximum
difference from the prior sent target is `0.0` rad, while its maximum difference
from the prior measured joint position is `0.1078` rad. It is commanded state, not
measured realized position.

The phase evidence proves the observation uses the prior tick's post-advance phase;
it does not use the phase value advanced later in the same control iteration.

This closes the preserved-runtime golden-vector comparison. It does **not** grant
policy Gate 5 clearance: the selected offline winner must still prove matching
training semantics for target quantity, phase order, and the 5.24 rad/s slew rule.
No servo transaction, inference, torque write, or new motion occurred while this
artifact was produced; it was derived from existing suspended telemetry.
