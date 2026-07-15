# Requirements Traceability

| Requirement | Implementation | Offline evidence | Hardware status |
| --- | --- | --- | --- |
| 101 observations / 14 actions | `contract.py`, `policy.py`, snapshot extractor/verifier | independent legacy-formula, named-mismatch tests, corrected-knee board snapshot | deployed golden vector exact; candidate training parity pending |
| 50 Hz / bounded timing | `AbsoluteTicker`, `TimingSeries`, probe; schema-bound raw/summary provenance | 1,000-tick mock summary, comparison, collision/tamper tests | Gate 2 torque-off tick p99.9 20.101307 ms; moving run blocked by bus gates |
| Gate 1 single-servo echo/read | torque-off `probe_single_servo`; raw hash/auth/cutoff/framing summary | mock tick+summary schema and provenance tests | 10,000-read serial run `PASS_REVIEWED` |
| `duck_config.json` semantics | `config.py` | config, strict boolean, finite phase, and offset-order tests | live file validated and hashed; no writes performed |
| Frozen servo map | `constants.py` | logical map plus distinct wire-order test | logical map unchanged; ID 13 last removes reproduced grouped-read CRC |
| Script parity | `open_duck_x5.tools` and root wrappers | all four tools run on mock | no motor commands run |
| Crash/exit torque-off | `TorqueGuard`; cutoff-first cleanup; terminal cutoff status | injected-crash, signal-during-home, cleanup-order, failed-cutoff, schema, and summary tests | physical cutoff latency pending |
| Direct STS3215 bus | `bus/sts3215.py` | fixed frames and fake-transport tests | all-14 torque-off path measured; moving run blocked |
| SyncWrite + grouped read | preallocated bus frames; ID-routed wire order ending 14,13 | 14-response and exact request-order tests | CRC mechanism repaired; bus max 7.703526 ms fails <5 ms gate |
| Timeout/CRC/partial/device taxonomy | `ErrorCode`, parser, JSONL and v2 summary | zero-preserving per-class count tests | preflight isolated CRC ordering and then one ID 13 device-status reply |
| Explicit staleness | `ServoSnapshot`, assembler rejection | stale-source tests | sustained-rate test pending |
| Serial minimum latency | verification/install scripts | shell syntax check | WCH 1a86:55d3 uses 12 Mbit/s `cdc_acm`; no `latency_timer`; transport review required |
| Round-robin current/voltage/temp | extended read every tick modulo 14 | register decode test | units/value check pending |
| SCHED_FIFO + isolated core | pre-spawn housekeeping partition plus verified control-thread isolation in `realtime.py`; exact-list and scheduler preflight | partition/offender/service-mask/parser tests | CPU 7 isolation, housekeeping 0-6, and `SCHED_FIFO 80` verified |
| Preallocated hot-loop data | arrays, packet frames, telemetry record pools | lint/tests; no JSON I/O in loop | allocation/timing profile pending |
| Complete evidence stream | bounded writers fail hard on pool/queue overflow or file errors | synchronous-open and forced-exhaustion tests | Gate 1 has 10,000 contiguous records and zero drops |
| Gate 5 provenance and summary | hashed runtime-start record, strict tick/event schemas, continuity-checking `summarize_control_run` | active/paused, command, envelope, schema, gap, path, and active-duration tests | serial summary `NOT_RUN` |
| Probe-decided Rust escalation | D002 and runbook | mock explicitly non-authoritative | RT tick gate green; Rust not triggered by bus/USB latency failure |
| BNO055 + contacts | nonblocking immutable publication plus guarded labeled `probe_sensors`; raw hash/auth provenance | raw-unit, axis-remap, polarity, freshness, blocked-I2C, schema, and guard tests | labeled tilt/contact review `NOT_RUN` |
| Common timestamp clock | `clock.py` imported by all producers | coarse-clock issue caught by probe | X5 monotonic clock reports 1 ns resolution |
| ONNX warm-up | `OnnxPolicy` float32 I/O binding, warm-up, finite guards, and single-thread sequential session | fake-runtime session/binding/warm-up/failure tests plus snapshot tooling | BEST model interface loaded; inference latency pending |
| 3.75 rad/s telemetry monitor | `ActionPipeline`, control JSONL | envelope test | suspended replay pending |
| Watchdog >40 ms / consecutive bus faults | `Watchdog` | work/period/failure tests | torque-off latency pending |
| Finite active replay duration | separate hard total-tick and valid-policy-tick caps | target-met and target-not-reached tests | 600 active-tick replay `NOT_RUN` |
| Xbox/F710 controller parity | locked seven-command publication in `controller.py` | axis, A-edge pause, Y-edge head mode, and LB sprint-factor tests | physical controller mapping check pending |
| Staged authority boundary | dual CLI assertions, movement/Gate-5-specific assertions, finite exact-command replay, runbook, `NOT_RUN` files | pre-I/O guard tests | Gate 2 authorized but stopped torque-off; Gates 3-5 await authorization |
| Board evidence extraction | safe-default collector, schemas, policy handoff | archive/manifest, secret-skip, 115-D rejection, and guard tests | Gate 1 bundle and 199-entry manifest verified |
| Artifact hashing | `tools/hash_artifacts.py` | checked-in SHA-256 manifest | update per authorized gate |

No row marked pending may be treated as passed based on the mock run.
