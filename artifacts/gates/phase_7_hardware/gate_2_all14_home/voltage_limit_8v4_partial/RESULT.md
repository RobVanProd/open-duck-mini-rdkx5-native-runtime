# Maximum-voltage alarm configuration partial result

Status: `HALTED_SAFE_PARTIAL_LOCK_AUDIT_REQUIRED`

The authorized torque-off configuration ran on the X5 from exact commit
`ce161b57cd3fb7d393cfcf175ba70b2f74fa10bb` through direct UART1
`/dev/ttyS1`. The deployed git archive reproduced SHA-256
`f1dc534c5f3c5d5b9577d41e2b4867a0ee20547f7c9721e5923a17100e7292ca`
on the workstation and X5. The robot was on its stand; the port was unowned
immediately before the run.

All 14 preflight reads returned raw maximum/minimum `80,40`. Servo 20 was the
canary and completed unlock, maximum write, exact `84,40` readback, relock, and
clean status at 8.3 V. Servo 21 did the same.

Servo 22's maximum-limit write acknowledgement timed out. The fail-closed tool
stopped new limit writes and attempted an emergency relock; that acknowledgement
also timed out. The final read-only audit nevertheless proved that the maximum
write landed: IDs 20, 21, and 22 each read raw `84,40` with device status 0 and
present voltage 8.2-8.3 V. IDs 23 onward remained raw `80,40`, status 1. The
first-run tool did not include register 55 in its final failure audit, so ID
22's lock state is not claimed.

Initial and final all-servo torque-off returned `ok`. The evidence records zero
torque-enable requests, zero goal-position writes, zero minimum-voltage writes,
three maximum-voltage write attempts, and no policy or motion. `/dev/ttyS1` was
closed and unowned after the run.

The partial-state hashes copied from the X5 are:

- `result.json`:
  `9edcfa0fe46f8c6b42199d1864882bf371f843d52c65084c6ec5d128a175e5e7`;
- `journal.jsonl`:
  `ac79b6acc66105acc5fc58ca487b8fed484fda1e93f604c57c12c5bcb5dafb4c`.

No blind retry is permitted. The next action is the separately preregistered
recovery: read and verify/relock the already-targeted IDs first, then resume at
the first remaining 8.0 V unit. A lost acknowledgement can be accepted only
when an immediate independent register read proves the exact requested value.
Gate 2 remains blocked independently.
