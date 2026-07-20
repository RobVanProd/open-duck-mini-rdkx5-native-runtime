# Control-Run Evidence

The operational runtime writes a bounded JSONL evidence stream. It is not a
console log and must remain complete: a writer error, queue overflow, or missing
record invalidates the run.

## Record sequence

Every normal runtime file has this order:

1. one `open_duck_x5.runtime_event.v1` `runtime_start` event;
2. one `realtime_verified` event when RT mode is required;
3. contiguous `open_duck_x5.control_tick.v1` records numbered from zero;
4. one final `runtime_halt` event with the halt reason, drop count, and final
   torque-off attempt/status/error.

The startup event freezes the runtime contract, config and policy SHA-256,
101/14 ONNX names and shapes, deterministic single-thread session settings,
joint/servo order, command, total and active tick caps, bus settings, controller,
RT requirement, and hardware assertions. The
tick schema requires all 14 transaction statuses, staleness, sensor ages,
observation/action validity, targets, implied target velocities, envelope flags,
and round-robin extended telemetry.

Schemas:

- `schemas/runtime_event.schema.json`
- `schemas/control_tick.schema.json`
- `schemas/control_summary.schema.json`

## Summarize without trusting counters

After the runtime has closed the JSONL file, build the reviewed summary:

```bash
summarize_control_run \
  --input gate5-x0.jsonl \
  --output gate5-x0-summary.json
```

The summarizer independently rejects missing/reordered ticks, event-order or
timestamp errors, stale/status contradictions, wrong extended-telemetry order,
wrong joint/servo/ONNX contract, incomplete RT partition evidence, malformed
envelope flags, and input/output path collisions. It recomputes percentiles,
transaction counts, failure rate, read bursts, staleness, command identity,
sensor ages, per-joint envelope events, and extended-telemetry coverage from the
raw records. The summary includes the raw JSONL SHA-256. It rejects a missing or
internally contradictory torque-off result, and `torque_off_confirmed=false`
prevents both `run_status=COMPLETE` and a Gate 5 candidate result.

Shutdown is cutoff-first: after the control loop exits, the runtime issues a
redundant torque-off command before closing the controller, sensor workers,
serial bus, or telemetry writer. The terminal record is written last, so it can
carry the result of that cutoff attempt. This is command-path evidence, not a
measurement of physical rail decay; the Phase 6 hardware artifact remains
`NOT_RUN` until cutoff latency is measured on the supported robot.

`--max-active-ticks` is distinct from the hard `--max-ticks` cap. Gate 5 uses
600 valid policy ticks while allowing a bounded paused startup window. Reaching
the total cap before the active target is a safety halt, not a completed replay.
For serial Gate 5 the physical controller is a pause/unpause device only: the
runtime fixes X to the authorized value, zeros the other six command fields, and
holds the phase factor at 1.0. The summarizer verifies the recorded non-X fields.

## Interpretation

- Mock summaries are always `INFORMATIONAL_ONLY` and
  `hardware_gate_status=NOT_APPLICABLE_MOCK`.
- Serial summaries are always `REVIEW_REQUIRED`, even when every recomputed
  boolean is green.
- `gate5_timing_and_bus_candidate=true` means only that the recorded stream met
  the preregistered mechanical checks. It does not grant policy or robot
  clearance and never authorizes grounded replay.
- Hash the reviewed summary and other gate artifacts with
  `python tools/hash_artifacts.py` only after operator review.
