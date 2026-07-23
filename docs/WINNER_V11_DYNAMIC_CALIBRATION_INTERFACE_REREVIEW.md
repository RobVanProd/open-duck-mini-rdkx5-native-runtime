# Winner-v11 Dynamic Calibration Runtime Rereview

status: `PASS_WINNER_V11_LF_BINDING_HOLD_ZERO_PPO_ONLY`

decision: `AUTHORIZE_POLICY_WINNER_V11_ZERO_PPO_CPU_MECHANICS_CONTRACT_ONLY`

JSON SHA-256: `6c4f05830d2f1b661bd27297a40e05da5256c701427d929cf1a480d731bfcf57`

Policy request: `RobVanProd/open-duck-mini-rdkx5@07893eecb7858f15a61d8763be526ca4800ebafa`

Corrected committed LF artifact SHA-256: `2500c731a3413b08568e6e88b57300d2c8c86b61f9fe7418f3efa21ab639c8a2`

## Rereview result

The metadata-only correction closes the prior LF/CRLF hold. The exact
committed artifact and all nine source receipts match authoritative Git blobs,
the prior runtime HOLD remains unreclassified, and no zero-PPO run began before
this review. No graph, ABI, gate, or authority changed.

The unchanged calibrator `115+14+64 -> 14+14+64` and locomotion
`115+14+64+64 -> 14+14+64` ABIs remain feasible against the exact Winner-v10
protected hashes. The corrected request now explicitly inherits the complete
Winner-v6 sequence, context, pause, and fail-closed contract.

Default-off x=0 remains byte-exact Winner-v10. Runtime does not impose a host
x=0 deadband: a future enabled graph may produce nonzero corrective action at
x=0, but that behavior is graph-authoritative and requires a separate behavior
gate. Normalized action guards remain graph-owned; inward torque remains
plant/XML semantics and creates no runtime limiter.

## Authority boundary

Policy may freeze and run one separately named CPU-only zero-PPO mechanics
contract with 250 calibrator ticks, zero optimizer steps, and zero behavior
cells. This does not authorize training, an optimizer step, Colab, GPU/iGPU,
runtime implementation, X5 or robot access, serial/GPIO/I2C, torque, motion,
Gate 5, deployment, or robot clearance.
