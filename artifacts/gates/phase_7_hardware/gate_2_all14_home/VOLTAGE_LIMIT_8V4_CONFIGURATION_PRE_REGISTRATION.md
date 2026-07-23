# All-14 maximum-voltage alarm 8.4 V configuration pre-registration

Status: `RUN_HALTED_PARTIAL_RECOVERY_NOT_RUN`

Rob identified the installed servos as the 7.4 V STS3215 variant, supplied a
maximum rating of 8.4 V, requested that the voltage alarms be set accordingly,
and confirmed immediately before development that the robot is on its stand.
The manufacturer's STS3215 product manual independently lists an operating
range of 6-8.4 V. This operation changes only maximum-input-voltage register 14
from raw 80 (8.0 V) to raw 84 (8.4 V). Minimum-input-voltage register 15 remains
raw 40 (4.0 V). This configuration operation cannot advance Gate 2.

Authoritative manufacturer source:

`https://www.feetechrc.com/Data/feetechrc/upload/file/20230218/%E4%BA%A7%E5%93%81%E6%89%8B%E5%86%8C20230217.pdf`

## Frozen safety scope

- direct X5 UART1 `/dev/ttyS1`, 1,000,000 baud;
- hardware and supported/benched assertions plus the dedicated
  `--confirm-max-voltage-8v4` acknowledgement are mandatory;
- issue all-14 torque off before any register read or write and again on
  every exit path;
- never issue torque enable, goal position, gain, ID, baud, offset, or policy
  commands;
- preserve the physical read/update order ending `14,13`;
- preflight all 14 limits before the first EEPROM write;
- accept only a uniform raw `80,40` starting state, or a uniform already-set
  raw `84,40` state; any other or mixed state halts with zero EEPROM writes;
- update servo 20 first as the canary: unlock register 55, write only register
  14 raw 84, read back registers 14-15, relock register 55, verify the lock, and
  read present-voltage register 62 with raw device status;
- if the canary voltage-alarm bit remains asserted, halt before changing the
  remaining 13 units;
- after a clean canary, repeat the same individually verified transaction for
  each remaining servo, then read all 14 limits and voltage/status values;
- maintain an append-only, fsync'd JSONL journal so a power loss cannot hide a
  partial update.

## Failure behavior

Any timeout, partial response, CRC failure, unexpected ID, I/O error,
unexpected preflight value, failed readback, failed relock, or persistent
canary alarm halts the sequence. The tool attempts to relock every servo it
knows it unlocked and issues final all-14 torque off. It does not automatically
write 8.0 V back: fail-closed relock plus a recorded partial state avoids extra
EEPROM writes and preserves the requested in-range 8.4 V value for review.

The operation is complete only when all 14 units read raw `84,40`, every lock
reads raw 1 immediately after its update, every final voltage status has bit 0
clear, all known unlocked units are relocked, and final torque off returns
`ok`. Device-status bits other than voltage remain visible and are not masked.

## Reviewed invocation

After tests, artifact hashes, commit, push, exact-source deployment, and a final
read-only check that no process owns `/dev/ttyS1`:

```bash
configure_servo_voltage_limits --bus serial --device /dev/ttyS1 \
  --repository-commit <exact-40-hex-commit> \
  --timeout-ms 10 \
  --hardware-authorized --suspended-or-benched \
  --confirm-max-voltage-8v4 \
  --output /home/sunrise/duck-evidence/voltage-limit-8v4/result.json \
  --journal /home/sunrise/duck-evidence/voltage-limit-8v4/journal.jsonl
```

No timing probe, torque-enabled check, home hold, or policy run follows
automatically. The result must be copied back, reviewed, and hashed first.

The exact run from commit `ce161b57cd3fb7d393cfcf175ba70b2f74fa10bb`
halted after IDs 20-22 accepted raw 84. See
`voltage_limit_8v4_partial/RESULT.md`. The uniform-preflight rule in this
document governed that first run and is not retroactively changed. Recovery of
the measured mixed state is separately frozen in
`VOLTAGE_LIMIT_8V4_RECOVERY_PRE_REGISTRATION.md`.
