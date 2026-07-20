# Real-Time Loop Setup on RDK-X5

The X5 is still a Linux application processor; SCHED_FIFO and isolation reduce observed jitter but do not turn it into a hard real-time MCU.

All loop, bus, controller, and sensor timestamps use one imported
`time.perf_counter_ns` callable. It is a monotonic, high-resolution performance
counter, avoiding coarse host clocks while keeping every age and duration in the
same clock domain.

## Verified board topology and intended configuration

The 2026-07-15 read-only board inventory reports eight Cortex-A55 CPUs (`0-7`), not
six. The initial kernel command line had no isolation argument;
`/sys/devices/system/cpu/isolated` was empty; the process had SCHED_OTHER priority 0
on all eight CPUs; and `RLIMIT_RTPRIO` was zero. Timing evidence collected in that
state cannot decide the native-escalation rule. The stock 6.1.83 kernel explicitly
reports `CONFIG_NO_HZ_FULL` unsupported and treats `rcu_nocbs` as unknown, so this
image must not claim either feature.

- Reserve CPU 7 with the supported kernel argument `isolcpus=7`.
- Keep device IRQs and general services on CPUs 0-6. The captured USB controller IRQ
  is currently handled on CPU 0.
- Start the process with CPUs 0-7 available. Before creating ONNX, sensor,
  controller, or logging threads, the runtime moves the initialization thread to
  CPUs 0-6 so every background/native worker inherits the housekeeping mask.
- Immediately before the control loop, move only the control thread to CPU 7 and
  request `SCHED_FIFO` priority 80.
- Request SCHED_FIFO priority 80.
- Run logging, controller input, and noncritical sensor work off the isolated core.

## Verified CPU-frequency requirement

The preregistered 2026-07-18 torque-off A/B changed only policy0 from
`schedutil` to `performance` for the frozen 10,000-tick serial population.
Complete-sweep mean/p99.9/max improved from
`5.655528/8.067290/8.352496 ms` to
`4.115062/4.522262/4.821428 ms`; tick p99/p99.9 was
`20.002755/20.005297 ms`. The A/B passed its material-effect threshold and the
absolute `<5 ms` bus budget with zero failures or bursts.

Therefore subsequent timing gates must verify policy0 is `performance` before
opening the serial device. The gate launcher must record the before/during/after
values and restore the prior governor on normal exit, failure, or signal. Do
not make this a silent machine-wide assumption, and do not reuse the torque-off
A/B runner for a moving gate. See D036-D037 and
`artifacts/gates/phase_7_hardware/gate_2_all14_home/cpu_governor_ab/RESULT.md`.

The Gate 2 implementation is `setup/run_gate2_home_hold.sh`. It records and
restores the governor around both the source-matched torque-off preflight and
the conditionally reached home hold. It is intentionally not a general command
wrapper: endpoint, timing population, home duration, RT settings, source/config
hashes, and movement amplitude are frozen and have no command-line override.

The CPU ONNX session is explicitly sequential and single-threaded, with intra-
and inter-op spinning disabled. Inference therefore executes on the RT control
thread instead of making it wait for default SCHED_OTHER worker pools on the
housekeeping cores. Any native thread still created by ONNX Runtime or another
library is enumerated and must exclude the control CPU.

On this board, `/boot/boot.cmd` constructs `bootargs`, `/boot/boot.scr` is the compiled
U-Boot script, and the currently selected kernel is `/boot/Image`. `/boot/Image-rt`
exists but is not selected and must not be switched merely on preference. Any reviewed
boot-argument change must update `boot.cmd`, rebuild `boot.scr` with its documented
`mkimage` command, preserve a recovery copy, reboot, and then verify `/proc/cmdline` and
the kernel isolation sysfs files. `setup/print_core_isolation_plan.sh 7` prints the
arguments and current state; it intentionally does not edit bootloader files.

`setup/verify_rt_setup.sh 7 80` parses the kernel CPU-list syntax exactly and
launches a short-lived process that must successfully pin itself to CPU 7 and
enter `SCHED_FIFO` priority 80. A `PASS` therefore proves both isolation
membership and current-session scheduler privilege; substring matches such as
CPU 1 versus CPU 10 are never accepted.

`setup/install_rt_permissions.sh` installs a narrow limits file for group
`open-duck-rt`. A systemd service is preferred in production because it can set
`CPUAffinity=0 1 2 3 4 5 6 7`, `LimitRTPRIO=90`, and `CAP_SYS_NICE` without granting
broad capabilities to every Python process. **Do not set `CPUAffinity=7`:** that
would place sensor, ONNX, controller, and JSON writer threads on the isolated core
and the runtime now rejects it.

The runtime refuses `--require-realtime` unless all of these are true:

- the initial service affinity contains the requested CPU plus at least one
  housekeeping CPU;
- `/sys/devices/system/cpu/isolated` reports it isolated;
- the control thread alone is pinned to that CPU under `SCHED_FIFO` at or above
  the requested priority;
- every other live userspace thread in `/proc/self/task` excludes the control CPU;
- the monotonic clock is available.

Successful verification is written as a `realtime_verified` runtime event before
servo startup. The event includes initial affinity, housekeeping affinity, control
affinity/priority, and every verified background native thread.

Do not loosen a timing gate because setup is incomplete. An incomplete RT setup makes the measurement invalid for the native-escalation decision.
