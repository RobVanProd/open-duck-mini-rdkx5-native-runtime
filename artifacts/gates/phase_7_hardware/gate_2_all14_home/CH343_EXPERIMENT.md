# WCH CH343 Driver Experiment

Status: `COMPLETE_REJECTED_ROLLED_BACK`

Rob separately authorized a reversible build/install/bind test of the official
WCH CH343 Linux driver followed only by the same 50-tick all-14 torque-off Gate
2 preflight. No torque enable, home movement, policy inference, or later gate was
authorized or performed.

## Pinned source and build

- upstream: `https://github.com/WCHSoftGroup/ch343ser_linux`
- upstream commit: `9e6eb31f59068e10dd68160cbbf587013a9725d5`
- source archive SHA-256:
  `ca30cf6e180486af36f15aa78c10db1bf263840883ac46943480b184756d1e50`
- running kernel: `6.1.83 #3 SMP PREEMPT`, AArch64
- matching header package: `hobot-kernel-headers 3.0.2-20251208164403`
- explicit header directory: `/usr/src/linux-headers-6.1.83`
- header `UTS_RELEASE`: `6.1.83`
- header `Module.symvers` SHA-256:
  `82e6e5fd557071277615e9c28c9e46bdb07dd01c87e2f949abee7d890f9fa502`
- built module version: `V2.2 On 2026.04`
- built module vermagic: `6.1.83 SMP preempt mod_unload aarch64`
- built/installed module SHA-256:
  `ff417f9946ab35f0943fa598a06218989ef443f42ae4ef883efbf803573481a2`

The board's header package had no `/lib/modules/6.1.83/build` symlink. The build
used the exact installed header directory explicitly; no mismatched Ubuntu
header package was installed.

## Reversible live binding

Before mutation, the adapter was free and both USB interfaces were bound to
`cdc_acm`; no CH343 module or udev rule existed. A rollback script was installed
before mutation. The module was copied only to
`/lib/modules/6.1.83/extra/ch343.ko`, loaded, and the existing interfaces were
live-bound to `usb_ch343` without reboot. The resulting device was
`/dev/ttyCH343USB0`, `root:dialout`, mode `0660`.

Captured state:

- `ch343_driver_before.txt` SHA-256:
  `ca4dfad39d5c443c7a58a6e5dbf89bac6d93add3da5a93a740486a1e9a708724`
- `ch343_driver_after.txt` SHA-256:
  `9b88a9372bb29e3adc037bb349ee0664ef4d2ac356b2ba4660735dde6717e9ef`

## Apples-to-apples torque-off result

The exact prior 50-tick preflight was repeated on `/dev/ttyCH343USB0` with the
same runtime commit `9cd4ca0`, config, 1 Mbit/s baud, four-millisecond timeout,
ID-13-last SyncRead order, isolated CPU 7, and `SCHED_FIFO 80`.

- completed records: `50 / 50`
- transaction failures: `0 / 800`
- CRC/device/timeout/partial/unexpected counts: all `0`
- read bursts, partial bytes, unexpected packets, telemetry drops: all `0`
- group round trip mean/p99.9/max:
  `3.588421 / 4.782763 / 4.783880 ms`
- extended round trip mean/p99.9/max:
  `0.813533 / 1.199473 / 1.201751 ms`
- total bus mean/p99.9/max:
  `5.437868 / 7.488103 / 7.490049 ms`
- tick p99/p99.9/max:
  `20.097414 / 20.097846 / 20.097894 ms`
- final torque-off: `ok`

The vendor driver removed the prior isolated device-status failure, but it did
not improve the governing `<5 ms` total-bus gate. The experiment therefore does
not unblock Gate 2. Machine-readable result: `preflight_ch343_summary.json`; raw
JSONL SHA-256:
`f494d2dc869b4abbf31d29758558eb3abbfc9dac9d66c74c4bc10d18282e9d2a`.

## Verified rollback

After evidence recovery, the CH343 interfaces were unbound, the module was
unloaded and removed, `depmod` was refreshed, and both interfaces were restored
to `cdc_acm`. Final checks proved:

- `/dev/ttyACM0` exists as `root:dialout` mode `0660`;
- `/dev/ttyCH343USB0` is absent;
- `ch343` is absent from `/proc/modules`;
- `/lib/modules/6.1.83/extra/ch343.ko` is absent;
- the adapter driver resolves to `/sys/bus/usb/drivers/cdc_acm`;
- the serial device has no process owner.

No reboot was required. The temporary rollback executable was removed after the
restored state passed verification.
