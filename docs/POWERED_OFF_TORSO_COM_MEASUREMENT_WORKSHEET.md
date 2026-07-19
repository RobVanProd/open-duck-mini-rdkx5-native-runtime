# Powered-Off Real-Build Torso COM Measurement Worksheet

Status: `READY_AS_46_FIELD_FALLBACK — DIRECT_REACTION_ROUTE_PREFERRED`

This worksheet converts the policy repository's frozen
`real_build_torso_com_measurement.v2` packet into a physical collection plan.
It does not authorize software, the RDK-X5, serial access, torque or motion.
All measurements are performed with the robot powered off and electrically
disconnected.

The policy repository subsequently contracted and CPU-tested a simpler
two-support direct-reaction measurement of the complete torso-fixed assembly.
Use `docs/POWERED_OFF_TORSO_COM_DIRECT_REACTION_WORKSHEET.md` first. This file
remains the exact fallback for the original 46 missing fields. Do not mix
measurements from the two methods into one result.

## What the 46 fields are

The packet contains six coordinate-contract fields and five fields for each of
eight component groups:

- 6 coordinate fields;
- 8 × (`mass_kg`, `mass_uncertainty_kg`, `x_m`,
  `x_uncertainty_m`, `source`) = 40 component fields;
- total = 46 source-backed fields.

Use the machine-readable blank packet at
`docs/templates/real_build_torso_com_measurement_v2.json`. Do not add, remove
or rename keys.

## Measurement boundary

The inventory must describe the complete physical counterpart of simulator
body `trunk_assembly` in intended deployment configuration:

- include all torso-fixed printed parts, fasteners, RDK-X5 hardware, battery,
  BMS/charger, wiring, thermal stack, mounts, adapters, IMU, bus/power boards,
  covers and ballast;
- exclude articulated child assemblies at the left/right hip-yaw boundaries
  and at the neck-pitch boundary;
- keep any servo portion fixed to the torso on the torso side of that boundary;
- count every physical item exactly once;
- record absent optional covers/ballast as zero mass and zero uncertainty with
  photo evidence; do not leave the row null.

Stop if an item cannot be assigned uniquely, the intended deployment build is
not final, or a cable/fixture/hand carries any load during weighing.

## Recommended datum

Use the midpoint of the left and right hip-yaw rotation axes as the physical
X datum. The policy-side source audit places that datum at X = `-0.019 m` in
the simulator `trunk_assembly` frame. Physical `+X` points forward, toward the
toes at home, so the axis sign is `+1`.

The source evidence currently cited by the policy preregistration is:

- upstream Open Duck Mini v2 URDF commit
  `b23317a485b3cec7d8417f352478778b3475173c`;
- URDF SHA-256
  `a42c5ff3213b4662d81708807d698ab63d4e7432a54b4112728969d45928b54b`;
- simulator XML SHA-256
  `968b18de4e3f55b31252155f52779fa490989f5da92bc9b308e0bb4e81d6bb5c`.

This source record supports the nominal mapping. The physical uncertainty in
locating the two real rotation axes is still a required measured value; do not
enter zero unless a reviewed metrology source proves zero uncertainty.

## Tools and evidence

Use:

- a scale suitable for each component group, with known resolution and a
  documented accuracy or calibration check;
- a ruler or caliper with known resolution;
- a narrow transverse balance edge or two-point fixture for locating each
  group's X center of mass;
- noncompressible shims/fixtures that can be tared or weighed separately;
- a camera and a paper trial sheet.

Create one immutable evidence directory containing:

1. a complete before-measurement build photo from front, rear, left, right and
   top;
2. a photo labeling the hip-axis datum and forward-positive direction;
3. an inventory photo for every component group;
4. every scale reading and balance-position reading;
5. scale/caliper resolution and calibration evidence;
6. the raw worksheet, calculations and completed JSON.

Give each item a stable evidence ID such as `M03_BATTERY_TRIAL_2`. The JSON
`source` and `transform_evidence` fields should cite those IDs or immutable
repository paths, not prose such as “measured.”

## Conservative value and uncertainty rule

For every nonzero group, unload and replace the item for at least three mass
readings and at least three balance-position readings. Preserve every raw
reading.

For a repeated scalar measurement:

1. record the smallest and largest plausible values after including instrument
   resolution/calibration;
2. enter their midpoint as the JSON value;
3. enter half their full span as the uncertainty;
4. enlarge, never shrink, that uncertainty for placement repeatability or an
   uncertain mounting reference.

This is a conservative worksheet rule, not permission to average away spread.
If a component group cannot be balanced separately, use build CAD with
assigned as-built masses or measure a documented combined group and leave no
other row containing the same parts. Nominal web specifications do not replace
as-built mass evidence.

All JSON values use kilograms and metres. Keep raw grams and millimetres in the
evidence, then show the conversion.

## Coordinate-contract fields (1–6)

| # | JSON field | Entry | Evidence / calculation |
|---:|---|---|---|
| 1 | `datum_description` | Midpoint of left/right hip-yaw rotation axes | |
| 2 | `datum_origin_x_in_trunk_assembly_m` | `-0.019` after policy-side source review | |
| 3 | `datum_origin_x_uncertainty_m` | | Physical datum-location uncertainty |
| 4 | `positive_x_description` | Forward/toe direction at home | |
| 5 | `axis_sign_to_trunk_assembly_x` | `1` | |
| 6 | `transform_evidence` | | URDF/XML hashes plus datum photo/drawing |

The common datum uncertainty is entered once in field 3. Do not add it again
to every component's `x_uncertainty_m`.

## Component records (7–46)

For `x_m`, use the signed X coordinate of the group's own center of mass
relative to the physical hip-axis datum: forward is positive, rearward is
negative.

| JSON `id` | mass kg | mass uncertainty kg | X m | X uncertainty m | source/evidence ID |
|---|---:|---:|---:|---:|---|
| `printed_torso_and_fasteners` | | | | | |
| `rdk_x5_board` | | | | | |
| `rdk_x5_thermal_and_mount` | | | | | |
| `rdk_x5_cables_and_adapters` | | | | | |
| `battery_cells_pack` | | | | | |
| `battery_bms_charger_wiring` | | | | | |
| `servo_bus_imu_power_hardware` | | | | | |
| `build_specific_covers_or_ballast` | | | | | |

### Raw trial sheet — copy once per component group

Component ID: ____________________  Evidence ID prefix: ____________________

Installed parts included: _________________________________________________

Installed parts explicitly excluded: ______________________________________

Scale resolution/accuracy: ____________________

| trial | mass raw | balance X raw relative to datum | photo/evidence ID |
|---:|---:|---:|---|
| 1 | | | |
| 2 | | | |
| 3 | | | |

Mass plausible interval: __________ to __________ kg

JSON `mass_kg`: __________ kg

JSON `mass_uncertainty_kg`: ±__________ kg

X plausible interval: __________ to __________ m

JSON `x_m`: __________ m

JSON `x_uncertainty_m`: ±__________ m

## Completion checks

Before sending the packet to the policy task, verify:

- [ ] Robot was powered off and electrically disconnected throughout.
- [ ] The deployed torso-fixed inventory is final and photographed.
- [ ] Both legs and the head/neck child assembly were excluded at the frozen
      joint boundaries.
- [ ] All parts appear in exactly one component row.
- [ ] All 46 fields are non-null.
- [ ] Every numeric value is finite and every uncertainty is nonnegative.
- [ ] All masses are kilograms and all coordinates are metres.
- [ ] Forward values are positive and rearward values are negative.
- [ ] The datum uncertainty is included once, not duplicated per component.
- [ ] Absent covers/ballast are recorded as zero with absence evidence.
- [ ] Every `source` and `transform_evidence` identifier resolves to preserved
      evidence.
- [ ] Raw readings, conversions and uncertainty calculations are retained.

Completing this worksheet does not itself pass the policy-side COM gate. The
policy repository must run its frozen calculator and return one of its reviewed
decision tokens. Runtime-v2 acceptance, policy robot clearance and Gate 5
remain separate decisions.
