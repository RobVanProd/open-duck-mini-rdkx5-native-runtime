# All-14 present-voltage diagnostic pre-registration

Status: `AUTHORIZED_NOT_RUN`

Rob explicitly authorized one torque-off, all-14 present-voltage telemetry read
while the robot is suspended/benched. Torque enable and motion are not
authorized. This is a diagnostic of the repeated all-servo status `0x01`; it is
not Gate 2 and cannot advance a hardware gate.

## Frozen scope

- establish all-14 torque off before any read;
- use `/dev/ttyACM0` at `1,000,000` baud;
- read only STS register `62`, length `1`, from all 14 IDs;
- use the reviewed physical read order ending `14,13`;
- interpret the returned byte as `0.1 V/count`;
- preserve the response device-status byte even when it is nonzero;
- send a second all-14 torque-off packet during cleanup;
- write no torque-enable packet, goal position, gain, offset, or EEPROM value;
- run no policy and make no motion request.

The diagnostic-only reader may expose parameters from a valid device-error
packet in its evidence. The normal runtime reader remains unchanged: it rejects
parameters from any nonzero device status and keeps the sample stale.

## Stop rules

- stop before reading if initial torque-off cannot be written;
- halt after two consecutive timeout, CRC, partial, unexpected-ID, or I/O
  failures;
- do not classify a valid framed packet with status `0x01` as transport success
  for the runtime; record it as `device` plus its raw status and voltage byte;
- always attempt final torque off and close the serial device;
- stop on any unexpected motion or operator concern.

## Evidence contract

The JSON artifact must record the exact 40-hex source commit, device, baud,
authorization assertions, initial/final torque-off status, fixed register and
scale, read order, and for every received ID: transport classification, raw
device status, raw voltage byte, scaled voltage, response length, and round-trip
time. A complete capture may diagnose the voltage condition but remains
`NOT_ADVANCED_DIAGNOSTIC_ONLY`.

Planned invocation after offline tests, review, commit, and exact-source deploy:

```bash
probe_servo_voltage --bus serial --device /dev/ttyACM0 \
  --repository-commit <exact-40-hex-commit> \
  --watchdog-failures 2 \
  --hardware-authorized --suspended-or-benched \
  --output /home/sunrise/duck-evidence/voltage-all14/result.json
```
