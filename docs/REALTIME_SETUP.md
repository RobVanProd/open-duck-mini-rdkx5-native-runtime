# Real-Time Loop Setup on RDK-X5

The X5 is still a Linux application processor; SCHED_FIFO and isolation reduce observed jitter but do not turn it into a hard real-time MCU.

All loop, bus, controller, and sensor timestamps use one imported
`time.perf_counter_ns` callable. It is a monotonic, high-resolution performance
counter, avoiding coarse host clocks while keeping every age and duration in the
same clock domain.

## Verified board topology and intended configuration

The 2026-07-15 read-only board inventory reports eight Cortex-A55 CPUs (`0-7`), not
six. The current kernel command line has no `isolcpus`, `nohz_full`, or `rcu_nocbs`
arguments; `/sys/devices/system/cpu/isolated` is empty; the process has SCHED_OTHER
priority 0 on all eight CPUs; and `RLIMIT_RTPRIO` is zero. Timing evidence collected
in that state cannot decide the native-escalation rule.

- Reserve CPU 7 with kernel arguments: `isolcpus=7 nohz_full=7 rcu_nocbs=7`.
- Keep device IRQs and general services on CPUs 0-6. The captured USB controller IRQ
  is currently handled on CPU 0.
- Start the process with CPUs 0-7 available. Before creating ONNX, sensor,
  controller, or logging threads, the runtime moves the initialization thread to
  CPUs 0-6 so every background/native worker inherits the housekeeping mask.
- Immediately before the control loop, move only the control thread to CPU 7 and
  request `SCHED_FIFO` priority 80.
- Request SCHED_FIFO priority 80.
- Run logging, controller input, and noncritical sensor work off the isolated core.

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
