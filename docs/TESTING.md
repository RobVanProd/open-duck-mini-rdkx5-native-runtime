# Offline Verification

Install and run:

```bash
python -m pip install -e ".[dev]"
python -m ruff check .
python -m pytest
```

The suite covers fixed STS3215 packet vectors, checksum and partial-frame
classification, grouped state reads, round-robin extended telemetry, numeric
conversions inherited from `rustypot==0.1.0`, all 101 observation fields, all 14
actions, history order, phase order, stale-source rejection, config validation,
field-labeled legacy snapshot extraction/comparison, mock JSONL schema,
per-error taxonomy, tracking statistics, authorization guards, watchdog
triggers, torque-off on an injected exception, BNO055 units/remapping,
active-low contacts, and nonblocking publication when I2C is delayed.
The ONNX host is exercised with a fake runtime that verifies pre-loop warm-up,
single-thread sequential/no-spin session options, bound float32 buffers,
zero-copy output reuse, and rejection of non-finite data.
Controller tests cover both right-stick layouts, locked seven-command snapshots,
A-button pause edges, the inherited Y-button head-control mode, and LB sprint
phase factor.
The evidence-collector tests verify safe default operation, schema and manifest
integrity, likely-credential exclusion, policy-binary exclusion, 115-input ONNX
rejection, and dual-acknowledgement enforcement before output creation.
Real-time tests verify pre-spawn housekeeping affinity, control-thread-only
`SCHED_FIFO`, rejection of a service pinned only to the control CPU, and failure
when any background native thread can execute on the isolated core.
The labeled sensor-probe tests validate JSONL/summary schemas, shared-clock
freshness evidence, explicit review-required orientation status, and refusal to
open X5 GPIO/I2C before both hardware acknowledgements.
Telemetry tests prove output-open failures are reported synchronously and that
exhausting any bounded record pool fails the run instead of silently dropping
evidence. Runtime guard tests reject incomplete Gate 5 scope and
`start_paused=false` before serial or real-time setup is touched. Path-collision
tests protect config/policy/evidence files, while cleanup tests verify that a
stop during the home move cuts torque, final cutoff precedes every potentially
blocking resource close, and a failed cutoff status cannot look successful.
Control-evidence tests validate startup/tick/event/summary schemas, source and
config/policy hashes, contiguous tick numbering, timestamp-derived periods,
fixed-command readback, transaction recounting, round-robin telemetry coverage,
per-joint envelope reconstruction, terminal torque-off proof, output collision
guards, and the distinction between total ticks and valid policy ticks.
Timing-probe summaries are schema-checked and bind their raw JSONL SHA-256,
authorization assertions, RT partition, moving-gate scope, and final cutoff
status. The comparison builder rejects halted/incomplete summaries, refuses
source overwrite, and labels serial results `REVIEW_REQUIRED` rather than
minting an automatic hardware pass.
Gate 1 uses the same evidence discipline for its torque-off single-servo stream,
including response framing and a hardware-only review candidate field.

The CI workflow performs only offline operations. It has no board credentials,
hardware flags, policy file, or grounded execution path.

## Mock timing artifact

```bash
runtime_timing_probe --bus mock --ticks 1000 \
  --output artifacts/runs/mock/timing.jsonl \
  --summary artifacts/runs/mock/summary.json
python tools/compare_timing.py \
  --new-summary artifacts/runs/mock/summary.json \
  --output artifacts/comparisons/baseline_vs_new.mock.json
python tools/hash_artifacts.py
python tools/hash_artifacts.py --check
```

Mock timing is informational only. It validates accounting and artifact
production; it cannot authorize a phase or trigger the native-extension
escalation criterion.
