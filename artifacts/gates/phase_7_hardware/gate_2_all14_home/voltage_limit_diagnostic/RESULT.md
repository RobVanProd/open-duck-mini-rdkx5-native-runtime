# All-14 model and voltage-limit diagnostic result

Status: `ROOT_CAUSE_CONFIRMED_SUPPLY_ABOVE_CONFIGURED_MAXIMUM`

The authorized torque-off diagnostic read model/version registers 3-4 and
voltage-limit registers 14-15 from every servo. It ran from exact commit
`c634af78d78d378b396b80dc2dd6ad7cde300477`; the deployed archive SHA-256 was
`2f5cd78ea32822453521e7b89c29c7aaba384b0f9c6f3fbdf2965f4c883fbc65`.

## Uniform all-servo result

All 28 fixed reads completed with valid framing. Every servo reported identical
configuration:

- model/version bytes: `09 03` (`0x0309`, decimal `777`);
- maximum input voltage: raw `80` = `8.0 V`;
- minimum input voltage: raw `40` = `4.0 V`;
- device status during both reads: `0x01`.

The preceding authorized register-62 capture measured the live shared rail at
`8.2-8.4 V` across the same 14 servos. The rail therefore exceeds every servo's
configured maximum by `0.2-0.4 V`. This exactly explains the common voltage
status bit and the new runtime's startup safety halt.

The complete JSON SHA-256 is
`b7746303ad5fc00254abcbf32eeb8c0d0b6cc7f4b39abb37e26c663e3ca314fa`.

## Root-cause boundary

This is not a baud mismatch, USB framing defect, missing rail, single loose
connector, or one misconfigured servo. Fourteen identical model/limit readbacks
and fourteen consistent live-voltage measurements identify a common
power-source-versus-servo-limit mismatch.

Feetech's official 7.4 V STS3215 product material lists a 6-7.4 V operating
range, and its specification describes over-voltage protection for that model:

- https://www.feetechrc.com/74v-19-kgcm-plastic-case-metal-tooth-magnetic-code-double-axis-ttl-series-steering-gear.html
- https://www.feetechrc.com/Data/feetechrc/upload/file/20200611/6372749961523760249976542.pdf

The configured `8.0 V` maximum provides some margin above nominal, but the
measured `8.2-8.4 V` still exceeds the device's own stored limit. The likely
source is an unregulated/fully charged two-cell supply, but the software evidence
does not identify the physical power-source model; that remains an operator
inspection item.

This finding explains the present all-servo `0x01` halt. It does not replace the
earlier timing diagnosis or prove that overvoltage caused every historical
"funky" behavior episode; earlier preflights did not show a persistent
all-servo device error.

## Safety and disposition

- initial torque-off: `ok`;
- final torque-off: `ok`;
- torque enable requested: `false`;
- goal-position writes: `0`;
- EEPROM/configuration writes: `0`;
- no policy or motion command;
- serial device unowned afterward; driver remained `cdc_acm`.

No remote corrective write is authorized or appropriate while the operator is
asleep. Do not raise the EEPROM limit merely to hide the alarm. The next physical
step is to identify the servo power source and provide a supply within the
servo's supported range. After that change, repeat only the torque-off voltage
and status read before reconsidering Gate 2.
