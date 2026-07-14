# Real-Time Loop Setup on RDK-X5

The X5 is still a Linux application processor; SCHED_FIFO and isolation reduce observed jitter but do not turn it into a hard real-time MCU.

All loop, bus, controller, and sensor timestamps use one imported
`time.perf_counter_ns` callable. It is a monotonic, high-resolution performance
counter, avoiding coarse host clocks while keeping every age and duration in the
same clock domain.

## Intended configuration

- Reserve CPU 5 on the six-core X5 with kernel arguments: `isolcpus=5 nohz_full=5 rcu_nocbs=5`.
- Keep device IRQs and general services on CPUs 0-4.
- Pin the control process to CPU 5.
- Request SCHED_FIFO priority 80.
- Run logging, controller input, and noncritical sensor work off the isolated core.

Boot configuration on RDK images varies. `setup/print_core_isolation_plan.sh 5` prints the arguments and checks the current kernel state; it intentionally does not edit bootloader files offline. Record the board's actual bootloader path before applying the arguments.

`setup/install_rt_permissions.sh` installs a narrow limits file for group `open-duck-rt`. A systemd service is preferred in production because it can set `CPUAffinity=5`, `LimitRTPRIO=90`, and `CAP_SYS_NICE` without granting broad capabilities to every Python process.

The runtime refuses `--require-realtime` unless all of these are true:

- requested CPU exists and process affinity contains only it;
- `/sys/devices/system/cpu/isolated` reports it isolated;
- scheduler is `SCHED_FIFO` at or above the requested priority;
- the monotonic clock is available.

Do not loosen a timing gate because setup is incomplete. An incomplete RT setup makes the measurement invalid for the native-escalation decision.
