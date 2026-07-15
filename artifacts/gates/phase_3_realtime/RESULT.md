# Real-Time Setup Verification Result

Status: `SETUP_PASS_TIMING_GATE_NOT_RUN`

Authorized configuration and reboot completed on the RDK-X5 on 2026-07-15.

## Boot and recovery evidence

- original `/boot/boot.cmd` SHA-256:
  `50b2793c0a6df10549ba253dc034752d75438c32723558551b48c71f432be3cf`
- original `/boot/boot.scr` SHA-256:
  `139534237a754fa9092ea48306cf1f8e099f7c7b980e927c26d38e903f84b915`
- configured `/boot/boot.cmd` SHA-256:
  `6559c2d2501b88dd12fa74ef1f25d016a8ba2452a3ecafadfdbaedbc9bdbb100`
- configured `/boot/boot.scr` SHA-256:
  `b5bd66d453843cc68ebb11e550e385a861948da4d2c702317c401a809d6e23fb`
- recovery copies:
  `/boot/boot.cmd.pre-open-duck-rt` and
  `/boot/boot.scr.pre-open-duck-rt`

The first reboot proved `isolcpus=7`. It also proved this stock 6.1.83 kernel
does not support `CONFIG_NO_HZ_FULL` and treats `rcu_nocbs` as unknown. Those two
inert arguments were removed before the final reboot. The final live command line
contains only the supported isolation setting:

```text
... hobotboot.reason=REBOOT_CMD isolcpus=7
```

## Live scheduler verification

- `/sys/devices/system/cpu/isolated`: `7`
- login `RLIMIT_RTPRIO`: `90/90`
- login memlock: `unlimited`
- service-equivalent launch affinity: CPUs `0-7`
- housekeeping affinity: CPUs `0-6`
- control affinity: CPU `7`
- control policy/priority: `SCHED_FIFO 80`
- verifier result: `PASS`

The SSH login naturally inherits housekeeping-only affinity after `isolcpus`.
Verification therefore used `taskset -c 0-7`, matching the reviewed systemd
unit's initial `CPUAffinity`, before partitioning workers and the control thread.

This closes RT configuration and privilege setup. It does not close Phase 3's
control-loop timing requirement or trigger the Python-to-Rust decision; those
remain gated on an authorized all-14 RT timing run.
