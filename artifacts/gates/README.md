# Gate Artifacts

Hardware gates are not run during offline development. Each gate directory starts with a `NOT_RUN.md`; replace it only after the raw run, summary, environment capture, operator notes, and hashes are reviewed.

Phase 7 keeps a separate status for each of the five sequential hardware gates
under `phase_7_hardware/`. Never delete or replace a later `NOT_RUN` record when
an earlier gate passes.

Never treat mock results as a hardware pass. Generate the manifest with:

```bash
python tools/hash_artifacts.py
```
