# CPU-Governor Torque-Off A/B Result

Status: `EXECUTED_REVIEWED_PASS_CAUSAL_AND_BUS_BUDGET`

The explicitly authorized arm B completed all 10,000 torque-off sweeps on
`/dev/ttyS1` while the robot remained on its stand. The fail-closed runner used
the frozen `8c73aae` source and changed only policy0 from `schedutil` to
`performance` for the probe. It restored `schedutil` after completion.

This is a passing torque-off timing preflight, not Gate 2 home-hold clearance.
No torque was enabled, no policy or config was loaded, no target amplitude was
requested, and no motion occurred. The moving Gate 2 run still requires a new
explicit authorization.

## Safety and completeness

- run status: `COMPLETE`; probe exit status `0`; 10,000/10,000 timing rows;
- torque enabled: false; amplitude: 0; moving authorization: false;
- final torque-off: `ok`; no process retained `/dev/ttyS1`;
- isolated CPU 7 under `SCHED_FIFO 80`; background threads on CPUs 0-6;
- governor before/during/after: `schedutil` / `performance` / `schedutil`;
- transaction failures: 0/160,000; read bursts: 0; alarms: 0;
- telemetry records dropped: 0; probe stderr empty;
- every file in the preserved board run passed its SHA-256 check.

## Frozen A/B decision

| Quantity | Arm A `schedutil` | Arm B `performance` | Change | Decision |
| --- | ---: | ---: | ---: | --- |
| Complete-sweep mean | 5.655528 ms | 4.115062 ms | -1.540466 ms | material pass |
| Complete-sweep p99.9 | 8.067290 ms | 4.522262 ms | -3.545028 ms | material pass |
| Complete-sweep max | 8.352496 ms | 4.821428 ms | -3.531068 ms | `<5 ms` pass |
| Tick p99 | 20.096915 ms | 20.002755 ms | -0.094160 ms | `<=21 ms` pass |
| Tick p99.9 | 20.134589 ms | 20.005297 ms | -0.129292 ms | `<=22 ms` pass |
| Group failures | 1/140,000 | 0/140,000 | -1 | pass |

The preregistration required both mean and p99.9 to improve by at least
0.5 ms, the maximum not to worsen, and every unchanged absolute gate to pass.
Arm B satisfies all of those conditions. Its complete-sweep maximum is below
5 ms over the full preregistered 10,000-tick population.

## Mechanism conclusion

Both arms received all 140 grouped-response bytes before one generic parse on
every tick. Under `performance`, mean group parse tail fell from 1.361458 ms to
0.559224 ms, mean state-decode gap fell from 0.576630 ms to 0.230265 ms, and
mean unattributed exchange gap fell from 0.652860 ms to 0.266352 ms. The mean
application read-call count increased from 9.6714 to 11.9766 while total host
tail decreased, consistent with the isolated core waking and executing Python
at a higher frequency rather than waiting for more wire data.

This matched one-variable A/B identifies CPU-frequency scaling as the cause of
the failed host-side tail in this probe. It rejects servo-count capacity, UART
baud rate, and USB framing as explanations for the remaining sub-5 ms failure.
It also removes any timing basis for escalating the servo transaction to Rust:
the Python loop passes the preregistered tick gates with substantial margin.

## Provenance

- runner commit: `8da00da`;
- runtime source commit:
  `8c73aae2110f10a294e1dcf333c41bfc9d2f3a88`;
- runtime source archive SHA-256:
  `a90070d00e8f0eca704005aa241c36e7ab4aa782ca7f8af41253d3d4be41de77`;
- timing JSONL SHA-256:
  `43178e5ff7621843a810d9f2a2f9000f3a29a35665b4c51c69226c37acdeff39`;
- summary SHA-256:
  `1444cd3f39afe0f980f282ada1b55df4ac7bec8c3deabd03d1230cf1ec2d0e79`;
- transaction trace SHA-256:
  `ef28fb54b8651d5a8a18580bba15f827f43ec5801c65d904b0d14d784be34fb9`;
- matched comparison SHA-256:
  `6fd8e0241016d4aee7bea64b430db1e6f5a9e74abb479a9cc5b65a3b3314071a`.

The compact summary, metadata, governor records, comparison, and board hash
list are checked in here. Raw 10,000-row logs remain on the board under
`/home/sunrise/duck-evidence/cpu-governor-ab-8c73aae-performance-20260718`.
