# NOT RUN — Suspended Policy Gate

No policy has been deployed or replayed from this repository. Grounded replay is outside authority.

Runtime startup provenance, tick/event schemas, and the independent control-run
summarizer are implemented offline. The preserved-runtime v1 golden vector
passes. The policy handoff at commit
`ad1cd8e9b9fdacd26a5453318411dafe423588b4` was independently hash-checked and
CPU-replayed. The 512000-step graph was subsequently selected, and the separate
default-off 115-D runtime-v2 implementation passed the complete 2,400-tick
offline matrix. It remains deliberately incompatible with the 101-D v1 path.

The T247 candidate is green offline and the T250 state-coherent integration is
exact, but deployment remains held. T251A2 proved 2,298 optimized paced ticks
byte-exact with no robot interfaces; its p99 `2.179714 ms` and p99.9
`2.545636 ms` missed the preregistered reserve screen. T251B and production
integration are not earned. No policy has been deployed or replayed, and no
serial policy summary exists.
