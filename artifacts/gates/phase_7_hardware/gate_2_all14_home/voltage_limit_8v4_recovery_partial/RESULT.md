# 8.4 V alarm recovery partial result

Status: `HALTED_SAFE_PARTIAL_ALL_LOCKS_KNOWN`

The first recovery ran on `/dev/ttyS1` from exact commit
`e83cf51864f926b8bff1369d5b81e5389b3d5748`. Its git archive reproduced
SHA-256
`550c89a8aaa217b6c0e11fb80a1cea6b51e227bfb7b51d0351ab9537c4aa868c`
on the workstation and X5. The robot remained on its stand and the UART was
unowned immediately before and after the run.

Preflight reproduced the prior partial state: IDs 20-22 were raw `84,40`; IDs
23 onward were `80,40`. Independent register-55 reads proved IDs 20, 21, and 22
were all locked at raw 1, resolving the first run's only unknown. Those three
were not rewritten.

IDs 23 and 24 completed the full update/relock/clean-alarm sequence. ID 30's
maximum write acknowledgement timed out and its immediate limit readback also
timed out. The tool halted new limit writes, issued an emergency relock, and
received a partial acknowledgement; its independent register-55 read returned
1, so the relock is proven. The final audit then proved the maximum write had
also landed: ID 30 read raw `84,40`, device status 0, and 8.2 V.

The final measured state is therefore:

- raw `84,40`, locked and alarm-clear: IDs 20, 21, 22, 23, 24, 30;
- raw `80,40`, voltage alarm asserted: IDs 31, 32, 33, 10, 11, 12, 14, 13.

Initial/final torque-off returned `ok`; all known unlocked servos were relocked.
The evidence records zero torque-enable requests, zero goal-position writes,
zero minimum-voltage writes, three maximum-voltage write attempts, and no
policy or motion.

Copied artifact hashes:

- `result.json`:
  `f4a55502e729c04a2fc0425c5bf30e878841abcc115665b7df4de928efc94945`;
- `journal.jsonl`:
  `d7b0e20dd8d4ea4e7cc0be58e5c6076f9a91f18a654f34e74db518f1978295f4`.

The next candidate adds exactly three read-only verification attempts. It never
retransmits a limit write. This targets the observed sequence—write ACK timeout,
first read timeout, later successful audit—without masking a disagreement. See
`VOLTAGE_LIMIT_8V4_FINAL_RECOVERY_PRE_REGISTRATION.md`. Gate 2 remains blocked.
