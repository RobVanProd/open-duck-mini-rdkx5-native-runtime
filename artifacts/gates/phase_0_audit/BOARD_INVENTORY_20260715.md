# RDK-X5 Read-Only Board Inventory

Status: `CAPTURED_READ_ONLY`

Collection ID: `duck-evidence-golden-20260715`

Archive SHA-256:
`352aace265867296af2559a8792cfd8cfe3f182d57e87437f52ad166ab07f617`

The 836,355-byte archive passed its board-side and downloaded SHA-256 checks.
All 197 entries in its internal manifest also passed. The raw bundle remains
local and is intentionally not committed because it contains copied legacy
source and large telemetry.

## Board and real-time state

- D-Robotics RDK X5 V1.0, Ubuntu 22.04, Linux 6.1.83 aarch64.
- Eight Cortex-A55 CPUs (`0-7`), 300-1500 MHz, `schedutil` governor during capture.
- Kernel reports SMP `PREEMPT`, not PREEMPT_RT.
- No `isolcpus`, `nohz_full`, or `rcu_nocbs` boot arguments.
- `/sys/devices/system/cpu/isolated` is empty.
- Collector ran SCHED_OTHER priority 0 with affinity `0-7`; `RLIMIT_RTPRIO` is 0.
- USB controller interrupts were routed to CPU 0 in the captured table.
- `/boot/boot.cmd` constructs boot arguments and compiles to `/boot/boot.scr`;
  `/boot/Image` is selected. `/boot/Image-rt` exists but is not selected.

This state is insufficient for an escalation-decision timing run. CPU isolation,
RT permission setup, a reboot, and runtime verification must precede that evidence.
The topology-backed control-core plan is CPU 7 with CPUs 0-6 as housekeeping.

## Serial and buses

- Servo adapter: `/dev/ttyACM0`, stable `/dev/serial/by-id` link present.
- USB ID `1a86:55d3`, `cdc_acm` driver, USB full speed (12 Mbit/s).
- Device permissions: `root:dialout`, mode `0660`; no process held it at capture.
- No `latency_timer` exists, so the inherited FTDI rule cannot apply.
- Nine I2C adapters exist (`i2c-0` through `i2c-8`); no active address scan ran.
- `gpioinfo` is not installed. Legacy source says BCM 22/27 with active-low
  contact semantics, but physical line verification remains a sensor-gate item.

## Installed runtime environment

- Python 3.10.12
- NumPy 1.26.4
- ONNX Runtime 1.18.1
- pypot 5.0.2
- rustypot 0.1.0
- pyserial 3.5
- smbus2 0.6.1
- pygame 2.6.0

The live `/home/sunrise/duck_config.json` validates and has SHA-256
`131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b`.
It has `start_paused=true`, `imu_upside_down=true`, phase offset `0.0`, and the
corrected left-knee soft offset `0.0371` rad.

`/home/sunrise/BEST_WALK_ONNX_2.onnx` has SHA-256
`3c606f9381a1710cc8fecdb7442787dcbfce3ee9bc02a6f1224774ab2b3a1067`.
ONNX Runtime loads it as `obs [1,101] -> continuous_actions [1,14]`.

## Safety and remaining evidence

The collection performed no inference, serial open, I2C address scan, GPIO read,
goal write, torque enable, or motion. Gate 1 status is `NOT_REQUESTED`.

The preserved-runtime golden vector is now verified separately under
`artifacts/contracts/`. Candidate-policy training semantics and every hardware
timing/sensor gate remain blocked pending their own evidence and authorization.
