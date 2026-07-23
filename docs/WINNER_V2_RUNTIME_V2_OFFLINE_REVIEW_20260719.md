# Winner-v2 Runtime-v2 Offline Review

Status: `PASS_FINAL_OFFLINE_ASSET_FREEZE — HOLD_POLICY_CONFIGURATION_ROBUSTNESS`

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
| Selected fully recursive action/history chain | `2.384185791015625e-6` | record-only normalized difference |
| Audit-only fully recursive action/history chain | `3.814697265625e-6` | non-gating audit |
| Selected recursive logical target | `5.960464477539062e-7 rad` | pass versus half-LSB `0.0007669904 rad` |
| Selected recursive P30 target | `5.602507320290329e-7 rad` | pass versus half-LSB `0.0007669904 rad` |
| Selected raw STS goal difference | `0` counts over 16,800 words | bit-exact wire closure |

Every x=0 action and recurrent state is bit-exact zero. Fault injection passes
for failed-send rollback, stale data, mixed sample epochs, unsupported command,
and nonfinite sensor input.

The policy side preregistered a separate physical-space closure metric at
commit `182459eb4d5eb422a6936b7744f5730d22a9bb27`, before the formal rerun.
It preserves the direct same-input `1e-6` rule and derives its recursive bound
from half one 4096-count STS3215 position quantum. With the frozen real soft
offsets and exact runtime `rad_to_raw_position` conversion, every selected raw
goal word is bit-exact. Saturation, measured-rate/envelope, and inherited-5.24
classifications remain unchanged. No rounding, quantization, projection, or
host action repair was introduced.

The machine-readable result is
`artifacts/gates/phase_5_policy/winner_v2_runtime_v2_verification_20260719.json`.
Its SHA-256 is
`e1842ca64e91056b96c297666803bdeec7c5ff2950d4dfe32e27044379049b14`.
The same verifier invocation emits the policy-requested reduced result at
`artifacts/gates/phase_5_policy/winner_v2_recursive_cross_cpu_closure_20260719.json`
with SHA-256
`1292772e54f3734f2e48b5b0d75fb0c931949d3b7820598c4a9040a8b765dc5e`.
It contains the platform/provider and all preregistered decision inputs for
each of the four cells and binds the full result by hash.

Policy commit `bc4132b8a7a9db28e32bb873747c164b3a3abb4d` identified a
reporting-only mismatch: the reduced artifact called the teacher-forced
observation gate `<=1e-6`, but the frozen rule is exact zero. All four values
were already exactly zero. The runtime changed the gate name/evaluation to
exact equality and regenerated only the reduced artifact from the unchanged
full-result bytes. No outcome cell or accepted decision changed.

Policy commit `fab1feaa8d136fed0ab33d5590d0eec88ef90d8f` independently
reviewed the formal Windows result together with its separate Linux replay and
accepted `PASS_RECURSIVE_BIT_EXACT_WIRE_CLOSURE`. The reviewed CPU recursive-
numeric blocker is therefore closed on both sides.

Policy commit `4c99b5e3be203af419536382f11f3cce98283ba2`
independently reproduced the exact-zero reduced report and reran all 2,400
Linux CPU ticks. Its final acceptance-result SHA-256 is
`5380897c21d3e438dbc4216ba049bc14fb6beb227a13407943d4d092519b7ddc`.

The regenerated hash-only lock is
`artifacts/gates/phase_5_policy/winner_v2_offline_asset_lock_20260719.json`
with SHA-256
`48fd6d81aa9f621d0167536829ed7df62fe1d3b92b161607315aec9e8f64ef31`.
Its verifier passes 12 runtime files, two runtime evidence files, six policy
package files, and the exact policy acceptance result. The superseded lock
SHA-256 `4da893b3...de940` remains machine-revoked. Neither ONNX binary is
committed to this repository. Policy-side review of replacement lock SHA-256
`48fd6d81...f64ef31` subsequently passed at commit
`4521cd8fdcf5603dfb1405417ce38cd2f031fd84`. The exact policy review result
has SHA-256
`53351707ab1477541a4193b291bdc5ec8073ad500c171f7778fc36bf363aadea`,
contains 46 passing checks, and reports no issues.

The non-circular two-repository closure record is
`artifacts/gates/phase_5_policy/winner_v2_final_asset_freeze_closure_20260719.json`
with SHA-256 `281382bb...83110`. Its executable verifier returns
`PASS_FINAL_OFFLINE_ASSET_FREEZE`; it preserves all hardware and deployment
authority as false.

## Remaining gates

1. Policy-side preregistration of a variable-configuration mass/COM/inertia
   domain that requires no per-unit physical measurement.
2. Evaluate the current candidate over that complete CPU-only domain. If it
   fails, train or select a robust replacement and repeat the complete gate.
3. Repeat the two-repository asset freeze for any changed graph or package and
   receive policy-side `robot_clearance: true`.
4. Run the same frozen closure metric in a no-servo X5 CPU preflight. Only
   after that and the preceding gates, prepare a separately reviewed,
   separately authorized suspended Gate 5 launcher.

The no-servo preflight implementation and locked X5 wrapper now exist at
`src/open_duck_x5/winner_v2_cpu_preflight.py` and
`setup/run_winner_v2_cpu_preflight.sh`. Their frozen population and thresholds
are preregistered under
`artifacts/gates/phase_5_policy/x5_cpu_preflight/PRE_REGISTRATION.md`. The
wrapper's non-SHA envelope sentinel blocks before setup or ONNX load, so the X5
preflight remains `NOT_RUN`.

The separate `winner_v2_cpu_preflight_review` command is also frozen. It
rehashes the complete run directory and independently recomputes the two
10,000-sample timing populations and all gates rather than trusting the
launcher summary. It also verifies exact source/runner/policy/config identities
and CPU-governor restoration. Review output must be written outside the
immutable evidence directory and does not change the `NOT_RUN` or authority
state.

The prior direct-reaction and component-level COM worksheets are not selected
advancement routes. The frozen candidate's raw torso-X bracket passes through
`-22.65625 mm/+5.46875 mm` and fails at
`-23.4375 mm/+6.25 mm`; that is treated as policy fragility, not an operator
measurement obligation. See
`docs/WINNER_V2_VARIABLE_CONFIGURATION_ROBUSTNESS_REQUEST_20260719.md`.

The machine-readable current-state audit is
`artifacts/gates/phase_5_policy/winner_v2_completion_audit_20260719.json`.
Implementation commit `4962b28db91f6f141a0e4e53903f24ea319e79c3` and source
SHA-256 `73fdae8bb5036f222d4f4a5345512cf63965c69d80215ca6f9922898d43cc16d`
pin all 12 offline runtime requirements and explicitly distinguish the
superseded measurement route from the still-pending policy and physical gates.

Gate 5 remains `NOT_RUN`. Grounded work remains out of scope.
