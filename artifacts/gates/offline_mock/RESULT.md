# Offline Mock Result

Status: `INFORMATIONAL_ONLY`

- Ticks: 250
- Transactions: 4,000 expected, 0 failed
- Read bursts: 0
- Bus max: 2.6057 ms
- Tick p99: 21.043932 ms
- Tick p99.9: 21.810927 ms
- Tracking p95: 0.0034451701886752516 rad
- Host: Windows, Python 3.10.11, stock scheduler

The torque-off single-servo mock probe also completed 1,000 reads with zero
failures or bursts and a read round-trip p99 of 0.050504 ms. Its machine-readable
result is `artifacts/runs/mock/single_servo_summary.json`.

Both summaries bind their raw JSONL hash and final torque-off status. This run
validates the probe, telemetry schemas, high-resolution shared clock, failure
accounting, and fail-closed comparison pipeline. It misses the hardware tick gates
on an unisolated non-RT host. It is not an X5 gate result and cannot justify the
Python-to-Rust escalation.

Machine-readable result: `artifacts/runs/mock/summary.json`.
