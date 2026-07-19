# Active Rebuild Track Reconciliation

Status: `NATIVE_RUNTIME_GATE4_PASS_GATE5_BLOCKED`

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

## Current boundary

Gate 4 is complete and does not authorize Gate 5. A legacy 101-D policy
can exercise the frozen 101x14.v1 stack only under its Gate 5 contract. The
115-D composite winner requires a separately reviewed interface/handoff path;
it must not be mislabeled as 101-D, wrapped ad hoc, or treated as robot-cleared.
The separate COM measurement remains relevant to eventual winner deployment,
not to the completed native-runtime Gate 4. Until the observation/action handoff
is resolved with golden vectors and an explicitly reviewed deployable export,
Gate 5 remains `NOT_RUN`, blocked, and unauthorized.
