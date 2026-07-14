# Offline Mock Result

Status: `INFORMATIONAL_ONLY`

- Ticks: 1,000
- Transactions: 16,000 expected, 0 failed
- Read bursts: 0
- Bus max: 2.5472 ms
- Tick p99: 22.000512 ms
- Tick p99.9: 22.0126294 ms
- Host: Windows, Python 3.10.11, stock scheduler

This run validates the probe, telemetry schema, high-resolution shared clock,
failure accounting, and comparison pipeline. It misses the hardware tick gates
on an unisolated non-RT host. It is not an X5 gate result and cannot justify the
Python-to-Rust escalation.

Machine-readable result: `artifacts/runs/mock/summary.json`.
