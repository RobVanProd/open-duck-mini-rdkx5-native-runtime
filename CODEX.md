# Codex Notes

Read `AGENTS.md` first. This repository is the separate, ground-up X5-native runtime; the inherited port remains reference evidence only.

Current operating rule:

```text
measure -> compare to a pre-registered gate -> decide
```

Never substitute error-count zero for deterministic loop timing. Never silently fix the observation contract. Never report a hardware gate as run unless its raw artifact and hash are present.

Current rebuild state:

```text
This repository and branch agent/measurement-contract-evidence are the active
RDK-X5 runtime rebuild. Hardware Gates 1-3 are PASS_REVIEWED. Gate 4 is the
next sequential gate: its source/archive/launcher/validator contract is frozen,
CI is green, and execution remains NOT_RUN until Rob gives the exact supported
left-hip-yaw sine-sequence authorization required by the preregistration.

Gate 4 has no policy or COM dependency. The separate ground-up winner is a
stateful 115-D family and is not silently compatible with this repository's
frozen 101x14.v1 Gate 5 interface. Do not feed it to Gate 5, add an adapter, or
change observation semantics without a separately reviewed handoff decision.
```
