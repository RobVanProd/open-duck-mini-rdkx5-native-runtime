# All-14 present-voltage diagnostic result

Status: `COMPLETE_ALL14_VOLTAGE_ERROR_CONFIRMED`

The explicitly authorized torque-off diagnostic read STS register 62 from all
14 servos while the robot was suspended/benched. It ran from exact source commit
`ec4ecb779f601ddc2e0ff0d33d87ce9d7c690aa2`; the deployed archive SHA-256 was
`31b44ca162450a08f0fb2a121ad4583c3b328bb8261dd3824f598d487e264bb1`.

## Result

All fourteen one-byte reads completed with valid framing. Every response kept
device status `0x01`, and every servo reported a present voltage between
`8.2 V` and `8.4 V`:

| Servo IDs | Reported voltage |
| --- | --- |
| 20, 21 | 8.3 V |
| 22 | 8.2 V |
| 23 | 8.4 V |
| 24 | 8.3 V |
| 30, 31, 32, 33 | 8.2 V |
| 10, 11 | 8.3 V |
| 12, 14 | 8.2 V |
| 13 | 8.3 V |

Minimum/mean/maximum was `8.2 / 8.257 / 8.4 V`. The complete JSON artifact
SHA-256 is
`ed749b2cf1369ef104c5cf0e94ef548453ada4be597693083e3f89a3b2fcd179`.

## Interpretation boundary

This rules out a missing servo power rail and strongly rejects a baud mismatch:
all IDs returned complete register data at 1 Mbps. The narrow voltage spread
also makes one loose downstream servo connector an insufficient explanation for
the common status bit.

The leading hypothesis is an over-voltage alarm relative to the servos'
configured threshold. STS register 14 is the maximum input-voltage limit and
register 15 is the minimum; both use 0.1 V/count. Some STS3215 memory tables list
an 8.0 V maximum for the 7.4 V variant, which would make the measured 8.2-8.4 V
rail consistently out of range. This is not yet proven because registers 14/15
and the model/version registers were outside this authorization and were not
read.

Do not change the supply voltage or EEPROM limits from this result alone. The
next safe step is a separately authorized torque-off read of model/version
registers 3-4 and voltage-limit registers 14-15. No write is required.

## Safety and gate status

- initial torque-off: `ok`;
- final torque-off: `ok`;
- torque enable requested: `false`;
- goal-position writes: `0`;
- `/dev/ttyACM0` was unowned after the run;
- serial driver remained `cdc_acm`;
- no policy or motion command ran.

This diagnostic does not advance Gate 2. The repeated device-status fault still
blocks the home-pose hold.
