# Winner-v2 Policy Handoff Review

Status: `PASS_CPU_HANDOFF_INSPECTION — HOLD_VERSIONED_RUNTIME_V2`

This is the native-runtime repository's independent review of the policy
handoff. It is offline evidence only. It changes no frozen v1 behavior and
authorizes no Gate 5, deployment, RDK-X5 access, torque, or robot motion.

## Evidence identity

- Policy repository: `RobVanProd/open-duck-mini-rdkx5`
- Policy branch: `codex/torso-com-decode-probe`
- Policy commit: `ad1cd8e9b9fdacd26a5453318411dafe423588b4`
- Artifact root: `artifacts/runtime_handoff/rdkx5_native_20260719`
- Manifest SHA-256:
  `ba7143f5c653c0bb2f3f27930a7997dd5a2b90e3258bca516b7240bd0f21abd7`
- Half graph SHA-256:
  `99d3afce0dfac127816c6327665c35b3c403e005f25cd0a505dfcb37f01304de`
- Final graph SHA-256:
  `0dfc24bde5d839e4d346dd8c08d9a7d0222a3847764ec6738bfc7f8d947f4ece`
- Package disposition: `REQUIRES_REVIEWED_115_RUNTIME_V2`
- Selected deployment graph: `NOT_READY`
- Policy-side robot clearance: `false`

The committed manifest blob was hashed directly to avoid Windows line-ending
conversion. A sparse checkout with `core.autocrlf=false` then reproduced the
same hash and every package/external artifact hash and size.

## Independent CPU results

The package's exact `inspect_and_smoke.py` ran under Python 3.12.10 with the
pinned NumPy 2.5.1, ONNX 1.22.0, ONNX Runtime 1.27.0, and only
`CPUExecutionProvider`. It returned
`PASS_CPU_HANDOFF_INSPECTION_BLOCKED_FOR_RUNTIME_REVIEW` with no failures.

Both graph interfaces are:

```text
obs                 float32 [1,115]
previous_action     float32 [1,14]
  -> continuous_actions  float32 [1,14]
  -> previous_action_out float32 [1,14]
```

The package smoke's maximum action/state/chain errors were `8.9406967e-8` for
the 512000 graph and `2.9802322e-8` for the 1024000 graph.

The runtime review extended that check across all four 600-tick packs:

| Check | Maximum absolute error |
| --- | ---: |
| ONNX action | `4.7683716e-7` |
| ONNX recurrent output | `4.7683716e-7` |
| Incoming recurrent chain | `4.7683716e-7` |
| `home + action * 0.25` target equation | `1.1920929e-7 rad` |
| P30 observer versus `obs[83:97]` | `0 rad` |
| P30 observer versus packaged applied target | `0 rad` |

All values pass the frozen `1e-6` tolerance. Every x=0 action and recurrent
output is bit-exact zero, and the external 5.24 rad/s limiter changed no
packaged target.

The reduced machine-readable review is committed at
`artifacts/gates/phase_5_policy/winner_v2_handoff_review_20260719.json`; the
package-smoke and full-chain reductions are committed beside it as
`winner_v2_package_checker_20260719.json` and
`winner_v2_full_chain_verification_20260719.json`.

## Exact compatibility disposition

The shared 0:101 slice numbering does not make the contracts compatible.

| Concern | Frozen runtime v1 | Verified winner-v2 |
| --- | --- | --- |
| ONNX ABI | one `[1,101]` input, one `[1,14]` output | stateful `115+14 -> 14+14` |
| `obs[83:97]` | previous commanded logical target after v1 slew/head overlay | preceding P30 observer-realized absolute logical target |
| `obs[101:115]` | absent | projected reference action at current command/phase |
| phase reset | inherited special `[0,0]` | phase index 0, `[1,0]` |
| phase order | build current observation, then advance | build current observation, infer/send, then advance |
| action state | observation histories only | histories plus explicit `previous_action` state |
| limiting | host global 5.24 rad/s limiter | graph-owned per-joint measured vector; host limiter assertion-only |
| safety transform | none inside a legacy graph assumption | actual-centered guard and x=0 deadband inside ONNX |
| head overlay | permitted by v1 | forbidden for winner-v2 |

Replacing winner-v2 `obs[83:97]` with v1's commanded target first changes the
moving output at tick 1 by `0.03518425` (half) or `0.02920967` (final)
normalized action. Advancing phase/reference early changes tick-0 output by
`0.10399798` or `0.11153935`. Independently, retaining v1's special `[0,0]`
reset phase while keeping the phase-0 reference changes tick-0 output by
`0.03805099` or `0.04923201`. These are semantic failures, not tolerances.

## Required v2 design boundary

A reviewable v2 implementation must be default-off and must not alter v1. It
must include:

1. a versioned 115-element assembler with exact projected-reference lookup;
2. the pinned P30 forward observer initialized from logical home and advanced
   exactly once only after a confirmed logical target send;
3. a stateful preallocated ONNX host with explicit zero reset and chained
   `previous_action_out`;
4. a v2 phase clock starting at `[1,0]` and advancing once per confirmed tick;
5. a target path that proves the inherited host limiter is an identity and
   rejects any head overlay/filter/additional projection;
6. fail-closed handling for stale sensors, failed sends, ambiguous observer
   state, unsupported commands, wrong hashes, and nonfinite tensors;
7. a CPU verifier that replays every field of all four 600-tick packs within
   `1e-6`, with bit-exact x=0 output/state;
8. separate runtime provenance and telemetry schemas so v1 and v2 evidence
   cannot be mixed.

This review does not select between the 512000 and 1024000 graphs. That choice
must come from a policy-repository decision that does not select post hoc from
the persistence pair.

## Remaining blockers

1. No single deployment checkpoint is selected (`SELECTED_ONNX_SHA256=NOT_READY`).
2. The versioned v2 runtime path above is not implemented or reviewed.
3. The real-build torso COM/inertia packet lacks 46 required fields and emits
   no numerical estimate.
4. Policy-side robot clearance is false.
5. Gate 5 has no authorized v2 launcher or hardware run.

Gate 5 remains `NOT_RUN`. Grounded replay remains outside this repository's
authority.
