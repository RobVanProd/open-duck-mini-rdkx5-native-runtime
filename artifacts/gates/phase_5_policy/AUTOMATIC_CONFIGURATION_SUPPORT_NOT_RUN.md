# Automatic Configuration Support

Status: `OFFLINE_EXTRACTION_AND_VALIDATOR_PASS — PHYSICAL_PROFILE_NOT_RUN`

- Offline implementation: `src/open_duck_x5/configuration_support.py`
- Automatic extractor: `src/open_duck_x5/configuration_profile.py`
- Raw schemas: `open_duck_x5.configuration_excitation_metadata.v1` and
  `open_duck_x5.configuration_excitation_tick.v1`
- Generated profile: `open_duck_x5.automatic_configuration_profile.v2`, bound
  to raw trace, metadata, and exact `duck_config.json` SHA-256 identities
- CLI: `validate_configuration_support`
- Test population: synthetic raw excitation traces, generated automatic
  profiles, and policy envelopes only
- Manual mass/COM/inertia inputs accepted: no
- Physical excitation collector: `NOT_RUN`
- Robot/RDK-X5 access: no
- Servo bus access: no
- Torque: no
- Motion: no
- Policy inference: no
- Robot clearance: false
- Gate 5: `NOT_RUN`

The extractor recovers a known injected delay/gain/time constant across all 14
joints. The validator reproduces that profile from all three raw inputs before
the output passes its 73 metric checks. Neither tool can turn a
static measurement packet into clearance or authorize motion. The physical
collection sequence remains subject to separate implementation review and
explicit motion authorization.
