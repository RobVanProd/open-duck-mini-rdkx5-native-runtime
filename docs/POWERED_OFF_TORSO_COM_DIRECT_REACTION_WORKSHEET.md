# Powered-Off Torso COM Direct-Reaction Worksheet

Status: `NOT_SELECTED — PER_BUILD_PRECISION_MEASUREMENT_REJECTED`

This worksheet is preserved as historical evidence only. It is not a current
deployment prerequisite and the operator is not expected to complete it. The
selected route is variable-configuration policy robustness with optional
automatic supported calibration; see
`docs/WINNER_V2_VARIABLE_CONFIGURATION_ROBUSTNESS_REQUEST_20260719.md`.

This is the preferred, policy-contracted route for the remaining real-build
torso center-of-mass evidence. It requires no software, RDK-X5 connection,
serial bus, torque, or motor command. The battery must be electrically
disconnected throughout. Completing it closes only a policy-side input; it
does not authorize Gate 5 or robot motion.

The exact blank packet is
`docs/templates/real_build_torso_com_direct_reaction_template.json`, pinned to
policy commit `e5e9fb8` with SHA-256
`30229a80df15292bc36bcb143c28c46838bf826856ebd00cf156e2654c93af55`.
Do not add, remove, rename, or reinterpret its keys.

## Equipment

- two scales or load cells that can simultaneously support the specimen;
- two narrow, transverse support rails or knife edges;
- a ruler or caliper for support positions;
- an independent whole-specimen scale reading; and
- a camera for immutable evidence.

If two simultaneous load readings cannot be obtained, stop. Do not substitute
one scale moved between supports. Use the component-by-component fallback in
`docs/POWERED_OFF_TORSO_COM_MEASUREMENT_WORKSHEET.md` only as a separately
completed method.

## Exact specimen boundary

Measure the complete torso-fixed deployment assembly as it will be used:
RDK-X5, exact battery arrangement, cooling and mounts, torso wiring, covers,
fasteners, servo-bus/IMU/power hardware, and ballast.

Exclude the articulated children at these modeled boundaries:

- left leg at `left_hip_yaw`;
- right leg at `right_hip_yaw`; and
- head/neck child at `neck_pitch`.

The torso-side portions of servos remain with the torso. No stand, cable, hand,
head, or leg may carry load during a reading. Stop instead of guessing if the
boundary is uncertain.

## Coordinate contract

Use the midpoint of the left and right hip-yaw rotation axes as physical
X = `0`. Physical +X points forward, toward the toes at deterministic home.
The policy calculator maps this datum to simulator `trunk_assembly`
X = `-0.019 m`.

Record a conservative uncertainty for locating that physical midpoint. Do not
enter zero unless a reviewed measurement source proves zero uncertainty.

## Apparatus setup

Place the rearward support at `x_a` and the forward support at `x_b`, both
measured from the hip-axis datum. Their complete uncertainty intervals must be
separated by at least `0.060 m`:

```text
(x_b - support_b_uncertainty) -
(x_a + support_a_uncertainty) >= 0.060 m
```

Both load uncertainties must include scale resolution/calibration and reading
repeatability. Tare the rails/supports before placing the specimen.

| Apparatus field | Reading | Uncertainty | Evidence ID |
| --- | ---: | ---: | --- |
| Datum origin | 0 m | | |
| Rear support `x_a` | | | |
| Forward support `x_b` | | | |
| Scale A | n/a | | |
| Scale B | n/a | | |
| Independent complete-specimen mass | | | |

Use kilograms and metres in JSON. Preserve raw grams and millimetres, plus the
conversion, in the evidence record.

## Three formal trials

Unload and fully replace the torso between trials. Record both reactions
simultaneously only after the specimen is stable and no external load path is
present.

| Trial | Reaction A kg | Reaction B kg | Evidence ID |
| ---: | ---: | ---: | --- |
| 1 | | | |
| 2 | | | |
| 3 | | | |

The independent same-specimen mass interval must overlap each reaction-sum
interval. The three conservative COM intervals must also intersect. The
policy calculator rejects inconsistent mass, insufficient support separation,
nonpositive reaction intervals, or nonoverlapping COM trials; do not tune
uncertainties after seeing a result.

## Evidence checklist

- [ ] Battery and every electrical power source are disconnected.
- [ ] The final torso-fixed deployment configuration is photographed.
- [ ] The isolated specimen and every excluded articulated child are shown.
- [ ] All torso-fixed parts are inventoried exactly once.
- [ ] Both support positions and the +X direction are visible and measured.
- [ ] Scale calibration/resolution and support-position resolution are shown.
- [ ] No stand, cable, hand, head, or leg carries load in any trial.
- [ ] Exactly three unload/reload trials are recorded.
- [ ] The same complete specimen is independently weighed.
- [ ] Every JSON predicate is explicitly `true` only when its evidence exists.
- [ ] All evidence references identify immutable photos/files, not vague prose.
- [ ] The original blank-template keys and provenance remain unchanged.

## Handoff

Fill a copy of the exact JSON template and send the completed JSON plus its
evidence directory to the policy task. The policy repository must run its
frozen evaluator:

```bash
python3 tools/evaluate_real_build_torso_com_direct_reaction.py \
  --input outputs/analysis/real_build_torso_com_direct_reaction_template.json \
  --output outputs/analysis/real_build_torso_com_direct_reaction_result.json
```

Only the policy repository's reviewed decision token can close the physical
COM blocker. Runtime-v2 acceptance, policy robot clearance, the frozen asset
set, and an explicitly authorized Gate 5 remain separate gates.
