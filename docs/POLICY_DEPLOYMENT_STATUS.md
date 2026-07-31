# Policy Deployment Status

Status date: 2026-07-30

## Executive status

`CANDIDATE_EVALUATION_IN_PROGRESS - ROBOT_CLEARANCE_FALSE - GATE_5_NOT_RUN`

The T234B exact low-command route is the active candidate. It is the first
candidate in this workstream to pass its exact graph contract, a fresh nominal
matrix, the former upper-Z blocker, and the first ten conditions of a fresh
full R2 restart without hosted training.

This is encouraging but not a deployment decision.

## Evidence summary

| Gate | Result |
| --- | --- |
| T234B exact route contract | `PASS` |
| T235 nominal matrix | `16/16 PASS` |
| T236 upper-Z blocker matrix | `16/16 PASS` |
| T237 sequential full R2 | `10/20 conditions; 160/160 completed cells green` |
| T238 deployment-contract audit | `NOT_PREREGISTERED` |
| RDK-X5 CPU preflight for this candidate | `NOT_RUN` |
| Gate 5 | `NOT_RUN` |

T237 contract SHA-256:
`b26a4e5471992f5a2252a9c37cafdf802d5df7d5f8a3c9c1946a3f7cec9fe56b`

T237 progress artifact SHA-256 after condition 10:
`18b334b1e09ff564763b96ae73753e85b4c1ae10a14a10160561a035d5922601`

Completed conditions:

1. floor friction `0.5`;
2. floor friction `1.0`;
3. joint friction loss `0.9x`;
4. joint friction loss `1.1x`;
5. armature scale `1.0x`;
6. armature scale `1.05x`;
7. torso center of mass X offset `-0.05 m`;
8. torso center of mass X offset `+0.05 m`;
9. torso center of mass Y offset `-0.05 m`; and
10. torso center of mass Y offset `+0.05 m`.

Each condition contains both checkpoints, both measured actuator fits, and all
four commands. All 160 completed cells passed duration, gait, tracking, rate,
saturation, and protection rules.

## Why GitHub previously looked idle

T237 writes non-terminal progress to the local hashed artifact store and writes
a repository result only when the sequential gate fails or completes. The
research branch was also 489 commits ahead of GitHub. It was fully pushed on
2026-07-30 and now has zero local/remote divergence.

## Repository consolidation

The research repository had grown to 14,861 tracked files and approximately
622 MiB of packed Git history. It is now treated as the immutable evidence
archive. This native-runtime repository is the compact active deployment
surface. See [`REPOSITORY_BOUNDARIES.md`](REPOSITORY_BOUNDARIES.md).

## Advance rule

No deployment work advances from partial T237 evidence. All 20 conditions must
pass, then T238 must be preregistered and pass. Only then may a runtime-v2
policy handoff be called deployment-ready. Gate 5 still requires its own
explicit hardware authorization.
