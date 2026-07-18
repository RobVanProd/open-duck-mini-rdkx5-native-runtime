# Partial 8.4 V alarm configuration recovery pre-registration

Status: `RUN_HALTED_PARTIAL_FINAL_RECOVERY_NOT_RUN`

The first authorized run halted with the measured state `84,40` on IDs
20-22 and `80,40` on IDs 23 onward. Final torque-off succeeded. ID 22's lock
state was not captured. Rob's request remains to set all installed maximum
alarms to the documented 8.4 V limit while the robot remains on its stand.
This recovery is configuration-only and cannot advance Gate 2.

## Frozen recovery behavior

- require the two hardware assertions and the dedicated 8.4 V EEPROM
  confirmation;
- require an unowned `/dev/ttyS1`, 1,000,000 baud, and initial all-14 torque
  off before reads or writes;
- preflight all 14 maximum/minimum limits in wire order ending `14,13`;
- accept only raw `80,40` or `84,40`; any other value halts before a new limit
  write;
- for every pre-existing `84,40` unit, read register 55. If it is 0, issue only
  a relock write of 1 and read it back; if it is neither 0 nor 1, halt;
- require every pre-existing 8.4 V unit to have lock 1 and a clear voltage bit
  before changing a remaining unit;
- never rewrite register 14 on a unit already at raw 84;
- use the first remaining raw-80 unit (expected ID 23) as the recovery canary;
- for every write, immediately read the affected register. An acknowledgement
  timeout/CRC/partial result may be classified as recovered only if that
  independent read returns the exact requested lock or voltage-limit value;
- otherwise halt, attempt relock for the possibly unlocked servo, audit all
  limits/status values, and issue final all-14 torque off;
- after a clean recovery canary, update only the remaining raw-80 units using
  individual unlock/write/readback/relock/status transactions;
- finish with an all-14 `84,40` and voltage-status audit, final torque off, an
  fsync'd JSONL journal, and source/evidence hashes.

No minimum-voltage, torque-enable, goal-position, ID, baud, gain, offset,
policy, timing-probe, or motion command is allowed. The recovery must use a new
evidence directory and exact new source commit. A completed alarm correction
does not waive the separate `<5 ms` Gate 2 bus-time requirement.
