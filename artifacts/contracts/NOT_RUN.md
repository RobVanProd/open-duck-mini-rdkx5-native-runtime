# Legacy Contract Snapshot

Status: `NOT_RUN`

The field-by-field verifier and capture schema are implemented, but no board
snapshot has been captured. A valid result requires the preserved runtime's
actual 101-element ONNX input, current action/history, logical joint state,
phase, previous targets, offsets, and emitted targets from the same labeled
tick. Hardware access remains subject to explicit authorization.

The preserved runtime already emits the required data when invoked with
`--log-telemetry --telemetry-every-n 1`. Extract and verify an adjacent tick:

```bash
extract_contract_snapshot legacy-telemetry.jsonl --tick <tick> \
  --output legacy-contract-snapshot.json
verify_contract_snapshot legacy-contract-snapshot.json \
  --output artifacts/contracts/legacy-contract-report.json
```

Any mismatch blocks policy Gate 5. Do not alter scaling or field order to make
the report pass.
