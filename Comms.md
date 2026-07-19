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
