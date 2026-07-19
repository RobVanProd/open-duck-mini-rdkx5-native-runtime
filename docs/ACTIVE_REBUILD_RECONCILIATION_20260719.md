# Active Rebuild Track Reconciliation

Status: `NATIVE_RUNTIME_ACTIVE_GATE4_NEXT`

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

## Native-runtime evidence state

On branch `agent/measurement-contract-evidence`:

- Gates 1, 2, and 3 are `PASS_REVIEWED` with committed reduced evidence;
- Gate 4 is `NOT_RUN` and fully frozen at source commit
  `c5f27598b68fa7d69d81d0675f50a06435ecdaf8`;
- its source archive SHA-256 is
  `5ee4aa30fb11e411ec7cea797c70ebf5aa53d1278e8c873544825253b193ffc8`;
- binding commit `2d2e46c99d6c890676bc2cb4a5c2501b9a2b33b9` is the branch tip at
  reconciliation time;
- PR #1 is mergeable and both offline CI checks pass;
- a fresh local CPU verification passes ruff, 214 pytest cases, the required
  250-tick mock population, and the complete artifact manifest.

The fresh local mock remains `INFORMATIONAL_ONLY`; it is not Gate 4 evidence
and its host-specific timing values are not promoted into a reviewed artifact.

## Correct next boundary

Gate 4 is the next sequential rebuild step. It uses no policy or ONNX graph and
does not depend on the unresolved real-build torso-COM measurement. Its exact
physical scope remains the preregistered supported/benched left-hip-yaw
(servo 20) sequence: torque-off 10,000-tick preflight, then 0.03 rad at 0.25 Hz,
then 0.5 Hz only if the first moving population independently passes.

The gate remains unauthorized until Rob explicitly approves that exact moving
sequence while physically present. No parameter, joint, duration, frequency,
amplitude, timing threshold, or stop rule may change after authorization.

If Gate 4 passes, Gate 5 is still a separate decision. A legacy 101-D policy
can exercise the frozen 101x14.v1 stack only under its Gate 5 contract. The
115-D composite winner requires a separately reviewed interface/handoff path;
it must not be mislabeled as 101-D, wrapped ad hoc, or treated as robot-cleared.
The separate COM measurement remains relevant to eventual winner deployment,
not to completion of native-runtime Gate 4.
