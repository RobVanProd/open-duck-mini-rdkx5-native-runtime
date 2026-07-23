# Power Provenance and Device-Status Reconciliation

## Outcome

The robot's documented power architecture is nominal 7.4 V (2S), not 12.6 V
(3S). The measured 8.2-8.4 V servo rail is consistent with a charged 2S pack.
The persistent servo status byte `0x01` is a real device alarm relative to the
configured 8.0 V maximum, but it is not evidence of a malformed serial reply.

The runtime therefore separates two facts that the earlier parser collapsed:

| Question | Recorded result |
| --- | --- |
| Did a complete, checksum-valid response arrive? | Transport `OK`; payload is fresh |
| Did the servo report an internal alarm? | Preserve the raw device-status byte and count it separately |

Timeout, checksum, and partial-response failures still invalidate the affected
sample. A nonzero device status does not. This distinction is necessary to
measure bus timing honestly without hiding the servo's safety state.

## Build provenance

Frank Fu's [Open Duck Mini article](https://frankfu.blog/openai/understanding-reinforcement-learning-through-openduck/)
points builders to the upstream Open Duck Mini v2 hardware instructions. The
upstream [editable v2 wiring diagram](https://github.com/apirrone/Open_Duck_Mini/blob/v2/docs/open_duck_mini_v2_wiring_diagram.drawio)
labels the battery as two 18650 cells in series, the BMS and main output as
7.4 V, and the motor board input as 7.4 V DC. The Waveshare
[Bus Servo Adapter (A) documentation](https://docs.waveshare.com/Bus_Servo_Adapter_A/FAQ)
also states that the board supports a 2S lithium battery and that output voltage
equals input voltage.

The later user-supplied 3S/12.6 V sketch was a reconstruction, not the build's
source schematic. It must not be used to infer that this robot was wired for a
3S servo rail. The owner independently confirmed that the installed servos are
7.4 V units.

## What the read-only evidence establishes

The preserved torque-off captures establish:

- all 14 servos returned complete framed replies;
- all 14 returned raw status `0x01`;
- present-voltage register 62 reported 8.2-8.4 V;
- configured voltage limits read as 4.0 V minimum and 8.0 V maximum; and
- registers 3-4 returned identical raw bytes `0x03,0x09`.

Registers 3-4 are version fields in this protocol path. Those bytes are retained
as raw evidence; they are not sufficient to claim a particular servo SKU.
The captures prove that the live voltage exceeded the configured 8.0 V threshold
when sampled. They do not prove that the documented 2S architecture is wrong.

## Runtime and gate behavior

- Grouped position/speed and round-robin extended telemetry preserve valid
  payloads even when the status byte is nonzero.
- Per-servo and extended device status are written to JSONL and summarized as
  device-alarm and voltage-alarm reply counts.
- Runtime startup, home movement, and torque-capable probes reject any device
  alarm before torque enable or goal-position writes.
- Torque-off probes may measure transport timing through alarm-bearing replies,
  but `zero_device_alarms=false` prevents a hardware-gate candidate.
- The normal convenience register/ping APIs remain fail-closed; only their
  explicit `*_with_device_status` variants return alarm-bearing diagnostic data.

No EEPROM voltage-limit change, power-wiring change, torque enable, movement, or
policy deployment is authorized by this reconciliation. Gate 2 remains blocked
both by the unresolved device alarm and by the independent measured total-bus
maximum above the preregistered `<5 ms` threshold.

## Subsequent reviewed configuration

After this reconciliation, the owner supplied the installed motor's 8.4 V
upper rating and explicitly authorized a guarded torque-off alarm correction.
The final reviewed run changed only maximum-input-voltage register 14 from raw
80 to 84, retained minimum raw 40, and verified raw `84,40`, device status 0,
and 8.2-8.4 V on all fourteen units. All locks and final torque-off verified;
no torque enable, target, policy, or motion ran. See
`artifacts/gates/phase_7_hardware/gate_2_all14_home/voltage_limit_8v4_complete/RESULT.md`.

This subsequent result clears the device-alarm condition but does not change
the independent failed Gate 2 bus-time measurement.
