# Codex Notes

Read `AGENTS.md` first. This repository is the separate, ground-up X5-native runtime; the inherited port remains reference evidence only.

Current operating rule:

```text
measure -> compare to a pre-registered gate -> decide
```

Never substitute error-count zero for deterministic loop timing. Never silently fix the observation contract. Never report a hardware gate as run unless its raw artifact and hash are present.
