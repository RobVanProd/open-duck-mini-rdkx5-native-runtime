# Phase 0: Pi Inheritance Audit

Status: complete for the preserved source snapshot; board package/sysfs verification remains pending explicit hardware authorization.

Audited reference: `RobVanProd/open-duck-mini-rdkx5` commit `84491f866139b9fd7d681e63da3b6f72bf07b991`. All text source under `runtime/` was inspected; audio assets and polynomial coefficient payloads were treated as data. Dependency inspection included the published `rustypot==0.1.0` source distribution and pypot branch `support-feetech-sts3215` at `f6d305e70e1640f66188b256dfd1dcfeb8ab8a59`.

## Executive result

The port is not an X5-native timing design. It keeps the Pi application's relative-sleep Python loop, adds platform shims for I2C/GPIO, and places blocking serial retries directly inside the tick. Its behavior can therefore become smoother in error logs while becoming less deterministic in time. The direct replacement must not reproduce those control-flow and buffering choices.

## Serial and servo path

| Inherited assumption | Evidence | Timing/reliability effect | Replacement rule |
| --- | --- | --- | --- |
| Serial device is `/dev/ttyACM0` | HWI and utilities hard-code it | Device naming and driver are assumed, not verified | CLI/configurable path; report driver and sysfs path |
| Bus is always 1 Mbps | `rustypot.feetech(port, 1000000)` | Correct only if all servos and adapter match | Verify at gate 1; include baud in every artifact |
| Published rustypot serial timeout is 1000 ms | `rustypot==0.1.0` binding constructs `serialport` with `Duration::from_millis(1000)` | One missing response can exceed 50 nominal ticks | Use an absolute per-cycle microsecond-scale deadline and explicit timeout result |
| Eight catch-all retries are safe | `HWI._retry(..., tries=8)` with 3 ms sleep | Hides failure bursts and can add at least 21 ms of sleeps, plus blocking call time | No hidden retry in the tick; count the first failure by class |
| Position and velocity are separate reads | `get_obs()` calls two rustypot sync reads | Two requests and two 14-response trains per tick | One grouped read from address 56 for position+speed |
| Utility and runtime stacks may differ | Hot path uses rustypot; configure/record tools use pypot | Different timeouts, units, error behavior, and port ownership | One direct bus implementation for runtime and tools |
| FTDI Pi udev rule applies | Pi README sets `ftdi_sio latency_timer=1`, while runtime path is normally `ttyACM0` | `ttyACM0` is commonly `cdc_acm`, which exposes no FTDI timer | Inspect the actual X5 driver; set only an exposed tunable |
| Python dependency is reproducible | `rustypot==0.1.0` is pinned, but its source `Cargo.toml` points to a moving git branch without a revision | Rebuilding the same sdist can compile different Rust source | Own the packet implementation and test known frames |

The exact published rustypot binding allocates new Rust/Python vectors on every read/write, locks a mutex, converts values, and maps all failures to `PyIOError`. Its custom Feetech sync read is instruction `0x82` followed by one status packet per requested ID. It does not expose timeout versus checksum versus partial response to Python. It also prints CRC diagnostics inside the lower layer.

pypot is not in the walking hot path, but it is installed and used by motor configuration, voltage, and characterization scripts. Its default serial timeout is 50 ms. This split is the relevant “layering”: two independently behaving bus abstractions serve one robot, and their results are not directly comparable.

## Error handling and stale data

- HWI catches every exception, retries eight times, prints the final exception, then returns `None` for failed position or velocity reads.
- The walking loop sees `None` and immediately `continue`s. It does not account for the failed transaction in its deadline logic and can begin another read burst without sleeping.
- Position and velocity are all-or-nothing arrays. The code cannot identify which servo or error class failed.
- The IMU queue returns the last sample when empty, without a timestamp or stale bit.
- Controller queues likewise retain the last command without age information.
- The telemetry patch records cumulative read/write counts but not timeout/CRC/partial per transaction.

Replacement: every servo receives an explicit status and staleness bit. Any required stale value rejects policy inference for that tick. Sensor samples carry monotonic timestamps. Consecutive failures feed the watchdog; nothing silently masquerades as fresh.

## Timing constructs

- Main tick scheduling uses `time.time()` and `time.sleep(max(0, period - took))`, a relative scheduler that drifts and is affected by wall-clock adjustment.
- A late tick only prints “budget exceeded”; no deadline or watchdog action follows.
- The process does not request SCHED_FIFO, CPU affinity, core isolation, memory locking, or GC control.
- ONNX Runtime session construction occurs before the loop, but no explicit warm-up inference exists.
- Each tick allocates through `np.concatenate`, `.copy()`, lists, dictionaries, action conversion, and ONNX input wrapping.
- Optional per-tick telemetry creates a nested dictionary and calls the logger from the control thread.
- Error reporting and CRC diagnostics print synchronously from the hot path.
- Paused state sleeps in 100 ms increments rather than maintaining the 50 Hz timing model.

Replacement: use `monotonic_ns`, absolute deadlines, preallocated arrays/records, disabled GC in the hot section, bounded ring-buffer telemetry, an off-thread writer, RT scheduling, pinned affinity, and runtime verification of isolation.

## Buffering and worker behavior

- IMU and controller workers use `Queue(maxsize=1)` with blocking `put`. If the consumer stops or pauses, the producer can block rather than overwrite with the newest sample.
- Consumers catch broad exceptions and reuse their last value indefinitely.
- The IMU worker uses relative sleep based on `time.time()` and has no common-clock timestamp.
- The serial lower layer owns its own receive behavior and provides no observable buffer/latency state.

Replacement sensor stores are latest-value buffers with sequence and `monotonic_ns` timestamps. The serial reader owns a bounded preallocated receive buffer and an absolute transaction deadline.

## Pi GPIO and I2C inheritance

- Platform detection defaults to Raspberry Pi unless `Hobot.GPIO` imports or `/dev/i2c-5` exists without `/dev/i2c-1`.
- RDK code assumes Raspberry Pi BCM numbers map unchanged: contacts 22/27, eyes 24/23, projector 25.
- Foot contacts intentionally invert the raw level: `False -> contact True`.
- Hobot pull-up setup catches `AttributeError` only; other API incompatibilities can abort.
- The smbus2 compatibility layer emulates CircuitPython `busio.I2C`, includes a process-local boolean “lock,” and has several read paths that default to register zero.
- IMU calibration pickle lookup is relative to the current working directory.
- `imu_upside_down=true` maps BNO055 axes `(Y, X, Z)` with all three signs negative; false keeps X negative and Y/Z positive.

Replacement: X5 components are explicit, no platform auto-detection. I2C bus and GPIO mapping are configured and verified in gate 3. Contact inversion and IMU mapping remain contract behavior.

## Observation/action findings

- Field layout is exactly the 101-vector in `OBSERVATION_ACTION_CONTRACT.md`.
- Current runtime phase is one tick behind the previously audited training/MuJoCo order because it advances phase after observation construction.
- Action output is home plus `0.25 * action`, with a 5.24 rad/s target slew limit, then head overlay.
- Soft offsets are added on write and subtracted on read.
- No explicit joint-limit clip exists in the deployed action path.
- ONNX normalization is embedded in the model.

Replacement: preserve these deployed semantics and make the phase discrepancy visible. Do not “clean it up” without a golden comparison and explicit decision.

## Safety gaps

- `RLWalk.run()` has a final torque-off path, but its constructor turns torque on before IMU/contact initialization; a later constructor exception is outside that guard.
- `v2_rl_walk_auto.py` does not reliably torque off on normal or interrupted exit.
- `head_puppet.py` only cleans up antennas on interrupt.
- `run_xbox_walk_safe.py` defaults to leaving torque enabled despite its safety-oriented name and header.
- Several configuration and characterization scripts lack a broad `finally` torque-off.
- Startup does not atomically verify all 14 servos before energizing and moving.

Replacement: torque is owned by a context guard established before enable. Startup verifies all IDs, warms policy, initializes sensors, then enables and slowly homes. Every signal, exception, watchdog, and normal exit attempts broadcast/all-ID torque-off.

## Other Pi-era paths deliberately excluded

- Pi OS, `raspi-config`, virtualenvwrapper, `RPi.GPIO`, `board`, `digitalio`, `pwmio`, and `picamzero` setup.
- `/home/bdxv2` and other Pi-user absolute paths.
- Camera, OpenAI navigation, sound, eyes, projector, and antennas inside the motion runtime.
- Pickle-based network IMU transport and unframed socket payloads.

They are not required for the frozen motion contract and would expand latency, dependency, and safety surface.

## Pending X5 facts

The following cannot be truthfully closed offline: actual USB-serial driver, available latency sysfs knobs, IRQ affinity, bootloader kernel-argument mechanism, isolated core, BNO055 bus/address, GPIO line mapping, installed servo firmware, and real transaction timing. The setup scripts report these as pass/fail/unknown; the gate artifact must contain the board output.
