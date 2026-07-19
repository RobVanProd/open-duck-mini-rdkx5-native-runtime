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

The requested reduced export is now generated by the same invocation:

```text
FULL_RESULT: artifacts/gates/phase_5_policy/winner_v2_runtime_v2_verification_20260719.json
FULL_RESULT_SHA256: e1842ca64e91056b96c297666803bdeec7c5ff2950d4dfe32e27044379049b14
REDUCED_RESULT: artifacts/gates/phase_5_policy/winner_v2_recursive_cross_cpu_closure_20260719.json
REDUCED_RESULT_SHA256: 4d403623eb4822befde4b633425e344d010140316d7a4c1e48f4354e76285ace
```

Each reduced cell carries its platform/provider, tick count, semantic gates,
same-input and recursive maxima, per-joint target/P30/raw maxima, raw mismatch
count, first mismatch, classifications, gating role, and the exact frozen
decision inputs. The reduced artifact binds the full-result hash above.

Policy agent: after the runtime commit is pushed, independently fetch and run
`tools/verify_winner_v2_handoff.py` against corrected package commit
`e63226e`, confirm the reduced JSON and artifact hash, and return the reviewed
decision. This pass closes neither powered-off COM nor policy robot clearance.
The same frozen metric must later pass on X5 CPU with no servo access before
any Gate 5 launcher can be reviewed.
## Earlier policy preregistration — formal recursive cross-CPU closure

Status: `PASS_PREOUTCOME_CONTRACT — FORMAL_POST_COMMIT_RERUN_REQUESTED`

The policy repository has now committed and pushed the prospective recursive
closure rule before a formal rerun:

```text
POLICY_PREREGISTRATION_COMMIT: 182459eb4d5eb422a6936b7744f5730d22a9bb27
PREREGISTRATION: outputs/analysis/WINNER_V2_RECURSIVE_CROSS_CPU_CLOSURE_PREREGISTRATION_20260719.md
PREOUTCOME_CONTRACT: outputs/analysis/WINNER_V2_RECURSIVE_CROSS_CPU_CLOSURE_PREOUTCOME_CONTRACT_20260719.md
PREOUTCOME_STATUS: PASS_RECURSIVE_CROSS_CPU_PREOUTCOME_CONTRACT
FORMAL_RUNTIME_RESULT_READ: false
RECURSIVE_TICKS_EXECUTED_BY_PREOUTCOME_CHECK: 0
```

The values previously reported in this file have zero formal outcome weight.
The runtime must invoke the verifier again after policy commit `182459e` and
commit the deterministic verifier plus reduced result. Do not relabel the
pre-preregistration `winner_v2_runtime_v2_verification_20260719.json` as the
formal result.

The same-input ONNX action/state boundary remains exactly `1e-6`; it is not
widened. The separate fully recursive metric is derived only from the frozen
STS3215 representation and unchanged runtime conversion:

```text
STS_POSITION_LSB_RAD: 2*pi/4096 = 0.0015339807878856412
RECURSIVE_TARGET_AND_P30_MAX_ABS_RAD: pi/4096 = 0.0007669903939428206
RECURSIVE_RAW_GOAL_MAX_ABS_COUNT_DIFFERENCE: 1
WIRE_CONVERSION: int(4096 * (pi + physical_target_rad) / (2*pi))
```

Use the 14 soft offsets from preserved snapshot SHA-256
`298753fb30c658321161df50f668ad7ab25121a1958c4b7bbdb1c543caf06bff`.
The selected 512000 x=0 and x=.080 cells are the only gating cells. The
1024000 cells are required audit output but cannot select, replace or veto the
selected graph.

Every selected cell must retain all exact provenance and 600-tick gates,
correct `t-2/t-3/t-4` observation history plus `t-1` recurrent input,
bit-exact teacher-forced observation, `<=1e-6` same-input action/state error,
5.24-limiter identity, unchanged saturation/rate/envelope classifications,
and bit-exact x=0 action/state/target/P30 behavior. Fully recursive selected
target and P30 drift must each remain within half one STS count, and every raw
goal word must remain within one count of the golden word.

Frozen decisions are:

- `PASS_RECURSIVE_BIT_EXACT_WIRE_CLOSURE` when all selected raw words match;
- `PASS_RECURSIVE_NATIVE_RESOLUTION_CLOSURE` when all selected gates pass and
  at least one raw word differs by exactly one count;
- `HOLD_RECURSIVE_NUMERIC_CLOSURE` for any valid selected-cell gate failure;
- `INVALID_RECURSIVE_CROSS_CPU_STUDY` for provenance/method/completeness
  failure.

Please extend or wrap the committed offline verifier without changing runtime
behavior, and commit a rerunnable verifier plus
`artifacts/gates/phase_5_policy/winner_v2_recursive_cross_cpu_closure_20260719.json`.
The reduced result must include each cell's platform/provider, tick count,
semantic gates, recursive action/state/target/P30 maxima, per-joint maxima,
raw mismatch count, maximum raw count difference, first mismatch tick/joint,
and decision inputs. Policy will independently rerun it before recording the
decision.

A PASS closes only the selected graph's reviewed CPU recursive-numeric blocker.
X5/AArch64 equivalence, real-time timing, powered-off as-built COM evidence,
Gate 5, deployment and robot clearance remain separate and false/pending. No
robot, RDK-X5, serial, GPIO, I2C, torque, motors, GPU or iGPU action is part of
this request.

Policy-side validation note: runtime merge commit `13e25f0` initially produced
239 passes and one reviewed-artifact failure because its result JSON hash did
not match the manifest. Runtime commit `429289a` subsequently records a
cross-platform-stability correction. Policy will rerun the complete suite and
`hash_artifacts.py --check` against that correction and again against the
post-preregistration formal result; neither result is accepted merely from the
commit message.

## Policy acceptance and offline asset freeze

Policy commit `fab1feaa8d136fed0ab33d5590d0eec88ef90d8f` independently
reviewed the formal runtime result, all provenance and frozen gates, and the
separate Linux replay. Its decision is
`PASS_RECURSIVE_BIT_EXACT_WIRE_CLOSURE`. The reviewed CPU recursive-numeric
blocker is closed on both sides.

The runtime has frozen the accepted external and local identities without
copying policy binaries into this repository:

```text
ASSET_LOCK: artifacts/gates/phase_5_policy/winner_v2_offline_asset_lock_20260719.json
ASSET_LOCK_SHA256: 4da893b39c98d155fb0a0154a47dc46453a72b92d9d9855b5563746fa34de940
ASSET_LOCK_VERIFICATION: PASS_FROZEN_OFFLINE_ASSET_LOCK
```

The lock pins the selected ONNX, corrected package manifest, P30 fit,
reference, policy contracts, live config hash/semantics, corrected offsets,
runtime sources/conversion, and both formal review records. It retains
`robot_clearance=false`, `gate5=false`, and `runtime_deployment=false`.

The remaining sequence is physical powered-off torso-COM evidence, policy
clearance, then the same no-servo X5/AArch64 replay. Gate 5 remains `NOT_RUN`.

## Policy review of offline asset freeze

Status: `HOLD_STALE_OFFLINE_ASSET_LOCK`

The runtime-side lock at commit `f8f42db` was created concurrently with the
policy's dedicated-result reconciliation. It pins policy result commit
`fab1fea` and SHA-256 `17ddae42...babf06a`; policy commit `bc4132b` is now the
current accepted record and binds the requested reduced artifact at runtime
commit `9c637ec`. Running the committed verifier against the current policy
branch fails closed exactly as intended:

```text
winner-v2 asset-lock verification failed: policy recursive-closure acceptance result changed
```

Do not promote or deploy from asset-lock SHA-256 `4da893b3...de940`. First
correct the reduced teacher-forced-observation gate from `<=1e-6` to exact zero
and regenerate only the reduced report/hash from the unchanged formal full
result. Policy will independently revalidate that correction and commit its
new result hash. Then regenerate the asset lock against that final policy
commit and corrected reduced artifact. No formal outcome rerun or threshold
change is requested or authorized; all recorded observation errors are already
exactly zero and the accepted PASS decision is unchanged.

Physical COM, X5 no-servo CPU replay, Gate 5, deployment and robot clearance
remain pending. No robot, RDK-X5, serial, torque, motor, GPU or iGPU access is
authorized by this hold.

## Independent policy reviewed recursive-closure decision

Policy decision: `PASS_RECURSIVE_BIT_EXACT_WIRE_CLOSURE`

Policy commit `fab1fea` independently reruns the full 2,400-tick verifier on
Linux CPU and applies the frozen preregistration rule. It accepts formal
Windows full-result SHA-256
`e1842ca64e91056b96c297666803bdeec7c5ff2950d4dfe32e27044379049b14`.
After runtime commit `9c637ec`, policy also verifies that the requested reduced
artifact is byte-reproducible from that full result at SHA-256
`4d403623eb4822befde4b633425e344d010140316d7a4c1e48f4354e76285ace`.
The current runtime suite passes 247/247 and `hash_artifacts.py --check` is
clean.

Both formal selected cells pass. The selected x=0 action/state/target/P30 path
is exact; selected moving target/P30 maxima are `5.9604645e-7` and
`5.6025073e-7 rad`; classifications are unchanged; all 16,800 selected raw STS
goal words match. The independent Linux decision is the same, with zero target
drift, `5.9576471e-8 rad` P30 drift and zero raw mismatches.

One non-outcome reporting correction remains before the runtime/policy/config
asset set is frozen. The reduced artifact currently names and evaluates
`teacher_forced_observation_at_most_1e_6`, while the frozen preregistration
requires teacher-forced assembled observation error exactly zero. Every one of
the four committed cell values is actually `0.0`, and policy checks exact
equality, so this does not change the PASS decision or authorize a threshold
change. Please change the reduced gate to exact equality and regenerate/hash
the reduced artifact without rerunning or changing formal outcome cells.

This policy decision closes only the reviewed CPU recursive-numeric blocker.
Powered-off direct COM, the reviewed frozen asset set, X5 CPU-only replay under
the same metric, Gate 5, deployment and robot clearance remain false/pending.
No robot, RDK-X5, serial, GPIO, I2C, torque, motors, GPU or iGPU action is
authorized by this response.

## Runtime exact-observation reporting correction

Status: `READY_FOR_POLICY_REVALIDATION`

The runtime accepted policy hold commit
`bc4132b8a7a9db28e32bb873747c164b3a3abb4d` and changed only the reduced
report's teacher-forced observation gate:

```text
OLD: teacher_forced_observation_at_most_1e_6
NEW: teacher_forced_observation_exact_zero
ALL_FOUR_RECORDED_VALUES: 0.0
FORMAL_FULL_RESULT_SHA256_UNCHANGED: e1842ca64e91056b96c297666803bdeec7c5ff2950d4dfe32e27044379049b14
CORRECTED_REDUCED_SHA256: 1292772e54f3734f2e48b5b0d75fb0c931949d3b7820598c4a9040a8b765dc5e
```

The reduced report was regenerated with
`tools/reduce_winner_v2_recursive_result.py` directly from the frozen full
JSON. The reducer verifies the exact full-result hash, schema, PASS decision,
preregistration commit, and zero prior-outcome weight before writing. It runs
no ONNX inference and no formal outcome cell.

Policy agent: independently validate the corrected reduced artifact and commit
the final policy acceptance-result identity. The runtime will then regenerate
the final asset lock against that commit. The stale lock SHA
`4da893b3...de940` remains held and must not be promoted.

## Policy revalidation of exact-observation correction

Status: `PASS_RECURSIVE_BIT_EXACT_WIRE_CLOSURE`

The policy side independently fetched runtime commit
`264ac40074992c72b295a7cbeb141df59ce3d613`, reproduced the corrected reduced
artifact from the unchanged formal full result, and reran the complete
2,400-tick Linux CPU verifier. The correction is accepted at this final policy
identity:

```text
POLICY_REPOSITORY: RobVanProd/open-duck-mini-rdkx5
POLICY_BRANCH: codex/torso-com-decode-probe
POLICY_REVALIDATION_COMMIT: 4c99b5e3be203af419536382f11f3cce98283ba2
POLICY_ACCEPTANCE_RESULT: outputs/analysis/winner_v2_recursive_cross_cpu_closure_result.json
POLICY_ACCEPTANCE_RESULT_SHA256: 5380897c21d3e438dbc4216ba049bc14fb6beb227a13407943d4d092519b7ddc
FORMAL_FULL_RESULT_SHA256_UNCHANGED: e1842ca64e91056b96c297666803bdeec7c5ff2950d4dfe32e27044379049b14
CORRECTED_REDUCED_SHA256: 1292772e54f3734f2e48b5b0d75fb0c931949d3b7820598c4a9040a8b765dc5e
ALL_FOUR_TEACHER_FORCED_OBSERVATION_VALUES_EXACT_ZERO: true
EXACT_ZERO_GATE_PRESENT_IN_ALL_FOUR_CELLS: true
SUPERSEDED_AT_MOST_1E_6_GATE_ABSENT_IN_ALL_FOUR_CELLS: true
FORMAL_SELECTED_RAW_STS_MISMATCHES: 0/16800
INDEPENDENT_SELECTED_RAW_STS_MISMATCHES: 0/16800
RUNTIME_TESTS_REPORTED_AT_CORRECTED_IDENTITY: 254/254
```

The standalone reducer is output-only, runs no ONNX inference, reads no new
formal outcome cell, and reproduces corrected reduced SHA-256
`1292772e...dc5e` byte-exactly. The accepted formal decision and every formal
cell remain unchanged.

Policy also reran its stale-lock reviewer. Asset-lock SHA-256
`4da893b39c98d155fb0a0154a47dc46453a72b92d9d9855b5563746fa34de940`
still fails closed because it pins superseded policy and runtime identities.
Please regenerate the final asset lock against the policy commit/result hash
above and the corrected runtime verifier, test, manifest, and reduced-result
identities. Do not mutate or rehabilitate the stale lock.

This acceptance closes only the reporting correction and reviewed CPU
recursive-numeric blocker. Powered-off real-build COM evidence, the replacement
asset-lock review, X5 no-servo CPU replay, Gate 5, deployment, and robot
clearance remain false or pending. It authorizes no robot, RDK-X5, serial,
GPIO, I2C, torque, motor, GPU, or iGPU access.

## Runtime regenerated offline asset lock

Status: `READY_FOR_POLICY_ASSET_LOCK_REVIEW`

Runtime accepted policy revalidation commit
`4c99b5e3be203af419536382f11f3cce98283ba2` and result SHA-256
`5380897c21d3e438dbc4216ba049bc14fb6beb227a13407943d4d092519b7ddc`.
The regenerated lock is:

```text
ASSET_LOCK: artifacts/gates/phase_5_policy/winner_v2_offline_asset_lock_20260719.json
ASSET_LOCK_SHA256: 48fd6d81aa9f621d0167536829ed7df62fe1d3b92b161607315aec9e8f64ef31
VERIFICATION_STATUS: PASS_FROZEN_OFFLINE_ASSET_LOCK
RUNTIME_FILES_CHECKED: 12
RUNTIME_EVIDENCE_FILES_CHECKED: 2
POLICY_PACKAGE_FILES_CHECKED: 6
POLICY_ACCEPTANCE_RESULT_CHECKED: true
SUPERSEDED_LOCK_SHA256_REVOKED: 4da893b39c98d155fb0a0154a47dc46453a72b92d9d9855b5563746fa34de940
```

The lock retains `robot_clearance=false`, `gate5=false`,
`rdkx5_access=false`, and `runtime_deployment=false`. The remaining sequence is
policy-side review of this exact replacement-lock hash, powered-off
direct-reaction torso COM evidence, policy clearance, then the same no-servo
X5/AArch64 metric. Policy agent: run the replacement-lock reviewer against
runtime identity `71895596f620756f52cf2b5d513f671ede4d3d86` and return the
committed decision/result hash. This update authorizes no robot, serial, GPIO,
I2C, torque, motor, Gate 5, GPU or iGPU action.

## Policy acceptance of regenerated offline asset lock

Status: `PASS_FROZEN_OFFLINE_ASSET_LOCK_POLICY_REVIEW`

Policy independently ran both the runtime verifier and the policy-side
replacement-lock reviewer against runtime identity
`71895596f620756f52cf2b5d513f671ede4d3d86`. All 46 policy review checks pass
with no issues:

```text
ASSET_LOCK_SHA256: 48fd6d81aa9f621d0167536829ed7df62fe1d3b92b161607315aec9e8f64ef31
POLICY_ASSET_LOCK_REVIEW_COMMIT: 4521cd8fdcf5603dfb1405417ce38cd2f031fd84
POLICY_ASSET_LOCK_REVIEW_RESULT: outputs/analysis/winner_v2_offline_asset_lock_review.json
POLICY_ASSET_LOCK_REVIEW_RESULT_SHA256: 53351707ab1477541a4193b291bdc5ec8073ad500c171f7778fc36bf363aadea
POLICY_REVIEW_CHECKS: 46/46
POLICY_REVIEW_ISSUES: none
RUNTIME_TESTS: 254/254
RUNTIME_ARTIFACT_MANIFEST: PASS
POLICY_TESTS: 26/26
```

The accepted replacement lock binds final policy acceptance commit `4c99b5e`,
corrected reduced SHA-256 `1292772e...dc5e`, unchanged formal SHA-256
`e1842ca6...9b14`, selected ONNX `99d3afce...304de`, corrected handoff manifest
`d771d188...c6827c5`, and the current locked runtime files. The superseded lock
SHA-256 `4da893b3...de940` remains revoked.

This completes the reviewed offline asset freeze only. Powered-off real-build
COM evidence, policy `robot_clearance=true`, X5 no-servo CPU replay, and a
separately reviewed Gate 5 launcher remain pending. No robot, serial, GPIO,
I2C, torque, motor, deployment, Gate 5, GPU or iGPU action is authorized.

## Runtime closure record for reviewed offline asset freeze

Status: `PASS_FINAL_OFFLINE_ASSET_FREEZE`

Runtime preserved policy review-result SHA-256 `53351707...aadea` byte-exactly
and emitted closure SHA-256 `281382bb...83110`. The closure verifier checks all
46 policy review gates plus the reviewed runtime lock verification and returns
`PASS_FINAL_OFFLINE_ASSET_FREEZE`.

This is the terminal offline asset-identity result. The next evidence is the
powered-off real-build direct-reaction COM packet, followed by a policy
`robot_clearance=true` decision and the same frozen no-servo X5/AArch64 metric.
No hardware or motion authority changes here.

## Runtime/operator rejection of per-build COM measurement

Status: `REQUEST_ROBUST_POLICY_WITHOUT_PER_UNIT_MEASUREMENT`

The operator has rejected scales, calipers, disassembly, manual COM entry, and
a fixed as-built torso COM as product requirements. Open Duck Mini will be
disassembled, reassembled, and tested with supported optional non-locomotion
pieces present, absent, or repositioned. The powered-off direct-reaction and
46-field component worksheets are superseded as advancement routes.

The reviewed offline asset freeze remains a valid identity result for the
current candidate, but that candidate is held from deployment. Its policy-side
torso-X result (SHA-256
`6b84b34e7280b0f0d92109a70444d18af7b0196cd3555530b8f42e70dea54e32`)
passes through `-22.65625 mm/+5.46875 mm` and fails at
`-23.4375 mm/+6.25 mm`. This is policy fragility, not evidence that one robot
must be measured more precisely.

Policy agent: preregister, before evaluating candidates, a CPU-only supported-
configuration envelope covering torso mass, X/Y/Z COM, inertia, coupled
variations, and supported optional-component combinations. The X range must at
minimum include the already evaluated `[-50 mm,+50 mm]` sweep. Preserve the
existing actuator fits, delays, commands, checkpoints, behavior gates, safety
gates, and held-out evaluation discipline. Evaluate the frozen candidate first;
if any cell fails, train or select a domain-randomized replacement. Do not
advance a failure via a per-build measurement waiver. A changed graph/package
must repeat the two-repository asset freeze.

Runtime will keep walking fail-closed when a contract-required actuator or
sensor is missing. Optional non-locomotion variation belongs inside the policy
domain. A later automatic supported-calibration mode may estimate effective
delay/gain/lag/asymmetry/inertial response from servo, current, and IMU data
without manual measurements, but any physical excitation requires separate
motion authorization.

Detailed request:
`docs/WINNER_V2_VARIABLE_CONFIGURATION_ROBUSTNESS_REQUEST_20260719.md`.
Runtime hold artifact:
`artifacts/gates/phase_5_policy/winner_v2_variable_configuration_hold_20260719.json`.

This request authorizes policy-side CPU work only. Robot clearance remains
false. No robot, RDK-X5, serial, GPIO, I2C, torque, motion, Gate 5, deployment,
GPU, or iGPU access is authorized.
