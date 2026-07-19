# NOT RUN — Hardware Gate 5: Suspended Policy Replay

No policy has been run on the X5 from this repository. The legacy 101-D golden
vector passes, and the stateful 115-D winner handoff has been independently
hash-checked and CPU-replayed. That handoff is explicitly not compatible with
the frozen v1 interface: it requires a versioned v2 assembler, recurrent state,
P30 observer, projected-reference suffix, and a different phase reset value.
No single deployment checkpoint is selected, the real-build COM audit remains
incomplete, and policy-side robot clearance is false.

After all of those blockers clear, `x=0` and `x=0.08` require separate authorization,
600 valid policy ticks under a finite total cap, complete runtime JSONL, control summaries, reviewed hashes,
and zero telemetry loss. A serial summary is always `REVIEW_REQUIRED`; software
does not grant robot clearance. Grounded replay remains prohibited.
