# Winner-v11 Dynamic Calibration Runtime Schema Review

status: `SCHEMA_FEASIBLE_HOLD_WINNER_V11_ZERO_PPO_HASH_BINDING`

decision: `REQUEST_POLICY_LF_STABLE_HASH_CORRECTION_BEFORE_ZERO_PPO`

JSON SHA-256: `a5496d7f23195975f83c2536cd0b5a962a074eaf9afdf7b4455b33f496c7c080`

Policy request: `RobVanProd/open-duck-mini-rdkx5@ed3385dbaf30a8cd1580baf452ff0d8406a1121b`

Policy claimed artifact SHA-256: `045342b676d96557d451c6a85383f1381c3e3b2489cad3c2b943d85e0778adc6`

Committed LF artifact SHA-256: `738cdfe131b5ba70eebbac3333c1b04016c7abdcb8a370c4c682bc3bc9a65424`

Protected Winner-v10 graphs: `cf001269908d86e47eaa145ffda1d87e946a314ecf51056dc086c4cf10164ab6` and
`d52b63241340d9d56671b95c58bb0fc72af0998fd47d4684719f6cd44f244a10`

## Schema result

The unchanged calibrator `115+14+64 -> 14+14+64` and locomotion
`115+14+64+64 -> 14+14+64` ABIs remain implementable against the exact
Winner-v10 protected graph hashes. Winner-v10's inward-torque representation
is internal to the graph and does not change the runtime observation, action,
state, handoff, or target semantics. A disabled adapter can delegate both
`continuous_actions` and `previous_action_out` byte-for-byte without a host
limiter or projection.

Runtime can carry the final confirmed previous action and P30 applied-target
observer through the handoff, copy the final successful `h_out[1,64]` without
scaling into immutable session-local `calibration_context`, reset locomotion
hidden state and phase once, and refuse locomotion arming without a valid
context. No context may be persisted across a process restart.

Condition 7 also fixes an important boundary: the four x=0 traces across both
checkpoints and both actuator fits are byte-identical, exact-zero protected
deadband chains, and all terminate after 47 samples at torso COM X=-0.05 m.
Default-off must preserve that Winner-v10 result exactly. A future trained,
enabled Winner-v11 graph may need nonzero x=0 corrective action, so runtime
must not impose its own x=0 zero-action rule. Enabled x=0 behavior remains
graph-authoritative and must pass a separate behavior gate before any use.

## Hash-binding hold

The policy receipt is not stable over committed bytes. Its claimed artifact
hash is the SHA-256 of a Windows CRLF checkout, while the exact Git object at
the reviewed commit has the distinct LF hash above. Six embedded evidence
receipts have the same LF/CRLF mismatch. The builder and unchanged network
source receipts do match committed bytes, so the defect is metadata-only, but
the zero-PPO population may not be frozen or run from this review.

## Authority boundary

Policy may make only an LF-stable metadata correction and return it for a new
runtime review. The future mechanics contract requirements remain: both
protected hashes, exact default-off action/state identity, the 250-tick
JAX/ONNX calibrator and handoff chain, graph-owned enabled bounds, physically
chained protected semantics, zero behavior cells, zero optimizer steps, and
invalid-handoff rejection.

This review does not authorize training, an optimizer step, Colab, GPU/iGPU,
runtime implementation, X5 or robot access, serial/GPIO/I2C, torque, motion,
Gate 5, deployment, or robot clearance. Winner-v10's condition-7 hold and the
closed Winner-v6/v6b results remain unchanged.
