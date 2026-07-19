# Active Rebuild Track Reconciliation

Status: `POLICY_HANDOFF_VERIFIED_V2_REQUIRED_GATE5_BLOCKED`

## Authority split

This repository is the active ground-up RDK-X5 runtime rebuild. Its frozen
deployment contract is `open-duck-mini.best-walk.101x14.v1`: one 101-element
observation input, one 14-action output, 50 Hz, deployed phase ordering, and
the inherited 5.24 rad/s slew semantics.

The separate `RobVanProd/open-duck-mini-rdkx5` evidence repository remains the
policy/search and historical-runtime record. Its ground-up composite winner is
a stateful 115-D policy family. The offline winner-v2 composer and P30 observer
cross-fit pass in that repository, but those results do not change this
repository's 101-D contract and do not authorize hardware.

Pinned policy evidence at source commit
`c86c3c96efd978167682ee85dc6741cce2aecb82`:

- winner-v2 runtime contract SHA-256
  `2c0e3f963fb6cb55457d5928a699b8741ebb6b36bf1aa628944d211c99bff18c`;
- observer cross-fit result SHA-256
  `42282815986035105a5ab4f29b1d76ac082142ff096e46a8ffcf260f99362102`;
- P30 pin result SHA-256
  `1c320276f8ea6343a1059f9ec7eda670b596f13141c49a0f7ae69af84ba15c85`.

The evidence-complete handoff superseding that read-only pin is policy commit
`ad1cd8e9b9fdacd26a5453318411dafe423588b4`, artifact root
`artifacts/runtime_handoff/rdkx5_native_20260719`, manifest SHA-256
`ba7143f5c653c0bb2f3f27930a7997dd5a2b90e3258bca516b7240bd0f21abd7`.
The native-runtime review independently reproduced every declared package and
external hash, inspected both graph ABIs, and replayed all 2,400 packaged
ticks. Its accepted disposition is `REQUIRES_REVIEWED_115_RUNTIME_V2`.

## Native-runtime evidence state

On branch `agent/measurement-contract-evidence`:

- Gates 1, 2, 3, and 4 are `PASS_REVIEWED` with committed reduced evidence;
- Gate 4 used the source frozen at commit
  `c5f27598b68fa7d69d81d0675f50a06435ecdaf8`;
- its source archive SHA-256 is
  `5ee4aa30fb11e411ec7cea797c70ebf5aa53d1278e8c873544825253b193ffc8`;
- binding commit `2d2e46c99d6c890676bc2cb4a5c2501b9a2b33b9` froze the launcher and
  validator before execution;
- the exact 30,000-tick sequence completed on 2026-07-19, with tracking p95
  `0.006940 rad` at 0.25 Hz and `0.009892 rad` at 0.5 Hz;
- worst tick p99.9 was `20.010044 ms`, worst bus maximum was `4.574218 ms`, and
  transaction failures, read bursts, alarms, and telemetry drops were all zero;
- final torque-off, UART release, and governor restoration were confirmed;
- Rob observed smooth motion with nothing weird;
- PR #1 carries the reviewed reduced evidence and offline CI checks;
- a fresh local CPU verification passes ruff, 214 pytest cases, the required
  250-tick mock population, and the complete artifact manifest.

The fresh local mock remains `INFORMATIONAL_ONLY`; it is not Gate 4 evidence
and its host-specific timing values are not promoted into a reviewed artifact.

## Verified policy/runtime boundary

The winner family consumes `obs float32[1,115]` plus recurrent
`previous_action float32[1,14]` and returns `continuous_actions` plus
`previous_action_out`, both float32 `[1,14]`. It requires:

- P30 observer-realized target at `obs[83:97]`, not v1's previous commanded
  target;
- projected reference action at `obs[101:115]`;
- phase `[1,0]` at reset and current-phase observation before one advance;
- graph-owned measured rate limits, actual-centered guard, x=0 deadband, and
  recurrent final-action state;
- a host 5.24 limiter that is asserted to be an identity and no head overlay.

The ordering rule is compatible with v1, but the phase reset is not: v1's
inherited `PhaseClock` begins at `[0,0]`. On the exact moving tick-0 golden
inputs, substituting that v1 reset changes output by `0.03805099` and
`0.04923201` normalized action for the two protected graphs. A v2 path must
therefore use its own versioned phase/reset contract rather than mutate or
reuse v1 implicitly.

Full 600-tick CPU replay of both checkpoints at x=0/.080 produced maximum
action/state/chain error `4.7683716e-7`, target-equation error
`1.1920929e-7`, and exact P30 observer agreement, all within `1e-6`.

## Current boundary

Gate 4 is complete and does not authorize Gate 5. The frozen 101x14.v1 path is
unchanged. The verified 115-D winner requires a separately specified, tested,
and reviewed v2 path; it must not be mislabeled as 101-D or wrapped ad hoc.
The policy repository has not selected one deployment checkpoint, its
real-build COM/inertia calculator still lacks 46 inputs, and its robot
clearance is false. Gate 5 remains `NOT_RUN`, blocked, and unauthorized.
