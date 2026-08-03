# Agent Instructions

This repository controls a real biped robot. Safety, contract fidelity, and measured evidence outrank speed.

## Frozen contract

- Keep the policy interface at 101 observations, 14 actions, ONNX Runtime, and a 50 Hz / 20 ms tick.
- Do not reorder, rescale, add, or remove observation fields.
- Do not change action scale, rate limiting, home pose, joint order, servo IDs, offset semantics, IMU mapping, contact polarity, or phase timing without an explicit reviewed decision backed by evidence.
- Treat `docs/OBSERVATION_ACTION_CONTRACT.md` and its tests as the contract.
- Preserve `duck_config.json` meanings for `joints_offsets`, `imu_upside_down`, `start_paused`, and `phase_frequency_factor_offset`.

## Authority boundary

- Development is offline by default. Use the mock bus.
- Do not access the robot, deploy a policy, energize torque, or run a moving test without Rob explicitly authorizing that exact hardware gate.
- Every suspended hardware command must require both `--hardware-authorized` and `--suspended-or-benched`.
- The frozen G3 x=0 path may be implemented offline and default-disabled. Its honest grounded mode must require `--hardware-authorized`, `--grounded-test-area-confirmed`, and `--grounded-x0-authorized`, and must reject `--suspended-or-benched`.
- No grounded invocation is authorized by this repository instruction. It still requires Rob to authorize that exact grounded gate while physically present.
- Grounded x=.08 replay and grounded walking remain outside this repository's authority.
- Do not advance past a failed timing gate.

## Safety

- Torque off on normal exit, signals, exceptions, watchdog trips, and failed startup.
- Honor `start_paused`; do not add a force-unpaused bypass.
- Stop on unexpected motion, wrong joint/side/sign, bus-failure bursts, hard tick overrun, stale required sensor data, or lost controller state.
- Keep the policy authoritative only after the frozen inputs are fresh and valid. Never silently reuse stale servo state.

## Evidence discipline

- Timing determinism is the primary success metric. Zero reported errors is not success by itself.
- Write per-tick data to a bounded ring buffer; serialize off the control thread.
- Label mock, bench, suspended, and not-run artifacts unambiguously.
- Never invent hardware results. Unrun gates remain `NOT_RUN`.
- Hash reviewed gate artifacts with `python tools/hash_artifacts.py`.
- Do not commit secrets, board access material, raw large logs, videos, or policy binaries.

## Native escalation rule

Keep the policy and initial servo loop in Python. Move only the servo transaction into a small Rust extension if an authorized hardware probe shows the Python loop, with SCHED_FIFO and CPU isolation verified, misses either `tick p99 <= 21 ms` or `tick p99.9 <= 22 ms`. Do not escalate from preference.

## Validation

Before finalizing changes, run:

```bash
python -m pytest
python -m open_duck_x5.probe --bus mock --ticks 250 --output artifacts/runs/mock/timing.jsonl --summary artifacts/runs/mock/summary.json
python tools/hash_artifacts.py
python tools/hash_artifacts.py --check
```
