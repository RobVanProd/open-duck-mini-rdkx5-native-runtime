# Gate Artifacts

Hardware gates begin as `NOT_RUN`. Replace that marker only after the raw run,
summary, environment capture, operator notes, and hashes are reviewed. Gates 1
through 3 now have reviewed results; later gates retain their independent markers.

Phase 7 keeps a separate status for each of the five sequential hardware gates
under `phase_7_hardware/`. Never delete or replace a later `NOT_RUN` record when
an earlier gate passes. A failed torque-off preflight is recorded beside the
unchanged moving-gate `NOT_RUN` marker rather than being promoted to a gate run.

Never treat mock results as a hardware pass. Generate the manifest with:

```bash
python tools/hash_artifacts.py
```
