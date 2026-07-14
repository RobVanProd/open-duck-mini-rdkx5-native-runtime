# Design Decisions

## D001 — Measurement before optimization

Accepted. The timing probe and failure taxonomy precede hardware optimization. Zero reported errors is not an acceptance metric.

## D002 — Python first, native only by gate

Accepted. Policy and servo transaction start in Python. A Rust extension is allowed only after an authorized RT/isolation run misses tick p99 or p99.9 gates. Only the transaction crosses FFI.

## D003 — One direct bus stack

Accepted. Runtime and parity tools share the direct STS3215 implementation. pypot and rustypot are audit references, not runtime dependencies.

## D004 — Reject stale observations

Accepted. The frozen 101-vector has no staleness slots. A stale required input invalidates the tick; it is never silently reused for inference.

## D005 — Preserve deployed phase order pending golden evidence

Accepted provisionally. The inherited real runtime's phase order is preserved even though prior audit found training/MuJoCo advance phase earlier. Policy hardware gates remain blocked until a golden 101-element comparison is reviewed.

## D006 — No grounded execution surface

Accepted. Hardware CLIs require suspended/benched assertion. The runtime exposes no grounded mode from this workstream.
