# Offline Mock Result

Status: `INFORMATIONAL_ONLY`

- Ticks: 1,000
- Transactions: 16,000 expected, 0 failed
- Read bursts: 0
- Bus max: 2.5408 ms
- Tick p99: 21.995416 ms
- Tick p99.9: 22.0109372 ms
- Tracking p95: 0.003451687978265439 rad
- Host: Windows, Python 3.10.11, stock scheduler

The torque-off single-servo mock probe also completed 1,000 reads with zero
failures or bursts and a read round-trip p99 of 0.0245 ms. Its machine-readable
result is `artifacts/runs/mock/single_servo_summary.json`.

This run validates the probe, telemetry schema, high-resolution shared clock,
failure accounting, and comparison pipeline. It misses the hardware tick gates
on an unisolated non-RT host. It is not an X5 gate result and cannot justify the
Python-to-Rust escalation.

Machine-readable result: `artifacts/runs/mock/summary.json`.
