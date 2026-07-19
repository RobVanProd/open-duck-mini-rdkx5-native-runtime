# Winner-v2 Runtime-v2 Offline Review

Status: `HOLD_RECURSIVE_NUMERIC_CLOSURE_TOLERANCE_REVIEW`

This review covers a separate, default-disabled 115-D winner-v2 implementation.
It does not modify or route around the frozen 101-D v1 runtime. It has no
serial, GPIO, I2C, torque, hardware, or runtime-CLI integration and cannot load
on the robot through an existing command.

## Frozen identities

- original handoff commit: `ad1cd8e9b9fdacd26a5453318411dafe423588b4`;
- original handoff manifest SHA-256:
  `ba7143f5c653c0bb2f3f27930a7997dd5a2b90e3258bca516b7240bd0f21abd7`;
- selected-checkpoint evidence commit:
  `e0badd7aa79ff791212b8d3822f9eefdc4c162e0`;
- selected graph: `T2_EQUAL_512000.onnx`;
- selected graph SHA-256:
  `99d3afce0dfac127816c6327665c35b3c403e005f25cd0a505dfcb37f01304de`;
- selected-result SHA-256:
  `38b7fc13522844fc3fe7be848f50d68d5cb26064ddb391dbf5e17ff6f31d284f`;
- P30 fit SHA-256:
  `908ddb01e5d82e661d77b8f3cb186a84665695660b86b304c6d1ae89c79cdb0b`;
- projected-reference table SHA-256:
  `8102d9cd139584816d807ca635bcca6d37fa6b3c455848e00395b6d565968212`.

The 1024000 graph remains an audit/persistence sibling, not a selectable
deployment asset.

## Implemented contract

The isolated implementation provides:

- `obs float32[115]` plus stateful `previous_action float32[14]`;
- strict CPU-only ONNX Runtime ABI and hash checks;
- `obs[83:97]` from the pinned P30 realized-target observer;
- `obs[101:115]` from the pinned projected-reference table;
- phase reset `[1,0]`, current-phase observation, then confirmed advance;
- exact zero command or forward support `0.074 <= x <= 0.080`, with every
  other command component exactly zero;
- graph-owned rate limits/actual-centered guard/deadband with no host overlay,
  filter, projection, or action modification;
- `home + action * 0.25`, with the legacy 5.24 rad/s limiter evaluated only as
  an identity assertion;
- soft offsets applied only to the physical bus target, never the observer;
- preallocated observation, reference, observer, action, recurrent-state, and
  finite-check buffers; and
- an all-or-nothing tick transaction. Policy state, action histories, target
  history, P30 state, phase, and tick count advance only after an unambiguous
  confirmed send. A failed or ambiguous send discards every staged state.

Fresh servo, IMU, and contact samples must all carry the same tick epoch. A
stale sample, mixed epoch, nonfinite tensor, unsupported command, wrong hash,
nonidentity legacy limiter, or graph-rate excess fails closed before commit.

## Action-history finding

Independent assembly exposed a metadata defect in handoff v1. The authoritative
golden tensors and evaluator source require:

| Input | Value at control tick `t` |
| --- | --- |
| `obs[41:55]` | final action `t-2` |
| `obs[55:69]` | final action `t-3` |
| `obs[69:83]` | final action `t-4` |
| ONNX `previous_action` | final action `t-1` |

Pre-reset entries are zero. The runtime implements this golden-evidenced order.
The policy repository preregistered the correction, then committed the
metadata-only v1.1 package at
`e63226eb5b60a9a96cca4bfbb20ef231c0cada64`. This repository independently
reproduced replacement manifest SHA-256
`d771d188218152c782c7d688440e2dd2083b47fd9b883749123f89226c6827c5`,
all 21 file identities, the selected graph identity, and zero history error
over all 2,400 ticks. The action-history metadata blocker is closed.

## 2,400-tick result

The verifier evaluates four 600-tick cells: selected/audit graphs at `x=0` and
`x=.080`.

| Layer | Maximum absolute error | Disposition |
| --- | ---: | --- |
| Runtime semantic assembly | `2.086162567138672e-7` | pass at `1e-6` |
| Assembled `obs` tensors | `0` over every field/tick | bit-exact |
| Frozen-observation ONNX state chain | `4.76837158203125e-7` | pass at `1e-6` |
| Selected fully recursive action/history chain | `2.384185791015625e-6` | held; no rule preregistered |
| Audit-only fully recursive action/history chain | `3.814697265625e-6` | held; no rule preregistered |
| Selected recursive physical target | `5.960464477539062e-7 rad` | recorded |
| Selected recursive P30 target | `5.602507320290329e-7 rad` | recorded |

Every x=0 action and recurrent state is bit-exact zero. Fault injection passes
for failed-send rollback, stale data, mixed sample epochs, unsupported command,
and nonfinite sensor input.

The recursive difference is ordinary float32 cross-CPU ONNX output variation
feeding back through both recurrent state and observation history. It must not
be hidden with host rounding, quantization, projection, or post-hoc tolerance.
The policy side must preregister a recursive cross-CPU acceptance metric before
this result can be classified.

The machine-readable result is
`artifacts/gates/phase_5_policy/winner_v2_runtime_v2_verification_20260719.json`.

## Remaining gates

1. Receive a preregistered recursive cross-CPU numeric-closure rule.
2. Complete the powered-off direct-reaction torso-COM packet and receive the
   policy repository's reviewed result.
3. Receive policy-side `robot_clearance: true`.
4. Freeze the accepted runtime, selected graph, fit, reference, config, and
   evidence hashes.
5. Only then prepare a no-servo X5 CPU benchmark and a separately reviewed,
   separately authorized suspended Gate 5 launcher.

Gate 5 remains `NOT_RUN`. Grounded work remains out of scope.
