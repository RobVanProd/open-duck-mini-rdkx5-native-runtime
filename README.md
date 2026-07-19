# Open Duck Mini RDK-X5 Native Runtime

Ground-up, measurement-first runtime for Open Duck Mini on the D-Robotics RDK-X5. This is deliberately separate from [`RobVanProd/open-duck-mini-rdkx5`](https://github.com/RobVanProd/open-duck-mini-rdkx5), which preserves the inherited Pi-derived runtime and the earlier sim-to-real campaign.

The governing success metric is bounded 50 Hz loop timing, not an empty error counter. The known legacy baseline is 1.07% read errors at `x=0.0`, 2.68% at `x=0.08`, and a 26 ms maximum tick with read bursts. A prior retry patch reached zero reported errors while motion remained behaviorally funky; retries can hide faults while worsening timing.

## Status

| Area | Status |
| --- | --- |
| Pi inheritance audit | Complete from preserved source plus hashed read-only X5 inventory |
| Frozen 101/14 contract | Deployed golden vector passes 101 observations and 14 targets exactly; candidate training semantics still required |
| Direct STS3215 bus | ID-routed Python implementation; wire SyncRead order ends 14,13; exact 140-byte state burst is collected before one-pass parsing; 10,000-tick governor A/B passes the `<5 ms` sweep budget |
| Extended servo telemetry | Current/voltage/temperature, one servo per tick |
| Timing probe | v2 per-class evidence with an explicit complete-tick-sweep population, raw hash, RT/auth/cutoff provenance, and gated movement |
| Runtime evidence | Hashed provenance, cutoff-bearing terminal record, strict schemas, and offline summarizer |
| RT scheduling / affinity | CPU 7 isolation and `SCHED_FIFO 80` verified; `performance` governor causally clears the Python host tail and tick gates remain green |
| IMU / contacts / policy host | BNO055 calibration/mapping and active-low contacts pass the reviewed nine-label matrix; all 2,250 rows were fresh with zero worker errors |
| Hardware gates 1-5 | Gates 1-3 `PASS_REVIEWED`; Gate 3 used no servo, torque, target, or policy path; Gates 4-5 `NOT_RUN` and separately unauthorized |
| Grounded replay | Out of scope |

## Non-negotiable contract

- ONNX input `obs`: float32 `[1, 101]`; output `continuous_actions`: float32 `[1, 14]`.
- 50 Hz, 20 ms nominal tick.
- Servo IDs: left leg 20-24, right leg 10-14, neck/head 30-33.
- `target_rad = home_rad + action * 0.25`, followed by the inherited 5.24 rad/s target slew limit and head-command overlay.
- `duck_config.json` keeps the existing soft-offset, `imu_upside_down`, `start_paused`, and `phase_frequency_factor_offset` meanings.
- A stale required servo or sensor sample invalidates the tick; it is never silently substituted into the policy observation.
- A checksum-valid servo reply with a device alarm retains its fresh payload and raw status; runtime startup still blocks before torque until the alarm is resolved or explicitly reviewed.

The exact field map and the inherited one-tick phase-ordering discrepancy are documented in [the contract](docs/OBSERVATION_ACTION_CONTRACT.md).

The deployable policy interface remains exactly 101/14. A simulation or stateful ONNX
using 115 inputs is not assumed equivalent: it must export the frozen single-input
interface and prove that `obs[83:97]`, phase ordering, and slew semantics match.

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
Moving probes additionally require `--moving-gate-authorized`. The serial policy
runtime is reserved for Gate 5 and additionally requires `--gate5-authorized`,
an exact fixed command, bounded total/active tick counts, a physical controller,
and `start_paused=true`.

Read these before any X5 work:

- [Hardware gate runbook](docs/HARDWARE_GATE_RUNBOOK.md)
- [Real-time setup](docs/REALTIME_SETUP.md)
- [Serial latency verification](docs/SERIAL_LATENCY.md)
- [Phase 0 inheritance audit](docs/PHASE_0_PI_INHERITANCE_AUDIT.md)
- [Requirements traceability](docs/REQUIREMENTS_TRACEABILITY.md)
- [Offline verification](docs/TESTING.md)
- [Control-run evidence](docs/CONTROL_RUN_EVIDENCE.md)
- [Duck evidence collector](docs/DUCK_EVIDENCE_COLLECTION.md)

Gate 3 and the serial Gate 5 runtime require a strict BNO055 calibration JSON.
`calibrate_imu` can capture this robot's offsets without opening the servo bus,
enabling torque, writing a target, or loading a policy. It requires Rob to be
physically present plus all three explicit acknowledgements, sustains full
3/3/3/3 calibration, reapplies the captured profile to a fresh BNO055 session,
and accepts it only after exact offset and frozen-mapping readback. Missing,
malformed, or non-matching calibration data blocks later hardware startup.
This robot's reviewed candidate profile is now recorded under
`artifacts/gates/phase_7_hardware/gate_3_sensors/calibration_20260718/`; its
completion did not auto-pass the nine-label Gate 3 matrix. Its first authorized
attempt halted on a startup-publication race with no servo access or torque;
that failed artifact remains preserved under
`artifacts/gates/phase_7_hardware/gate_3_sensors/startup_stale_halt_20260718/`.
The corrected 2026-07-19 matrix then passed all data-integrity and physical-label
reviews; its reduced packet is under
`artifacts/gates/phase_7_hardware/gate_3_sensors/matrix_20260719/`.

## Board evidence collector

When the X5 is available, the safe default collector captures the installed runtime,
board/serial/RT inventory, config, policy interface hashes, and legacy telemetry into a
local hashed archive. It performs no servo-bus access, inference, movement, or upload:

```bash
python3 tools/collect_duck_evidence.py \
  --legacy-root /home/sunrise/project \
  --notes "pre-gate board inventory"
```

An optional torque-off single-servo read probe exists, but remains behind the same two
hardware acknowledgements and requires separate Gate 1 authorization.

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
bursts, with bus-time max 2.527 ms. Tick p99 was 21.999 ms and p99.9 was
22.012 ms, so the mock host does not pass the hardware timing gates. Mock
tracking p95 was 0.00345 rad. That is an
informational result, not a failure of an X5 gate and not evidence about
`SCHED_FIFO` or CPU isolation.

Reviewed summaries are in `artifacts/runs/mock/summary.json` and
`artifacts/runs/mock/single_servo_summary.json`, with the legacy comparison at
`artifacts/comparisons/baseline_vs_new.mock.json`. Raw JSONL is intentionally
ignored. `artifacts/manifest.sha256` authenticates every checked-in artifact.
