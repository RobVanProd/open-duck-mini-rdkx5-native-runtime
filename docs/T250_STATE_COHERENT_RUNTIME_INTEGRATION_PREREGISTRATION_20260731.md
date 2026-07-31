# T250 state-coherent runtime integration preregistration

Status: `PREREGISTERED_OFFLINE_RUNTIME_INTEGRATION`

The policy repository's T250 audit passed all `320/320` offline cells and
earned only a versioned runtime integration. This task creates a new,
default-disabled 115-D path. It does not edit or reinterpret the frozen 101-D
runtime, and it does not alter the older Winner-v12 host.

The versioned path must reproduce the evaluated transition exactly:

- 250 confirmed calibration ticks;
- zero home-return ticks;
- the post-slew logical target drives the fixed P30 observer;
- physical state, observer state, and calibration action history survive the
  handoff;
- locomotion receives the calibrator's final `previous_action_out`, zero
  `h_in`, and immutable final `h_out` as `calibration_context`;
- the first locomotion observation is phase `[1, 0]` and contains the final
  three calibration actions in the visible history slots; and
- all graph, action-history, target, observer, and phase state commits only
  after a literal `True` send confirmation.

The new module remains disconnected from the production CLI and imports no
serial, GPIO, I2C, torque, or robot code. A pass earns only a separately frozen
no-motion X5 CPU-preflight preregistration. It does not authorize asset staging,
Gate 5, or robot motion.

Machine-readable contract:
`artifacts/gates/phase_5_policy/t250_state_coherent_runtime_integration_preregistration_20260731.json`
