# T251A2 X5 optimized paced-screen preregistration

Status: `PREREGISTERED_T251A2_X5_OPTIMIZED_PACED_SCREEN`

T251A showed two independent causes. The unpaced `SCHED_FIFO` runner exhausted
Linux's 950-ms-per-second RT budget, creating artificial 43–55 ms throttling
events at the one-second boundary. The exact T247 graph itself remained below
the frozen p99 gate, while Python host work raised the complete stage above it.

The default-off Winner-v14 implementation changes only scheduling and valid-path
implementation details. It retains identical graph bytes, observations,
actions, targets, recurrence, phase, P30 state, offsets, and confirmed-send
transactions. Local fake-session, mixed-delay P30, target-pipeline, and 2,250
real-asset tick comparisons are byte-exact.

T251A2 is a 2,048-locomotion-tick engineering screen, not a T251 rerun. It
paces releases at 20 ms, runs baseline and optimized hosts in alternating order,
and requires byte equality every tick. Its `1.8/2.5/4.0 ms` timing screen leaves
fixed reserve below the unchanged T251 `2/3/5 ms` limits. A pass earns only one
corrected 10,000-tick preregistration; it cannot clear production integration or
Hardware Gate 5.

Machine-readable contract:
`artifacts/gates/phase_5_policy/t251a2_x5_optimized_paced_screen_preregistration_20260731.json`
