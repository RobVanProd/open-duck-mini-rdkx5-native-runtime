# Gate Artifacts

Hardware gates are not run during offline development. Each gate directory starts with a `NOT_RUN.md`; replace it only after the raw run, summary, environment capture, operator notes, and hashes are reviewed.

Never treat mock results as a hardware pass. Generate the manifest with:

```bash
python tools/hash_artifacts.py
```
