# Policy Deployment Status

Status date: 2026-07-31

## Executive status

`CANDIDATE_CLOSED - ROBOT_CLEARANCE_FALSE - GATE_5_NOT_RUN`

The T234B exact low-command route passed its exact graph contract, a fresh
nominal matrix, the former upper-Z blocker, and the first 16 conditions of a
fresh full R2 restart without hosted training. It then failed condition 17,
the `-0.03 rad` home-joint-offset condition, in all 16 cells.

The route is closed and cannot advance to the deployment-contract audit.

## Evidence summary

| Gate | Result |
| --- | --- |
| T234B exact route contract | `PASS` |
| T235 nominal matrix | `16/16 PASS` |
| T236 upper-Z blocker matrix | `16/16 PASS` |
| T237 sequential full R2 | `FAIL at condition 17; 256/272 cells green` |
| T238 deployment-contract audit | `NOT_PREREGISTERED` |
| RDK-X5 CPU preflight for this candidate | `NOT_RUN` |
| Gate 5 | `NOT_RUN` |

T237 contract SHA-256:
`b26a4e5471992f5a2252a9c37cafdf802d5df7d5f8a3c9c1946a3f7cec9fe56b`

T237 terminal result SHA-256:
`119e2d3fbfd63c096f4db44509bc9329b1ba1f441c122e81ce514c810956943b`

Green conditions:

1. floor friction `0.5`;
2. floor friction `1.0`;
3. joint friction loss `0.9x`;
4. joint friction loss `1.1x`;
5. armature scale `1.0x`;
6. armature scale `1.05x`;
7. torso center of mass X offset `-0.05 m`;
8. torso center of mass X offset `+0.05 m`;
9. torso center of mass Y offset `-0.05 m`;
10. torso center of mass Y offset `+0.05 m`;
11. torso center of mass Z offset `-0.05 m`;
12. torso center of mass Z offset `+0.05 m`;
13. all-link mass scale `0.9x`;
14. all-link mass scale `1.1x`;
15. torso mass addition `-0.1 kg`; and
16. torso mass addition `+0.1 kg`.

Each condition contains both checkpoints, both measured actuator fits, and all
four commands. All 256 cells in conditions 1-16 passed duration, gait,
tracking, rate, saturation, and protection rules.

Condition 17 applied a uniform `-0.03 rad` modeled home-joint offset. In all
four checkpoint/actuator-fit blocks, `x=0` held for the full 12 seconds while
the three moving commands fell. The failures had zero action saturation and
zero rate-limit excess. This localizes the blocker to home/calibration
alignment rather than an overly aggressive command or one actuator fit.

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

T237 stopped at its first failed condition as preregistered. T238 is not
preregistered, the RDK-X5 CPU preflight is not run, and Gate 5 remains closed.
A successor policy mechanism must first earn and pass a new offline contract.
