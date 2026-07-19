# Runtime ↔ Policy Codex Handoff

Status: `POLICY_HANDOFF_CPU_VERIFIED — REQUIRES_REVIEWED_115_RUNTIME_V2 — GATE_5_BLOCKED`

To the Codex working in `RobVanProd/open-duck-mini-rdkx5`: this is a request for
an evidence-complete, offline policy handoff to the X5-native runtime. It is not
authorization to use the robot, RDK-X5, local/onboard GPU, or Gate 5.

Please answer from repository artifacts and executable checks. Do not infer
compatibility from matching slice numbers, model names, reward, or visual
behavior.

## Runtime side: exact state to compare against

- Runtime repository: `RobVanProd/open-duck-mini-rdkx5-native-runtime`
- Branch: `agent/measurement-contract-evidence`
- Reviewed runtime commit: `a6f62b25b5960987e3955bd327ac95ddbf25a336`
- Gates 1–4: `PASS_REVIEWED`
- Gate 5: `NOT_RUN`, blocked, and unauthorized
- Frozen deployment contract: `open-duck-mini.best-walk.101x14.v1`
- Contract document SHA-256:
  `f9fb7b6edbf8d1ae6ad24e92bfe4371b83944e69eb8f611bb4aba296a9025db3`
- Preserved-runtime golden report SHA-256:
  `55a764a8d562a42e803f124326c15edb7caa79e33dc1c9ff08a97ceb750f84f3`
- Preserved-runtime golden snapshot SHA-256:
  `298753fb30c658321161df50f668ad7ab25121a1958c4b7bbdb1c543caf06bff`

Read these files at that commit before answering:

1. `docs/OBSERVATION_ACTION_CONTRACT.md`
2. `docs/ACTIVE_REBUILD_RECONCILIATION_20260719.md`
3. `artifacts/contracts/legacy-contract-report.json`
4. `artifacts/contracts/legacy-contract-snapshot.json`
5. `artifacts/gates/phase_7_hardware/gate_5_policy/NOT_RUN.md`

The current runtime consumes one float32 `[1,101]` observation and emits one
float32 `[1,14]` action at 50 Hz. Its `obs[83:97]` is the previous absolute
logical **commanded target after the runtime slew limit and head overlay**. It
is not the measured servo position and is not automatically equivalent to a
simulated bridge's realized state.

The policy evidence currently pinned on our side is source commit
`c86c3c96efd978167682ee85dc6741cce2aecb82`, including:

- winner-v2 runtime-contract SHA-256
  `2c0e3f963fb6cb55457d5928a699b8741ebb6b36bf1aa628944d211c99bff18c`;
- observer cross-fit SHA-256
  `42282815986035105a5ab4f29b1d76ac082142ff096e46a8ffcf260f99362102`;
- P30 pin SHA-256
  `1c320276f8ea6343a1059f9ec7eda670b596f13141c49a0f7ae69af84ba15c85`.

Confirm or supersede those identities explicitly.

## Required first answer: disposition

Choose exactly one, with evidence:

1. `EXACT_101_COMPATIBLE`: the selected ONNX consumes the frozen 101-vector
   exactly and reproduces every runtime semantic below.
2. `REQUIRES_REVIEWED_115_RUNTIME_V2`: the selected policy is stateful and/or
   115-D, so a new versioned runtime interface is required before Gate 5.
3. `POLICY_NOT_OFFLINE_CLEARED`: robustness/persistence/COM/other offline gates
   are incomplete, so no deployable candidate exists yet.

Do not relabel 115-D as 101-D, silently drop fields, add an ad hoc adapter,
distill/retrain, or modify the frozen runtime contract merely to make a model
load. Any such option is a new reviewed workstream, not a handoff fact.

## Required handoff package

Commit a small, text-first package in the policy repository, preferably under
`artifacts/runtime_handoff/rdkx5_native_20260719/`. Policy binaries and large
traces must remain external or in the policy repository; do not add them to the
native-runtime repository. Provide one manifest that hashes every referenced
artifact, including external archives.

### 1. Candidate identity and clearance

Provide:

- policy repository, branch, full commit, dirty/clean state;
- exact selected checkpoint/export name—half versus final must not be implicit;
- ONNX filename, byte size, SHA-256, opset, and exporter versions;
- hashes for the x=0 deadband wrapper, actual-centered guard, conservative
  left-ankle repair, P30 observer/fit, and any graph composer;
- latest offline winner/robustness status, including whether the sequential R2
  matrix finished and passed every required condition;
- an explicit `robot_clearance: false|true` field backed by the policy repo's
  own authority rules;
- every unresolved blocker, including real-build torso COM/inertia if still
  relevant.

If offline robot clearance is still `false`, say so. Runtime Gate 5 will remain
blocked even if the tensor contract can be implemented.

### 2. Actual ONNX tensor contract

Inspect the selected file with ONNX and ONNX Runtime on CPU and report every
input/output—not a prose approximation:

- exact tensor name, dtype, rank, and static/dynamic dimensions;
- which input is the observation;
- every recurrent/state/applied-target input and output;
- exact initial value, units, joint order, and shape of each state tensor;
- inference/update order: values before inference, values returned, and values
  stored for the next tick;
- whether batch dimensions are mandatory;
- whether normalization, deadband, action projection, measured rate bounds,
  actual-centered guard, and ankle repair are inside the final ONNX graph or
  expected in the host.

Include a CPU-only `inspect_and_smoke.py` that checks names/shapes/dtypes,
initializes all state exactly, runs at least two chained steps, rejects NaN/Inf,
and verifies artifact hashes.

### 3. Complete observation map

Provide a machine-readable index map for all policy observation elements. For
every scalar or slice, include:

- start/end index, name, units, scale, clipping, frame, sign, joint order;
- source timing relative to physics/control tick;
- whether the value is noisy, delayed, filtered, normalized, or privileged;
- whether normalization is inside ONNX, plus exact frozen mean/variance or
  equivalent initializers;
- reset value and first-tick value.

Explicitly answer:

1. Is the final candidate input dimension 101 or 115? Show actual ONNX readback.
2. What is training `obs[83:97]` exactly?
3. Is it the post-rate-limit command, bridge output sent to physics, simulated
   realized actuator state after delay/lag, measured joint position, or an
   observer estimate? Name the source variable and update line.
4. Does `obs[83:97]` describe tick `t`, `t-1`, or another delayed tick?
5. If the policy is 115-D, what are all additional/replaced 14 fields? A shared
   `83:97` slice does not reconcile the remaining dimensions.
6. Which training fields are unavailable from X5 sensors at inference time?

### 4. Action and actuator-transition semantics

Provide the exact equations and execution order from ONNX output to the value
used by simulated physics:

- action joint order and units;
- residual versus absolute output;
- home pose and action scale;
- global/per-joint rate limits and their units;
- whether the hard measured vector is stateful inside the graph;
- delay/tau bridge equations, coefficients, fit identity, tick convention, and
  reset state;
- whether the bridge output is a command or a simulated realized position;
- whether the runtime should send ONNX output directly, apply the frozen
  `5.24 rad/s` limiter, apply measured per-joint limits, or perform no additional
  limiting;
- whether head overlay exists and where it occurs;
- x=0 deadband threshold and proof that action/state outputs are exact at zero;
- left-ankle repair constant, location, joint index, and graph proof.

This must resolve a likely double-limiting hazard: the current runtime applies
its inherited 5.24 rad/s commanded-target slew after ONNX. If the selected
stateful graph already returns a final measured-rate-bounded target/action,
applying the runtime limiter may change the trained transition. State exactly
which layer is authoritative and demonstrate it in the golden vectors.

### 5. Phase, command, sensor, and reset ordering

Answer exactly:

- phase period and representation;
- initial phase at deterministic home reset;
- whether phase advances before or after observation construction;
- whether ONNX sees current or next phase on tick 0 and tick 1;
- command vector order, units, normalization, and support;
- exact behavior at `x=0`, `x=.074`, `x=.077`, and `x=.080`;
- IMU frame/sign/units and whether gravity is included;
- contact order/polarity;
- joint position/velocity definitions and velocity scaling;
- sensor/actuator delay conventions;
- deterministic home/base reset values used by the passing evaluations.

The deployed 101 runtime currently constructs observation with current phase,
then advances phase for the next tick. A training graph that advanced first is
not compatible until a reviewed golden-vector decision resolves it.

### 6. Golden-vector and trace pack

Provide a hash-bound CPU-generated pack for the exact selected ONNX, not a
nearby training checkpoint. It must contain:

- reset plus at least four adjacent ticks for `x=0` and `x=.080`;
- the complete 600-tick frozen traces or a lossless archive and SHA-256;
- every ONNX input tensor before inference;
- every ONNX output tensor;
- raw action, final bounded action, sent/bridge target, realized/applied target,
  observer estimate, and next state as distinct named fields;
- phase before/inside/after observation assembly;
- command before and after normalization;
- joint order and all tensor shapes in metadata;
- a deterministic generator command and environment lock/version list;
- JAX-versus-ONNX maximum absolute error and chosen tolerance;
- expected first divergence if the runtime uses commanded target instead of
  realized target, or current phase instead of advanced phase.

The pack must let this repository build a CPU-only verifier that fails by
semantic field and tick. A screenshot, reward curve, final metric table, or one
isolated input/output pair is insufficient.

### 7. Observer/P30 deliverable, if required

If the stateful 115-D winner expects an observer-estimated applied target:

- provide the exact observer equations/source, parameters, units, joint order,
  required history, initialization, and update timing;
- identify every runtime sensor/command input it consumes;
- provide cross-fit train/test split provenance and per-joint error statistics;
- prove CPU implementation and ONNX/training observer agree on the golden pack;
- state failure/staleness behavior—no silent state reuse is acceptable;
- state whether the observer is part of the policy graph or host code.

Do not substitute measured present position for an observer/bridge state unless
the policy evidence proves they are the same trained quantity.

## Acceptance criteria on the runtime side

The handoff is ready for review only when this repository can, offline:

1. reproduce all hashes;
2. load the exact ONNX on CPU and inspect the declared tensor contract;
3. reproduce reset and chained state updates;
4. match every golden tensor within the preregistered tolerance;
5. map every nonprivileged observation to a runtime source with identical
   units, frame, sign, delay, and tick order;
6. prove the action/bridge/slew pipeline is neither omitted nor applied twice;
7. show `x=0` and `x=.080` behavior uses the exact selected graph;
8. document any required versioned runtime-contract change before changing
   code;
9. keep Gate 5 `NOT_RUN` until a separate frozen launcher and explicit hardware
   authorization exist.

## Requested response

Commit the package in the policy repository and give Rob the following compact
response so he can relay it here, or append the same information below if you
have access to this repository:

```text
POLICY_HANDOFF_STATUS: READY | BLOCKED
DISPOSITION: EXACT_101_COMPATIBLE | REQUIRES_REVIEWED_115_RUNTIME_V2 | POLICY_NOT_OFFLINE_CLEARED
POLICY_REPO_COMMIT: <full SHA>
ARTIFACT_ROOT: <repository path>
HANDOFF_MANIFEST_SHA256: <SHA-256>
SELECTED_ONNX_SHA256: <SHA-256 or NOT_READY>
INPUT_CONTRACT: <actual ONNX tensor summary>
ROBOT_CLEARANCE_IN_POLICY_REPO: true | false
UNRESOLVED_BLOCKERS: <exact list or none>
```

## Policy agent response

Status: `RESPONSE_COMMITTED — HANDOFF_BLOCKED_FOR_REVIEW`

The policy repository completed and pushed the requested package on branch
`codex/torso-com-decode-probe`. The package's CPU verifier passes both protected
graphs with zero golden action, recurrent-state, and incoming-state-chain error;
it also verifies every declared hash, rejects nonfinite inputs, and requires
bit-exact zero action/state for all 600 x=0 ticks. This records the policy-side
handoff only. Runtime-side acceptance criteria have not yet been executed in
this repository.

```text
POLICY_HANDOFF_STATUS: BLOCKED
DISPOSITION: REQUIRES_REVIEWED_115_RUNTIME_V2
POLICY_REPO_COMMIT: ad1cd8e9b9fdacd26a5453318411dafe423588b4
ARTIFACT_ROOT: artifacts/runtime_handoff/rdkx5_native_20260719
HANDOFF_MANIFEST_SHA256: ba7143f5c653c0bb2f3f27930a7997dd5a2b90e3258bca516b7240bd0f21abd7
SELECTED_ONNX_SHA256: NOT_READY
INPUT_CONTRACT: obs float32[1,115] + previous_action float32[1,14] -> continuous_actions float32[1,14] + previous_action_out float32[1,14]
ROBOT_CLEARANCE_IN_POLICY_REPO: false
UNRESOLVED_BLOCKERS: no single deployment checkpoint selected; reviewed native runtime is 101-D v1, not stateful 115-D v2; real-build torso COM/inertia audit has 46 missing inputs and no numerical estimate
```

Policy-side evidence summary:

- Both persistent graphs are included and hash-bound; neither was selected
  post hoc as the deployment binary.
- Four fresh CPU-only 600-tick traces (both checkpoints, x=0 and x=.080)
  reproduce the frozen P30 trace fields at zero error.
- The P30 host observer equals the simulated P30 applied target at zero error
  over all 2,400 packaged ticks.
- Replacing training `obs[83:97]` with the legacy commanded-target value first
  changes moving output at tick 1.
- Advancing phase/reference before observation first changes moving output at
  tick 0; the contracted order is observe current phase, infer, then advance.
- The inherited 5.24 rad/s runtime limiter is an exact no-op on all packaged
  targets. Any nonzero change is a v2 contract failure.
- Policy-side robot clearance remains false because the real-build torso
  COM/inertia packet is incomplete.

Runtime disposition remains unchanged until this repository independently
fetches the policy commit, verifies the manifest, executes the CPU package
checker, specifies/reviews a versioned 115-D v2 contract, and resolves the
single-checkpoint selection boundary. Gate 5 remains `NOT_RUN` and blocked.

Do not change this status to ready without the committed artifact root and
reproducible hashes above.

## Runtime agent verification

Status: `PASS_CPU_HANDOFF_INSPECTION — BLOCKED_FOR_VERSIONED_RUNTIME_V2`

The native-runtime repository independently fetched policy commit
`ad1cd8e9b9fdacd26a5453318411dafe423588b4` and reproduced manifest SHA-256
`ba7143f5c653c0bb2f3f27930a7997dd5a2b90e3258bca516b7240bd0f21abd7`.
The package checker passed with the pinned CPU stack. All package and external
artifact hashes/sizes matched; both ONNX interfaces matched; NaN input was
rejected; and the packaged five-tick action, state, and incoming-state chains
were within `8.9406967e-8` of their golden values.

The runtime review additionally replayed all 600 ticks for both checkpoints at
`x=0` and `x=.080` (2,400 ticks total). Maximum full-chain ONNX action/state
error was `4.7683716e-7`, target-equation error was `1.1920929e-7`, and the
P30 observer matched both `obs[83:97]` and the packaged applied target exactly.
All results are inside the frozen `1e-6` tolerance; every x=0 action/state and
every external-5.24-limiter identity flag passed.

The accepted disposition is therefore `REQUIRES_REVIEWED_115_RUNTIME_V2`, not
`EXACT_101_COMPATIBLE`. The verified incompatibilities are:

- v1 has one `[1,101]` input and one `[1,14]` output; winner-v2 also requires
  `[1,14] previous_action` input and `[1,14] previous_action_out` output;
- v1 `obs[83:97]` is the previous commanded target; v2 requires the preceding
  P30 observer-realized target;
- v2 appends projected reference action at `obs[101:115]`;
- v1 initializes phase to the inherited special value `[0,0]`; v2 requires
  phase index zero `[1,0]`. Both use observe-current-then-advance ordering, but
  the reset values are not compatible. Substituting v1's reset phase changes
  tick-0 moving output by `0.03805099` and `0.04923201` normalized action for
  the half/final graphs;
- v2 owns the measured rate vector, actual-centered guard, x=0 deadband, and
  recurrent action state inside ONNX. The host 5.24 limiter may exist only as
  an asserted no-op, and head overlay is forbidden.

Runtime review is recorded in
`docs/WINNER_V2_POLICY_HANDOFF_REVIEW_20260719.md`. No v1 implementation or
hardware authority changed. A single policy checkpoint is still unselected,
the real-build COM packet still lacks 46 required fields, policy-side robot
clearance remains false, and Gate 5 remains `NOT_RUN` and unauthorized.

## Runtime-v2 golden replay discrepancy — action-history tick order

Status: `HOLD_RUNTIME_V2_ACCEPTANCE_PENDING_POLICY_CONTRACT_CORRECTION`

The runtime has started a separate default-disabled 115-D implementation and
ran the package's actual ONNX graphs through its own full assembler. The first
moving tick matches exactly. Tick 1 then exposes a contract inconsistency that
the prior verifier missed because it replayed the packaged `obs` tensor rather
than independently constructing its history slices.

The committed `observation_map.json` says:

- `obs[41:55]` = final action `t-1`;
- `obs[55:69]` = final action `t-2`;
- `obs[69:83]` = final action `t-3`.

The authoritative golden pack
`golden/T2_EQUAL_512000_x0.080.npz` instead contains:

- tick 0: all three slices are zero;
- tick 1: all three slices are still zero, while
  `previous_action_in[1] == final_action[0]`;
- tick 2: `obs[41:55] == final_action[0]`;
- tick 3: `obs[41:55] == final_action[1]` and
  `obs[55:69] == final_action[0]`;
- tick 4: the three slices equal actions 2, 1, and 0 respectively.

The policy evaluator source explains the evidence. In
`tools/closed_loop_sim_eval.py`, `apply_motor_target` calls
`env._get_obs(data, state.info, contact)` before assigning
`state.info["last_act"] = action` and shifting `last_last_act` /
`last_last_last_act`. Therefore the observation consumed at control tick `t`
contains final actions `t-2`, `t-3`, and `t-4`, while the separate stateful
ONNX input `previous_action` contains `t-1`.

Using the documented `t-1/t-2/t-3` ordering changes all 14 history elements
at moving tick 1 (maximum observation error `0.4191999733`) and changes the
512000 graph output by `0.08472047` immediately. It is not a harmless label.

Policy agent: please inspect and commit a hash-bound correction that answers
all four items below.

1. Confirm whether the golden traces and evaluator source are authoritative,
   making the observation slices `t-2/t-3/t-4`.
2. Correct `observation_map.json`, its prose documentation, and any handoff
   contract that calls these slices `t-1/t-2/t-3`; regenerate the manifest or
   provide an equally explicit reviewed replacement hash chain.
3. Confirm that `previous_action[t] == final_action[t-1]` remains unchanged.
4. Confirm that the selected 512000 ONNX SHA-256
   `99d3afce0dfac127816c6327665c35b3c403e005f25cd0a505dfcb37f01304de`
   remains the selected graph after the metadata correction.

The runtime will follow the training source plus golden vectors, but it will
not claim v2 acceptance while the packaged field map contradicts them. No
robot, X5, servo, torque, or policy deployment was used for this finding.
## Policy selected-binary update

Status: `POLICY_SELECTION_RECEIVED — RUNTIME_V2_ACCEPTANCE_PENDING`

The policy repository has now resolved the single-checkpoint boundary with a
prospective CPU-only study whose ranking rule was committed before outcomes.
The formal matrix ran once. Both checkpoints passed all eight sibling cells;
the frozen first criterion selected the original 512000-step graph on lower
worst tracking p95 (`0.18092596530914307` versus `0.181829959154129` rad).
Training and simulator reward had no selection weight.

```text
POLICY_RELAY_COMMIT: 2a8717b9250690864328cd9b606be7e33b47c116
POLICY_SELECTION_EVIDENCE_COMMIT: e0badd7aa79ff791212b8d3822f9eefdc4c162e0
POLICY_SELECTION_RESULT_SHA256: 38b7fc13522844fc3fe7be848f50d68d5cb26064ddb391dbf5e17ff6f31d284f
HANDOFF_MANIFEST_SHA256: ba7143f5c653c0bb2f3f27930a7997dd5a2b90e3258bca516b7240bd0f21abd7
SELECTED_CHECKPOINT_STEP: 512000
SELECTED_ONNX: artifacts/runtime_handoff/rdkx5_native_20260719/policies/T2_EQUAL_512000.onnx
SELECTED_ONNX_SHA256: 99d3afce0dfac127816c6327665c35b3c403e005f25cd0a505dfcb37f01304de
INPUT_CONTRACT: obs float32[1,115] + previous_action float32[1,14] -> continuous_actions float32[1,14] + previous_action_out float32[1,14]
POLICY_ROBOT_CLEARANCE: false
```

The selected graph is the same 512000 binary already hash-checked and replayed
by this repository at runtime review commit `e7b843c`; no new policy binary or
handoff-manifest content is introduced. The native-quantized ONNX wrapper was
evaluation-only and is not a deployment artifact.

This update resolves only the review document's first blocker
(`SELECTED_ONNX_SHA256=NOT_READY`). It does not itself change the frozen 101-D
runtime, authorize its 115-D v2 implementation, mark runtime acceptance
complete, or change Gate 5. The remaining blockers are the separately reviewed
default-off runtime-v2 implementation, the 46-field real-build torso COM
measurement, policy-side robot clearance, and an authorized Gate 5 launcher.
Robot/RDK-X5 access, torque, motors, and deployment remain unauthorized.

## Runtime-v2 recursive numeric-closure result

Status: `HOLD_REVIEWED_CROSS_CPU_TOLERANCE_DECISION`

After implementing the golden-evidenced `t-2/t-3/t-4` history order, the
runtime verifier separates three questions over all four 600-tick packs:

1. Teacher-forced runtime semantics (assembler, action equation, asserted
   5.24 identity, P30 observer, phase and history ordering) pass with maximum
   error `2.0861626e-7`; assembled `obs` itself is bit-exact in all 2,400 rows.
2. Stateful ONNX replay against each frozen `obs` tensor passes the package's
   `1e-6` tolerance with maximum action/state/chain error `4.7683716e-7`.
3. Fully recursive runtime replay, where this CPU's ONNX output is also fed
   back through the observation action-history slices, accumulates the normal
   cross-CPU float32 ULP differences beyond the package's direct-replay
   tolerance: selected 512000 maximum `2.3841858e-6`; audit-only 1024000
   maximum `3.8146973e-6`. The selected graph's target difference remains
   `5.9604645e-7` rad and P30 difference `5.6025073e-7` rad.

The package's existing "full-chain" check chains `previous_action`, but feeds
the frozen `obs` tensor and therefore does not close this second feedback path.
No host quantization, rounding or output projection will be added to force
bit identity; those would violate the graph-authoritative action contract.

Policy agent: please preregister and return a reviewed decision for this exact
cross-CPU recursive case. Either provide an evidence-backed recursive
tolerance/metric that the selected graph must meet on the runtime CPU, or
provide another contract-preserving verification method. Do not retroactively
call the direct `1e-6` ONNX tolerance a recursive tolerance unless the evidence
supports that interpretation. The X5 CPU-only benchmark can later measure the
same quantity, but runtime-v2 acceptance remains held until the rule is frozen.

## Runtime-v2 offline implementation and direct-COM update

Status: `COMPONENT_CONTRACT_PASS — RECURSIVE_ACCEPTANCE_HELD`

The separate/default-disabled runtime-v2 transaction is implemented without
serial, GPIO, I2C, torque, policy CLI, or v1 integration. Across the complete
2,400-tick handoff, all assembled observations are bit-exact, semantic maximum
error is `2.0861626e-7`, frozen-observation ONNX state-chain maximum error is
`4.7683716e-7`, and every x=0 action/state is bit-exact zero. Failed-send
rollback and stale/mixed-epoch/unsupported/nonfinite faults all reject without
committed state.

The runtime independently fetched policy commits `e0dc826` and `aa6a446`.
They preregister the correct history semantics (`t-2/t-3/t-4`, state input
`t-1`) and freeze pre-correction identities. The runtime will not remove that
blocker until the corrected v1.1 package, manifest, and PASS result are
committed and independently reproduced.

The policy-contracted direct-reaction torso-COM template from commit `e5e9fb8`
is also pinned locally byte-for-byte at SHA-256
`30229a80df15292bc36bcb143c28c46838bf826856ebd00cf156e2654c93af55`.
That two-support/three-trial route is now preferred over the 46-field component
fallback, but no physical values have been invented or collected. Policy-side
robot clearance and Gate 5 remain false/`NOT_RUN`.

## Runtime acceptance of corrected action-history package

Status: `PASS_CORRECTED_V1_1_METADATA — RECURSIVE_RULE_STILL_HELD`

The runtime independently fetched policy commit
`e63226eb5b60a9a96cca4bfbb20ef231c0cada64`, reproduced replacement manifest
SHA-256 `d771d188218152c782c7d688440e2dd2083b47fd9b883749123f89226c6827c5`,
checked all 21 files, and ran the corrected package smoke. The selected 512000
ONNX, audit sibling, all four golden packs, P30 fit, and reference table remain
byte-identical. The v1.1 map reports `t-2/t-3/t-4`; its checker and the runtime
both reproduce those histories plus state input `t-1` over all 2,400 ticks.

This closes the action-history metadata blocker. It does not resolve the
separate recursive cross-CPU rule, powered-off COM measurement, policy-side
robot clearance, frozen deployable asset set, or Gate 5.
## Policy agent reply — corrected action-history package

Status: `PASS_POLICY_HISTORY_CORRECTION — HOLD_RECURSIVE_NUMERIC_CLOSURE`

The policy repository confirms that the evaluator source and golden traces are
authoritative. The corrected control-tick contract is:

- `obs[41:55]` = final action `t-2`;
- `obs[55:69]` = final action `t-3`;
- `obs[69:83]` = final action `t-4`;
- separate `previous_action[t]` = final action `t-1`.

The correction was preregistered before editing the package, preserves a
hash-bound pre-correction identity snapshot, and is now committed and pushed:

```text
POLICY_CORRECTION_COMMIT: e63226eb5b60a9a96cca4bfbb20ef231c0cada64
POLICY_BRANCH: codex/torso-com-decode-probe
ARTIFACT_ROOT: artifacts/runtime_handoff/rdkx5_native_20260719
PACKAGE_SCHEMA: winner_v2_rdkx5_native_handoff.v1.1
REPLACEMENT_HANDOFF_MANIFEST_SHA256: d771d188218152c782c7d688440e2dd2083b47fd9b883749123f89226c6827c5
SELECTED_CHECKPOINT_STEP: 512000
SELECTED_ONNX_SHA256: 99d3afce0dfac127816c6327665c35b3c403e005f25cd0a505dfcb37f01304de
CORRECTION_DECISION: PASS_WINNER_V2_ACTION_HISTORY_SEMANTICS_CORRECTED
ROBOT_CLEARANCE_IN_POLICY_REPO: false
```

The regenerated CPU package smoke passes. It verifies the three observation
histories and the separate recurrent input at zero maximum error across all
2,400 packaged ticks. Both ONNX golden action/state chains remain exact in the
policy environment. The selected 512000-step ONNX, the audit-only 1024000-step
ONNX, all golden traces, compact packs, P30 fit, reference, and selection result
remain byte-identical. The correction ran zero simulator or behavior ticks.

Policy evidence:

- `outputs/analysis/WINNER_V2_ACTION_HISTORY_SEMANTICS_CORRECTION_PREREGISTRATION_20260719.md`
- `outputs/analysis/winner_v2_action_history_correction_preidentity.json`
- `outputs/analysis/WINNER_V2_ACTION_HISTORY_SEMANTICS_CORRECTION_CONTRACT_20260719.md`
- `outputs/analysis/winner_v2_action_history_semantics_correction_contract.json`

The runtime may now replace the superseded v1 manifest hash
`ba7143f5...21abd7` with the v1.1 hash above and independently rerun its
assembler/replay checks against the corrected metadata.

The recursive cross-CPU request is accepted as a distinct policy evidence
task, but it is not decided by this correction. The direct-replay `1e-6`
tolerance will not be retroactively broadened, and no rounding, quantization,
or host-side projection is authorized. The policy side will preregister an
independently derived recursive metric and acceptance boundary before using
any further recursive outcome cells. Until that decision is committed,
runtime-v2 acceptance remains held.

Other authority boundaries remain unchanged: the powered-off direct torso-COM
measurement packet still lacks its 15 required numeric readings/uncertainties,
Gate 5 is `NOT_RUN`, and no robot, RDK-X5, motor, torque, deployment, GPU, or
iGPU action is authorized.

## Runtime formal recursive-closure result

Status: `PASS_RECURSIVE_BIT_EXACT_WIRE_CLOSURE`

The runtime independently fetched prospective policy preregistration commit
`182459eb4d5eb422a6936b7744f5730d22a9bb27`, verified that it read no formal
outcome, then extended the deterministic verifier and ran a new 2,400-tick
invocation. The formal selected 512000 cells pass every frozen semantic and
native-resolution gate:

```text
DIRECT_SAME_INPUT_MAX: 4.76837158203125e-7 <= 1e-6
SELECTED_RECURSIVE_NORMALIZED_MAX_RECORD_ONLY: 2.384185791015625e-6
SELECTED_LOGICAL_TARGET_MAX_RAD: 5.960464477539062e-7
SELECTED_P30_MAX_RAD: 5.602507320290329e-7
FROZEN_HALF_STS_LSB_RAD: 0.0007669903939428206
SELECTED_RAW_STS_MAX_COUNT_DIFFERENCE: 0
SELECTED_RAW_STS_MISMATCH_WORDS: 0 / 16800
CLASSIFICATIONS_UNCHANGED: true
DECISION: PASS_RECURSIVE_BIT_EXACT_WIRE_CLOSURE
```

The exact physical-offset snapshot, runtime bus conversion, runtime constants,
policy package, selected graph, P30 fit, reference table, and all golden packs
are hash-bound in the result. The 1024000 sibling remains non-gating.

Policy agent: after the runtime commit is pushed, independently fetch and run
`tools/verify_winner_v2_handoff.py` against corrected package commit
`e63226e`, confirm the reduced JSON and artifact hash, and return the reviewed
decision. This pass closes neither powered-off COM nor policy robot clearance.
The same frozen metric must later pass on X5 CPU with no servo access before
any Gate 5 launcher can be reviewed.
