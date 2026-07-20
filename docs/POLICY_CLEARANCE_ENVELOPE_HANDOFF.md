# Policy clearance and configuration-envelope handoff

Status: `WAITING_POLICY_ARTIFACTS — NO_X5_OR_ROBOT_EXECUTION`

The runtime accepts policy envelope schema
`open_duck_x5.supported_configuration_envelope.v2`. It does not accept a bare
clearance assertion. Policy must first commit this exact-shape decision artifact:

```json
{
  "schema_version": "open_duck_x5.policy_robot_clearance.v1",
  "robot_clearance": true,
  "policy": {
    "onnx_sha256": "<selected ONNX SHA-256>",
    "contract_id": "winner-v2-115d"
  },
  "supported_configuration_gate_passed": true
}
```

The later envelope artifact must include this additional object alongside the
selected policy, preregistration, broad configuration domain, and all 73
observable-response bounds:

```json
"clearance": {
  "robot_clearance": true,
  "commit": "<commit containing the clearance decision>",
  "artifact_path": "<repository-relative POSIX path>",
  "artifact_sha256": "<exact clearance artifact SHA-256>"
}
```

Return four Git identities:

1. preregistration commit and artifact path/SHA-256;
2. selected-policy commit and exact ONNX SHA-256;
3. clearance-decision commit and artifact path/SHA-256; and
4. later envelope-publication commit and artifact path/SHA-256.

Runtime independently reads all committed bytes, checks the official repository
origin, and proves preregistration -> selected policy -> clearance decision ->
envelope publication ancestry. The clearance and envelope artifacts cannot
self-reference the commit that first introduces them.

This handoff requires no per-unit mass, COM, inertia, ruler, caliper, scale, or
manual component inventory. It authorizes no X5 inference, serial access,
torque, motion, automatic calibration, Gate 5, deployment, or grounded walking.
