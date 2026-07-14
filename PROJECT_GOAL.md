# Project Goal

Build a ground-up RDK-X5 runtime for Open Duck Mini that preserves the policy and robot contracts exactly while making deterministic, measured tick timing the primary acceptance criterion.

## Why this repository exists

The deployed `Open_Duck_Mini_Runtime-2_RDK_X5` is a Pi Zero 2W runtime adapted as a platform diff. Its hot path combines a Python loop, `rustypot==0.1.0`, blocking serial calls, and retry sleeps under stock Linux scheduling. Measured read failures were 1.07% at `x=0.0` and 2.68% at `x=0.08`; tick maximum reached 26 ms with read bursts. A retry patch produced zero reported errors without fixing funky motion. The falsified hypothesis is “success equals no exceptions.” The active hypothesis is “behavior requires bounded transaction and tick timing.”

## Frozen interface

- 101 observations and 14 actions at 50 Hz through ONNX Runtime.
- Field order, units, scales, history, phase, home pose, head overlay, and action slew semantics are frozen in `docs/OBSERVATION_ACTION_CONTRACT.md`.
- `duck_config.json` remains compatible.
- Joint order and servo IDs remain unchanged.
- Torque-off and pause behavior are mandatory.

## Phases and exit criteria

0. Audit the inherited runtime end-to-end and record every Pi-era assumption.
1. Build the timing probe first; obtain an authorized legacy hardware baseline before claiming improvement.
2. Use one SyncWrite for 14 goals, one grouped read for 14 positions/velocities, explicit timeout/CRC/partial taxonomy, and round-robin current/voltage/temperature. Total bus time budget: under 5 ms.
3. Use SCHED_FIFO, an isolated pinned CPU, absolute deadlines, preallocated hot-loop state, disabled GC, and off-thread logging. Escalate only the servo transaction to Rust if authorized measurements miss p99/p99.9 gates after RT setup is verified.
4. Timestamp BNO055 and foot-contact samples on the same monotonic clock. Respect `imu_upside_down`; raw GPIO false means contact true.
5. Warm ONNX before the loop, reproduce the observation contract, apply soft offsets, and log target-velocity envelope excursions above 3.75 rad/s without blocking them.
6. Use watchdog torque-off for hard overruns over 40 ms or consecutive bus failures; preserve Xbox/F710 pause parity; verify all servos and move home slowly before waiting paused.
7. Run five separately authorized, suspended/benched hardware gates. Grounded replay is excluded.

## Final hardware acceptance

At `x=0.08`: tick p99 <= 21 ms, tick p99.9 <= 22 ms, zero read-failure bursts, and transaction failures < 0.1%. Sine-sweep tracking p95 must be <= 0.011 rad while timing gates remain green.

## Deliverables

- X5-native runtime package and direct STS3215 bus.
- Timing probe and baseline-vs-new comparison artifact.
- Phase 0 audit.
- RT, CPU-isolation, and serial-latency setup/verification scripts.
- `configure_motor.py`, `check_motors.py`, `find_soft_offsets.py`, and `set_servo_mid.py` equivalents.
- Per-phase gate artifacts and SHA-256 manifest.
