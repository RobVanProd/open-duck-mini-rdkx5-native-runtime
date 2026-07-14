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
