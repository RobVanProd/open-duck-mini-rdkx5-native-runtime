# Design Decisions

## D001 — Measurement before optimization

Accepted. The timing probe and failure taxonomy precede hardware optimization. Zero reported errors is not an acceptance metric.

## D002 — Python first, native only by gate

Accepted. Policy and servo transaction start in Python. A Rust extension is allowed only after an authorized RT/isolation run misses tick p99 or p99.9 gates. Only the transaction crosses FFI. The serial all-14 probe refuses to run without verified `SCHED_FIFO`, control-core affinity, and exclusion of every background native thread from that core.

## D003 — One direct bus stack

Accepted. Runtime and parity tools share the direct STS3215 implementation. pypot and rustypot are audit references, not runtime dependencies.

## D004 — Reject stale observations

Accepted. The frozen 101-vector has no staleness slots. A stale required input invalidates the tick; it is never silently reused for inference.

## D005 — Preserve deployed phase order pending golden evidence

Accepted provisionally. The inherited real runtime's phase order is preserved even though prior audit found training/MuJoCo advance phase earlier. Policy hardware gates remain blocked until a golden 101-element comparison is reviewed.

## D006 — No grounded execution surface

Accepted. Hardware CLIs require suspended/benched assertion. The runtime exposes no grounded mode from this workstream.

## D007 — Incomplete telemetry invalidates a run

Accepted. Bounded queues remain off the hot thread, but pool exhaustion, queue
overflow, and writer I/O failure are fatal evidence errors. A run with an
unrecorded tick or envelope event cannot remain `COMPLETE`.

## D008 — Reserve serial runtime for the exact Gate 5 scope

Accepted. Gate 1/2/4 use their dedicated probes. Serial policy execution also
requires a per-invocation Gate 5 assertion, a 101/14 policy, `start_paused=true`,
a finite duration, and exact `x=0` or `x=0.08`; each command is authorized and
reviewed separately.

## D009 — Recompute Gate 5 evidence from a complete JSONL stream

Accepted. The runtime records hashed startup provenance and contiguous tick/event
records. An offline summarizer recomputes timing, bus failures, bursts, command,
staleness, telemetry coverage, and envelope events rather than trusting runtime
counters. Mock runs cannot become hardware evidence, and serial summaries always
require human review.

## D010 — Separate paused wall-clock bounds from policy duration

Accepted. `--max-ticks` is the hard total-loop cap and
`--max-active-ticks` is the required number of valid policy ticks. Gate 5 uses a
bounded paused startup window and cannot silently shorten a 600-tick replay.

## D011 — Make the Gate 5 controller pause-only

Accepted. Exact fixed-command replay cannot depend on joystick drift, head mode,
or LB state. Serial Gate 5 retains the physical pause/unpause edge but zeros all
non-X commands and fixes phase speed at 1.0. General controller parity remains
unchanged outside that gate.

## D012 — Make shutdown cutoff-first and evidence-bearing

Accepted. The runtime issues its redundant final torque-off before closing any
worker, sensor, controller, serial, or telemetry resource. The terminal event
records whether cutoff was attempted, its explicit bus status, and any error.
The offline summarizer cannot report a complete run or Gate 5 candidate without
`torque_off_status=ok`. This does not claim the physical rail has decayed; that
latency still requires Phase 6 hardware evidence.

## D013 — Make the RT preflight test the claimed scheduler state

Accepted. `verify_rt_setup.sh` uses exact Linux CPU-list parsing and a
short-lived process that must enter the requested CPU affinity and `SCHED_FIFO`
priority. Merely finding the core number as a substring or printing the current
non-RT scheduler cannot produce `result=PASS`.

## D014 — Keep ONNX inference on the RT control thread

Accepted. The CPU session uses sequential execution with one intra-op and one
inter-op thread, and disables worker spinning. The default ONNX Runtime pool can
span the physical cores; waiting on those SCHED_OTHER workers would reintroduce
unbounded housekeeping latency into the SCHED_FIFO loop. The session settings
are recorded in startup and policy-handoff evidence. Authorized timing still
decides whether this configuration is sufficient.

## D015 — Bind timing comparisons to complete reviewed evidence

Accepted. Timing summaries carry the raw JSONL SHA-256, RT and authorization
provenance, moving-gate scope, final torque-off status, and explicit Gate 2/4
candidate fields. The comparison builder rejects halted or incomplete input and
protects its source path. Mock output stays informational; serial output is
always `REVIEW_REQUIRED`, never an automatic `HARDWARE_RESULT`.

## D016 — Apply complete-evidence rules to Gate 1

Accepted. The single-servo summary binds its raw stream, authorization
assertions, final cutoff status, ping, per-class failures, bursts, and exact
two-byte response framing. Only a serial run with all of those checks can become
a Gate 1 review candidate, and the candidate does not advance Gate 2.

## D017 — Keep Gate 3 physical labels human-reviewed

Accepted. Sensor summaries bind raw data, config, and both hardware assertions,
and can identify a complete fresh timestamp stream. They cannot infer whether
the operator actually held the robot upright, tilted it in the named direction,
or pressed the named switch. The data candidate therefore remains subordinate
to explicit label review.
