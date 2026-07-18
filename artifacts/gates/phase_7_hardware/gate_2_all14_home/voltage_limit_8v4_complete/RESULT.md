# All-14 8.4 V maximum-voltage alarm configuration result

Status: `COMPLETE_REVIEWED_CONFIGURATION_ONLY`

The final torque-off recovery ran on X5 UART1 `/dev/ttyS1` from exact commit
`da28f5325d9fc5ed55233a95e5e24fe5416e60c3`. Its git archive reproduced
SHA-256
`4824de3166e45cd1b6eaad54396396b94fe821a218e50dfbf9aea1f233c39cd3`
on the workstation and X5. The robot remained on its stand and the UART was
unowned immediately before and after the run.

Preflight found IDs 20, 21, 22, 23, 24, and 30 already at raw maximum/minimum
`84,40`. The tool independently verified lock 1 and a clear voltage bit on all
six and did not rewrite their maximum limits. ID 31 was the recovery canary.
The run updated only IDs 31, 32, 33, 10, 11, 12, 14, and 13.

IDs 32, 14, and 13 each lost their maximum-write acknowledgement and their
first independent limit read timed out. In every case the second read returned
exact `84,40`; the journal therefore classified the acknowledgement as
recovered by readback. No unlock, maximum, or relock write was retransmitted.

The final all-14 audit returned:

- maximum/minimum raw `84,40` (8.4/4.0 V) on every servo;
- raw device status 0 and voltage-alarm false on every servo;
- present-voltage raw 82-84 (8.2-8.4 V);
- all known unlocked servos relocked;
- initial and final all-servo torque-off `ok`.

The safety counters record eight maximum-voltage write attempts, sixteen lock
control write attempts, zero minimum-voltage writes, zero goal-position writes,
and no torque-enable request. No policy, timing probe, home move, or motion ran.

Copied artifact hashes:

- `result.json`:
  `ca72a6b2e2bec9606294d6d54eaaafd762b193ff49c4c35ebca228b937a9609f`;
- `journal.jsonl`:
  `84108006d3069e38934b02f29cd8ae01b9297af560ffc585097ab32965581b88`.

This clears the previously measured all-servo voltage-alarm condition. It does
not pass Gate 2: the last authoritative complete-sweep timing result still
fails the independent `<5 ms` bus-time maximum. The fixed-length SyncRead
collector A/B remains a separate torque-off hardware run and is not inferred
from this configuration result.
