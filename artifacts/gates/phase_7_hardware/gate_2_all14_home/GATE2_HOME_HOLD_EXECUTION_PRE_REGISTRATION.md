# Gate 2 Performance-Governed Home-Hold Pre-Registration

Status: `EXECUTED_REVIEWED_PASS`

This freezes the next Gate 2 execution protocol after the reviewed CPU-governor
A/B cleared the torque-off timing blocker. It does not authorize opening
`/dev/ttyS1`, enabling torque, moving home, or holding position. The 2026-07-15
authorization referred to an older USB source and stopped at its failed
preflight; it is not reused for this materially different source and launcher.

## Frozen implementation and inputs

- execution source commit:
  `a5b53442012899f89c899f5c2f8f1a110c4448f2`;
- execution source archive SHA-256:
  `730d53480de5cf3c64381c75984289994d4edb798e2b09aec31b1f8df7ff67f5`;
- board config: `/home/sunrise/duck_config.json`;
- config SHA-256:
  `131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b`;
- launcher: `setup/run_gate2_home_hold.sh`;
- launcher SHA-256:
  `868d6ebfa29672e8a4a482819b0bc5d19e13b91468e79b964cf0636d3b732f2a`;
- validator: `src/open_duck_x5/gate2_validation.py`;
- validator SHA-256:
  `bd3d3cd95fd5ef957bb499c9fd9266a5d9101397c95adf02c2358bb9f8355145`;
- serial endpoint: `/dev/ttyS1`, 1,000,000 bit/s, 8-N-1;
- SyncRead wire order: `20,21,22,23,24,30,31,32,33,10,11,12,14,13`;
- isolated CPU 7, `SCHED_FIFO 80`, initial affinity 0-7, housekeeping 0-6;
- policy0 precondition: `schedutil`, 300 MHz to 1.5 GHz, CPUs 0-7;
- policy0 during both stages: `performance`, restored to the exact prior value;
- transaction timeout: 4 ms; consecutive-failure watchdog: 2;
- no ONNX policy, controller, grounded operation, or nonzero target amplitude.

The runner exposes only the source archive, exact config path, fresh output
directory, and three hardware acknowledgements. Device, baud, timeout, tick
population, home duration, amplitude, RT settings, source/config hashes, and
governor policy cannot be overridden.

## Frozen two-stage sequence

Stage A is a source-matched torque-off preflight. It loads the frozen config,
keeps torque disabled, and executes exactly 10,000 50 Hz sweeps comprising one
all-14 SyncWrite, one all-14 position/speed SyncRead, and one round-robin
extended read per tick. It records zero-amplitude home targets but cannot move
the robot while torque is off.

The tested validator must accept Stage A before Stage B is invoked. It checks
the direct numeric statistics as well as the summary gate booleans: complete
10,000-row population, tick p99 `<=21 ms`, tick p99.9 `<=22 ms`, complete-sweep
sample maximum `<5 ms`, failures `<0.1%`, zero bursts, partial/unexpected
responses, alarms, and drops, exact config/home/RT provenance, and final
torque-off `ok`. Any mismatch restores the governor and exits without torque
enable.

Stage B reopens the same source and endpoint, establishes torque-off, verifies
all 14 servos are fresh and alarm-free, sets low startup gains, then enables
torque. It interpolates from fresh measured positions to the configured home
over exactly five seconds at 50 Hz. Bus errors halt immediately, and the same
hard-overrun watchdog used by the hold now covers every home-entry tick. The
operating gains are then restored and home is held for exactly 10,000 ticks
with amplitude `0 rad` and no policy.

Signals, exceptions, writer failure, a hard `>40 ms` overrun, or two
consecutive failed hold exchanges invoke the torque-off cleanup path. The
runner signals an active probe before restoring the governor. Unexpected
motion, wrong joint/side/sign, or operator concern still requires immediate
external power cutoff.

## Frozen advancement decision

Stage B becomes only a review candidate when its independent validator passes
the same timing, transport, alarm, drop, provenance, and final-cutoff checks and
the summary contains 10,000 tracking samples. Tracking error is reported but
the `0.011 rad` advancement threshold remains Gate 4's sine-sweep requirement,
not a post-hoc Gate 2 condition.

A failure stops Gate 2. It does not authorize a retry, threshold change,
timeout change, reordered contract, Rust escalation, policy inference, Gate 3,
or any grounded operation. Passing the runner still requires human review of
the evidence and does not authorize the next gate.

## Authorization required

Execution requires a new explicit authorization naming the complete
performance-governed Gate 2 sequence: the torque-off 10,000-tick preflight,
followed only on pass by the five-second torque-enabled home entry and
10,000-tick home hold on the stand or suspended/benched. The invocation must
contain all three acknowledgements:

```text
--hardware-authorized --suspended-or-benched --moving-gate-authorized
```

Authorization was supplied on 2026-07-18 with the robot on its stand and hands
clear. The exact frozen sequence completed once. Stage A passed before Stage B
was invoked; Stage B then completed the five-second home entry and 10,000-tick
hold. Both tested validators returned `PASS`, final torque-off was `ok`, and the
runner restored `schedutil`.

The reviewed result is preserved in `RESULT.md`, with its machine-readable
reduction under `performance_governed_home_hold/`. This execution passes Gate 2 only;
it does not authorize Gate 3, a policy, or grounded operation.
