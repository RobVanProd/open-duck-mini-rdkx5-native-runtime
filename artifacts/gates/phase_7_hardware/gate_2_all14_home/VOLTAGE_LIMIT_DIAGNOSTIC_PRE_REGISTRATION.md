# All-14 model and voltage-limit diagnostic pre-registration

Status: `AUTHORIZED_NOT_RUN`

Rob authorized autonomous work while motors remain de-energized and explicitly
authorized a torque-off all-14 read of model/version registers 3-4 and
voltage-limit registers 14-15. No writes, torque enable, or motion are
authorized. This diagnostic cannot advance Gate 2.

## Frozen transaction scope

- establish all-14 torque off before any read;
- `/dev/ttyACM0`, 1,000,000 baud, reviewed physical order ending `14,13`;
- per servo, read address 3 length 2, then address 14 length 2;
- preserve payload and raw device status from valid device-error replies;
- scale addresses 14 and 15 at 0.1 V/count;
- send final all-14 torque off and close the device;
- zero torque-enable, goal-position, gain, offset, EEPROM, and configuration
  writes;
- no policy or motion command.

## Stop and evidence rules

Initial torque-off failure blocks all reads. Two consecutive timeout, CRC,
partial, unexpected-ID, or I/O failures halt the probe. A valid status `0x01`
packet remains classified as `device`, not `ok`; its two data bytes may appear
only in diagnostic evidence. Final torque off is mandatory.

The JSON must bind the exact source commit and authorization assertions and
record both fixed transactions per servo, raw model bytes/value, raw/scaled
maximum and minimum voltage limits, device status, response length, and
round-trip time. It must explicitly record zero EEPROM writes.

Planned invocation after offline validation and exact-source deployment:

```bash
probe_servo_voltage_limits --bus serial --device /dev/ttyACM0 \
  --repository-commit <exact-40-hex-commit> \
  --watchdog-failures 2 \
  --hardware-authorized --suspended-or-benched \
  --output /home/sunrise/duck-evidence/voltage-limits-all14/result.json
```
