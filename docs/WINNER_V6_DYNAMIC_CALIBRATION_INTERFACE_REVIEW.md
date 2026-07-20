# Winner-v6 Dynamic Calibration Runtime Schema Review

status: `PASS_DYNAMIC_CALIBRATION_SCHEMA_HOLD_CPU_CONTRACT`

decision: `AUTHORIZE_POLICY_ZERO_PPO_CPU_SOFTWARE_CONTRACT_ONLY`

JSON SHA-256: `f0b95db839cff0c0329ffb1d9458c06e1ec6e6432b2b3ef84ef5f451550547c8`

Policy request: `RobVanProd/open-duck-mini-rdkx5@53fb7e28cad693e7ac9844559690bc9bbd35093c`

Artifact: `outputs/analysis/winner_v6_dynamic_calibration_interface_preregistration.json`

Artifact SHA-256: `a66ff7138bdc474c5bd6d0a8899eba041d00305a3d3bd38fc13b0c00e4c3007e`

## Review result

The proposed two-graph state and context handoff is implementable as a
default-off versioned runtime-v2 path. It does not alter or reinterpret the
frozen runtime-v1 101x14 contract. Runtime can preallocate the calibrator's
115+14+64 inputs and 14+14+64 outputs, pass the final successful `h_out[64]`
without scaling into an immutable locomotion `calibration_context[64]`, carry
the confirmed previous action and P30 applied-target observer across the
handoff, reset locomotion recurrent state and phase exactly once, and remain
paused while holding the last safe calibration target.

The learned latent has no physical field interpretation at runtime. Its exact
order is `learned_response_latent[0:64]`, its values must be finite float32 in
[-1,1], and it exists only for the current process. Runtime must never persist
or reload it after restart; a new successful calibration is required on every
startup, which automatically covers later disassembly or configuration change
without manual measurements.

## Remaining hold

This review authorizes only the policy-side zero-PPO CPU software contract.
Training remains blocked until that contract proves the exact graph ABIs,
default-off identities, action bounds, state/context chain, and JAX/ONNX
agreement. Runtime implementation, hardware access, torque, motion, Gate 5,
deployment, and robot clearance remain unauthorized.
