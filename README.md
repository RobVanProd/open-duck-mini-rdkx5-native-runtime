# Open Duck Mini RDK-X5 Native Runtime

Ground-up, measurement-first runtime for Open Duck Mini on the D-Robotics RDK-X5. This is deliberately separate from [`RobVanProd/open-duck-mini-rdkx5`](https://github.com/RobVanProd/open-duck-mini-rdkx5), which preserves the inherited Pi-derived runtime and the earlier sim-to-real campaign.

The governing success metric is bounded 50 Hz loop timing, not an empty error counter. The known legacy baseline is 1.07% read errors at `x=0.0`, 2.68% at `x=0.08`, and a 26 ms maximum tick with read bursts. A prior retry patch reached zero reported errors while motion remained behaviorally funky; retries can hide faults while worsening timing.

## Status

| Area | Status |
| --- | --- |
| Pi inheritance audit | Complete from the preserved reference snapshot |
| Frozen 101/14 contract | Implemented and unit-tested; hardware golden-vector capture still required |
| Direct STS3215 bus | Python implementation plus deterministic/fault-injecting mock |
| Timing probe | v2 per-class timing/tracking evidence; explicitly gated serial movement |
| RT scheduling / affinity | Implemented; X5 verification is `NOT_RUN` |
| IMU / contacts / policy host | Implemented behind hardware authorization |
| Hardware gates 1-5 | `NOT_RUN` — each requires separate explicit authorization |
| Grounded replay | Out of scope |

## Non-negotiable contract

- ONNX input `obs`: float32 `[1, 101]`; output `continuous_actions`: float32 `[1, 14]`.
- 50 Hz, 20 ms nominal tick.
- Servo IDs: left leg 20-24, right leg 10-14, neck/head 30-33.
- `target_rad = home_rad + action * 0.25`, followed by the inherited 5.24 rad/s target slew limit and head-command overlay.
- `duck_config.json` keeps the existing soft-offset, `imu_upside_down`, `start_paused`, and `phase_frequency_factor_offset` meanings.
- A stale required servo or sensor sample invalidates the tick; it is never silently substituted into the policy observation.

The exact field map and the inherited one-tick phase-ordering discrepancy are documented in [the contract](docs/OBSERVATION_ACTION_CONTRACT.md).

## Quick start: offline only

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
runtime_timing_probe --bus mock --ticks 250 \
  --output artifacts/runs/mock/timing.jsonl \
  --summary artifacts/runs/mock/summary.json
```

On Windows, activate with `.venv\Scripts\Activate.ps1`. The mock bus is the default and never touches hardware.

## Hardware guard

Every hardware CLI requires both of these exact flags:

```text
--hardware-authorized --suspended-or-benched
```

Those flags are an operator assertion that Rob approved the specific gate and the robot is physically supported. They are not blanket authorization for later gates. There is intentionally no grounded-run option.

Read these before any X5 work:

- [Hardware gate runbook](docs/HARDWARE_GATE_RUNBOOK.md)
- [Real-time setup](docs/REALTIME_SETUP.md)
- [Serial latency verification](docs/SERIAL_LATENCY.md)
- [Phase 0 inheritance audit](docs/PHASE_0_PI_INHERITANCE_AUDIT.md)
- [Requirements traceability](docs/REQUIREMENTS_TRACEABILITY.md)
- [Offline verification](docs/TESTING.md)

## Layout

```text
src/open_duck_x5/       Runtime, bus, timing, sensor, policy, and safety code
tools/                  Script-parity and artifact tools
setup/                  RT, CPU-isolation, and serial setup/check scripts
docs/                   Frozen contract, audit, decisions, and runbooks
artifacts/gates/        Pre-registered gate definitions and NOT_RUN records
artifacts/runs/         Raw local runs (ignored except placeholders)
tests/                  Offline protocol, contract, timing, and safety tests
```

## Gates

The new stack must ultimately show, on an explicitly authorized suspended `x=0.08` replay:

- tick p99 <= 21 ms;
- tick p99.9 <= 22 ms;
- zero read-failure bursts;
- transaction failure rate < 0.1%;
- total servo bus time < 5 ms per tick;
- sine-sweep tracking p95 error <= 0.011 rad.

Mock results validate code paths, schemas, failure accounting, and artifact production. They do not satisfy a hardware gate.

## Offline evidence

The checked-in 1,000-tick mock run used stock Windows scheduling and the shared
high-resolution monotonic clock. It produced zero transaction failures and zero
bursts, with bus-time max 2.510 ms. Tick p99 was 22.001 ms and p99.9 was
22.488 ms, so the mock host does not pass the hardware timing gates. Mock
tracking p95 was 0.00345 rad. That is an
informational result, not a failure of an X5 gate and not evidence about
`SCHED_FIFO` or CPU isolation.

Reviewed summaries are in `artifacts/runs/mock/summary.json` and
`artifacts/runs/mock/single_servo_summary.json`, with the legacy comparison at
`artifacts/comparisons/baseline_vs_new.mock.json`. Raw JSONL is intentionally
ignored. `artifacts/manifest.sha256` authenticates every checked-in artifact.
