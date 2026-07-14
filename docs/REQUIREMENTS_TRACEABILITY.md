# Requirements Traceability

| Requirement | Implementation | Offline evidence | Hardware status |
| --- | --- | --- | --- |
| 101 observations / 14 actions | `contract.py`, `policy.py`, snapshot extractor/verifier | independent legacy-formula and named-mismatch tests | golden board vector pending |
| 50 Hz / bounded timing | `AbsoluteTicker`, `TimingSeries`, probe | 1,000-tick mock summary | Gates 1, 2, and 5 `NOT_RUN` |
| Gate 1 single-servo echo/read | torque-off `probe_single_servo` | mock JSONL/schema/status test | serial run `NOT_RUN` |
| `duck_config.json` semantics | `config.py` | config, strict boolean, finite phase, and offset-order tests | existing board file not read |
| Frozen servo map | `constants.py` | map used by bus and parity tests | physical side/sign check pending |
| Script parity | `open_duck_x5.tools` and root wrappers | all four tools run on mock | no motor commands run |
| Crash/exit torque-off | `TorqueGuard`, `Runtime.close` | injected-crash test | board cutoff behavior pending |
| Direct STS3215 bus | `bus/sts3215.py` | fixed frames and fake-transport tests | serial adapter pending |
| SyncWrite + grouped read | preallocated bus frames | 14-response transport test | bus-time gate pending |
| Timeout/CRC/partial/device taxonomy | `ErrorCode`, parser, JSONL and v2 summary | zero-preserving per-class count tests | real fault distribution pending |
| Explicit staleness | `ServoSnapshot`, assembler rejection | stale-source tests | sustained-rate test pending |
| Serial minimum latency | verification/install scripts | shell syntax check | driver/sysfs unknown |
| Round-robin current/voltage/temp | extended read every tick modulo 14 | register decode test | units/value check pending |
| SCHED_FIFO + isolated core | `realtime.py`, setup scripts, unit example | configuration logic reviewed | X5 boot/runtime check pending |
| Preallocated hot-loop data | arrays, packet frames, telemetry record pools | lint/tests; no JSON I/O in loop | allocation/timing profile pending |
| Probe-decided Rust escalation | D002 and runbook | mock explicitly non-authoritative | decision pending valid RT run |
| BNO055 + contacts | nonblocking immutable publication in `sensors.py` | raw-unit, axis-remap, polarity, freshness, and blocked-I2C tests | labeled tilt/contact gate pending |
| Common timestamp clock | `clock.py` imported by all producers | coarse-clock issue caught by probe | X5 resolution pending |
| ONNX warm-up | `OnnxPolicy` float32 I/O binding, warm-up, and finite-value guards | fake-runtime binding/warm-up/failure tests plus snapshot tooling | real model golden run pending |
| 3.75 rad/s telemetry monitor | `ActionPipeline`, control JSONL | envelope test | suspended replay pending |
| Watchdog >40 ms / consecutive bus faults | `Watchdog` | work/period/failure tests | torque-off latency pending |
| Xbox/F710 controller parity | locked seven-command publication in `controller.py` | axis, A-edge pause, Y-edge head mode, and LB sprint-factor tests | physical controller mapping check pending |
| Staged authority boundary | dual CLI assertions, runbook, `NOT_RUN` files | guard tests | every gate awaits authorization |
| Artifact hashing | `tools/hash_artifacts.py` | checked-in SHA-256 manifest | update per authorized gate |

No row marked pending may be treated as passed based on the mock run.
