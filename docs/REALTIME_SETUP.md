# Real-Time Loop Setup on RDK-X5

The X5 is still a Linux application processor; SCHED_FIFO and isolation reduce observed jitter but do not turn it into a hard real-time MCU.

All loop, bus, controller, and sensor timestamps use one imported
`time.perf_counter_ns` callable. It is a monotonic, high-resolution performance
counter, avoiding coarse host clocks while keeping every age and duration in the
same clock domain.

## Intended configuration

- Reserve CPU 5 on the six-core X5 with kernel arguments: `isolcpus=5 nohz_full=5 rcu_nocbs=5`.
- Keep device IRQs and general services on CPUs 0-4.
- Start the process with CPUs 0-5 available. Before creating ONNX, sensor,
  controller, or logging threads, the runtime moves the initialization thread to
  CPUs 0-4 so every background/native worker inherits the housekeeping mask.
- Immediately before the control loop, move only the control thread to CPU 5 and
  request `SCHED_FIFO` priority 80.
- Request SCHED_FIFO priority 80.
- Run logging, controller input, and noncritical sensor work off the isolated core.

Boot configuration on RDK images varies. `setup/print_core_isolation_plan.sh 5` prints the arguments and checks the current kernel state; it intentionally does not edit bootloader files offline. Record the board's actual bootloader path before applying the arguments.

`setup/install_rt_permissions.sh` installs a narrow limits file for group
`open-duck-rt`. A systemd service is preferred in production because it can set
`CPUAffinity=0 1 2 3 4 5`, `LimitRTPRIO=90`, and `CAP_SYS_NICE` without granting
broad capabilities to every Python process. **Do not set `CPUAffinity=5`:** that
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
