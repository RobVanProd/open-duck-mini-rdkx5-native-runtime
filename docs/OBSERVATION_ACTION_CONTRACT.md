# Frozen Observation and Action Contract

Contract identifier: `open-duck-mini.best-walk.101x14.v1`

Source comparison: preserved board-derived runtime at reference commit `84491f866139b9fd7d681e63da3b6f72bf07b991`, especially `scripts/v2_rl_walk_mujoco.py`, `rustypot_position_hwi.py`, `raw_imu.py`, and `duck_config.py`.

## Joint/action order

| Index | Joint | Servo ID | Home rad |
| ---: | --- | ---: | ---: |
| 0 | left_hip_yaw | 20 | 0.002 |
| 1 | left_hip_roll | 21 | 0.053 |
| 2 | left_hip_pitch | 22 | -0.630 |
| 3 | left_knee | 23 | 1.368 |
| 4 | left_ankle | 24 | -0.784 |
| 5 | neck_pitch | 30 | 0.000 |
| 6 | head_pitch | 31 | 0.000 |
| 7 | head_yaw | 32 | 0.000 |
| 8 | head_roll | 33 | 0.000 |
| 9 | right_hip_yaw | 10 | -0.003 |
| 10 | right_hip_roll | 11 | -0.065 |
| 11 | right_hip_pitch | 12 | 0.635 |
| 12 | right_knee | 13 | 1.379 |
| 13 | right_ankle | 14 | -0.796 |

There are no software direction flips. Soft offsets are physical-servo offsets, applied as:

```text
physical_command_rad = logical_command_rad + joints_offsets[joint]
logical_read_rad = physical_read_rad - joints_offsets[joint]
```

## Observation vector

The ONNX input is float32 with shape `[1, 101]`. Normalization is inside the ONNX graph; Python must not normalize this vector.

| Slice | Count | Field | Exact source and scale |
| --- | ---: | --- | --- |
| `0:3` | 3 | gyro x/y/z | BNO055 gyro, rad/s, no Python scaling |
| `3:6` | 3 | acceleration x/y/z | BNO055 acceleration, m/s^2, no Python scaling |
| `6:13` | 7 | commands | x velocity, y velocity, yaw velocity, neck pitch, head pitch, head yaw, head roll |
| `13:27` | 14 | joint position error | logical present position minus `HOME_RAD`, action order |
| `27:41` | 14 | joint velocity | logical present velocity times `0.05`, action order |
| `41:55` | 14 | previous action | raw normalized ONNX output from one tick ago |
| `55:69` | 14 | action -2 | raw normalized ONNX output from two ticks ago |
| `69:83` | 14 | action -3 | raw normalized ONNX output from three ticks ago |
| `83:97` | 14 | previous motor target | previous absolute logical target after inherited slew limit, optional filter, and head overlay |
| `97:99` | 2 | foot contacts | left, right; raw GPIO false maps to `1.0` contact |
| `99:101` | 2 | gait phase | cosine, sine |

Startup history is three zero action vectors. Startup previous motor target is `HOME_RAD`.

The `83:97` field is the post-slew, post-head-overlay **commanded logical target**. It
is not the measured present position (available separately through the position-error
field), and it must not be treated as equivalent to an actuator-model bridge's
realized/applied state without training-source evidence. A candidate trained with a
different definition is semantically incompatible even if its ONNX shape is `[1,101]`.

Required freshness is intentionally out-of-band. The 101-vector has no spare staleness field; adding one would change the policy contract. If any required servo, IMU, or contact sample is stale, the assembler rejects that tick and the runtime does not infer on a mixed-age or silently reused observation.

## Phase ordering

The preserved real runtime builds the observation with the current phase, then advances phase, then infers using the already-built observation. Training and the MuJoCo inference path were previously audited as advancing phase before observation construction.

This repository preserves deployed runtime ordering until a reviewed golden-vector decision says otherwise:

```text
obs.phase = current phase
advance internal phase for next tick
infer(obs)
```

The period is 27 ticks, derived from the inherited reference motion metadata (`period=0.54`, `fps=50`). Per successful policy tick:

```text
phase_index += 1.0 + phase_frequency_factor_offset
phase = [cos(phase_index / 27 * 2*pi), sin(...)]
```

Controller sprint behavior can temporarily change the base factor; it does not change vector layout or scale.

## Action pipeline

The ONNX output is float32 `[1, 14]`. The deployed interpretation is:

```text
unlimited_target[i] = HOME_RAD[i] + action[i] * 0.25
sent_target[i] = clamp(
    unlimited_target[i],
    previous_target[i] - 5.24 / 50,
    previous_target[i] + 5.24 / 50,
)
sent_target[5:9] += commands[3:7]
physical_target[i] = sent_target[i] + joints_offsets[i]
```

No new action clip or joint-limit clip is added. The 3.75 rad/s envelope monitor is telemetry only: it compares consecutive sent logical targets, records excursions, and does not block or reshape policy output.

## Config contract

- `start_paused`: initial pause state. The runtime provides no force-unpaused bypass.
- `imu_upside_down`: selects the inherited BNO055 axis-remap sign tuple.
- `phase_frequency_factor_offset`: additive phase increment factor.
- `joints_offsets`: mapping of all 14 joint names to soft offsets in radians, applied with the equations above.
- `expression_features`: accepted unchanged for file compatibility; expression devices are outside the deterministic motion hot path.

## Golden verification result and remaining candidate gate

The preserved-runtime comparison now passes against adjacent ticks 0 and 1 from
the corrected-knee suspended capture. `artifacts/contracts/legacy-contract-report.json`
reports zero mismatches and zero maximum absolute difference across all 101
observation elements, all 14 logical sent targets, and all 14 physical targets. The
captured config uses the corrected left-knee soft offset `0.0371` rad.

The preserved runtime's existing `sim2real.telemetry.v1` records contain the
raw ONNX vector and action pipeline. Logging must use
`--telemetry-every-n 1`, because the previous tick's pre-head-overlay target is
required to reconstruct the slew limiter. Extract an adjacent pair and run the
named-field verifier:

```bash
extract_contract_snapshot legacy-telemetry.jsonl --tick <current-tick> \
  --output legacy-contract-snapshot.json
verify_contract_snapshot legacy-contract-snapshot.json \
  --output artifacts/contracts/legacy-contract-report.json
```

The extractor independently checks the ONNX names/dimensions, joint names/IDs,
position slice, velocity scaling, 50 Hz rate, action scale, 5.24 rad/s limiter,
and confirms that the observation phase equals the prior tick's post-advance
phase. It accepts the preserved JSON `null` representation for a disabled optional
filter and rejects any enabled filter because that would be a different action
contract. It also requires `obs[83:97]` to equal the prior sent target. A report
identifies every mismatch by vector index and semantic field name. Any future
mismatch blocks Gate 5.

The golden board comparison does not by itself prove candidate-policy training
semantics. Candidate handoff must additionally establish whether training `obs[83:97]`
used the post-slew commanded target or a bridge-realized state, whether training sampled
phase before or after advance, and whether it used the frozen 5.24 rad/s slew behavior.
