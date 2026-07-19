# Automatic Configuration Support

Status: `OFFLINE_VALIDATOR_PASS — PHYSICAL_PROFILE_NOT_RUN`

- Offline implementation: `src/open_duck_x5/configuration_support.py`
- CLI: `validate_configuration_support`
- Test population: synthetic automatic profiles and policy envelopes only
- Manual mass/COM/inertia inputs accepted: no
- Physical excitation collector: `NOT_RUN`
- Robot/RDK-X5 access: no
- Servo bus access: no
- Torque: no
- Motion: no
- Policy inference: no
- Robot clearance: false
- Gate 5: `NOT_RUN`

The validator requires a policy-side robustness envelope and a machine-collected
supported-excitation profile. It cannot turn a static measurement packet into
clearance and it cannot authorize motion. The physical collection sequence
remains subject to separate implementation review and explicit motion
authorization.
