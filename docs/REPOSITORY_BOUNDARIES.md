# Repository Boundaries

The project now has two intentionally different repositories. They should not
be recombined.

## Active deployment repository

[`RobVanProd/open-duck-mini-rdkx5-native-runtime`](https://github.com/RobVanProd/open-duck-mini-rdkx5-native-runtime)
is the compact product repository.

It owns:

- the X5-native runtime;
- the frozen runtime-v1 contract and the isolated runtime-v2 host;
- bus, timing, sensor, safety, and controller code;
- setup and hardware-gate runbooks;
- reviewed hardware evidence;
- the current policy handoff and deployment audit; and
- the eventual Gate 5 launch packet.

It does not own research sweeps, training traces, discarded mechanisms, or
thousands of one-off campaign evaluators.

## Research and evidence archive

[`RobVanProd/open-duck-mini-rdkx5`](https://github.com/RobVanProd/open-duck-mini-rdkx5)
is the immutable research/evidence archive. Its active evidence branch is
[`codex/winner-v4-response-contract`](https://github.com/RobVanProd/open-duck-mini-rdkx5/tree/codex/winner-v4-response-contract).

It owns:

- preregistered policy experiments and their source receipts;
- historical candidate and failure analyses;
- CPU robustness matrices;
- training and evaluator contracts;
- one-off falsifiers; and
- the complete audit trail needed to reproduce a policy decision.

The archive is deliberately large. Deleting files on its current branch would
not remove its Git history and would weaken provenance. It is therefore
classified as an archive rather than treated as the deployment workspace.

## Handoff rule

Nothing crosses from the archive into the active runtime merely because it is
the closest checkpoint or currently looks promising. A policy may cross only
as a minimal SHA-bound handoff packet after its complete offline decision gate
passes.

The packet must contain:

1. both mandatory checkpoint graph receipts;
2. exact input/output names, shapes, dtypes, and recurrent-state semantics;
3. observation-field semantics and golden-vector evidence;
4. action, command-route, rate, and state-feedback semantics;
5. full robustness and persistence results;
6. runtime compatibility and reset/rollback checks; and
7. an explicit `ROBOT_CLEARANCE` decision.

Policy binaries remain external artifacts unless a separate reviewed
distribution decision authorizes them. This repository stores hashes and
manifests, not unreviewed binaries.

## Current consolidation

- Root [`Comms.md`](../Comms.md) is now the short active handoff.
- Prior handoff history is preserved under
  [`docs/archive/COMMS_HISTORY_THROUGH_20260722.md`](archive/COMMS_HISTORY_THROUGH_20260722.md).
- [`docs/POLICY_DEPLOYMENT_STATUS.md`](POLICY_DEPLOYMENT_STATUS.md) is the
  human-readable current policy status.
- [`status/policy_gate.json`](../status/policy_gate.json) is its
  machine-readable counterpart.

