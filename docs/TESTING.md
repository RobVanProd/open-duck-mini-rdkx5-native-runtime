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
mock JSONL schema, authorization guards, watchdog triggers, and torque-off on an
injected exception.

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
