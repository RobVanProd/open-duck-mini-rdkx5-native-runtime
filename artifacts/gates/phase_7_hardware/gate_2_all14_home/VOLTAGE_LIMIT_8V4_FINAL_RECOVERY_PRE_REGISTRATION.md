# Final partial 8.4 V alarm recovery pre-registration

Status: `AUTHORIZED_NOT_RUN_OFFLINE_VALIDATION`

The first recovery left a fully measured, safe state: IDs 20, 21, 22, 23, 24,
and 30 are raw `84,40`, lock 1, and voltage-alarm clear; IDs 31, 32, 33, 10,
11, 12, 14, and 13 remain raw `80,40`. Final torque-off was `ok`. Rob's
authorized goal remains an 8.4 V maximum on all installed units while the robot
is on its stand. This operation cannot advance Gate 2.

## Frozen final-recovery behavior

- use an exact new source commit, new evidence directory, unowned
  `/dev/ttyS1`, 1,000,000 baud, the two hardware assertions, and the dedicated
  8.4 V EEPROM confirmation;
- issue initial all-14 torque off before any register operation;
- preflight all 14 limits and accept only raw `80,40` or `84,40`;
- independently require lock 1 and a clear voltage bit on every existing raw-84
  unit before a remaining maximum write; relock a raw-0 lock and verify it, but
  never rewrite an existing raw-84 maximum;
- use ID 31, the first remaining raw-80 unit in the frozen wire order, as the
  final-recovery canary;
- transmit each unlock, maximum, and relock write at most once;
- verify every operation by reading the affected register. A verification read
  may be attempted at most three times, with every failed and successful
  attempt journaled. These are read-only retries; no write is retransmitted;
- an acknowledgement error is recovered only after exact independent readback;
  a wrong value or three failed reads halts, relocks any possibly unlocked unit,
  audits all 14, and issues final torque off;
- after a clean ID-31 canary, update only the seven remaining raw-80 units;
- require final raw `84,40`, voltage bit clear, all known locks 1, final torque
  off `ok`, complete JSON plus fsync'd journal, and source/evidence hashes.

No minimum-limit, torque-enable, goal-position, gain, ID, baud, offset, policy,
timing-probe, or motion command is allowed. A complete configuration remains
separate from the `<5 ms` Gate 2 timing blocker.
