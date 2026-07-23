# Gate 4 — Left hip yaw sine tracking

Status: `PASS_REVIEWED`

The frozen Gate 4 sequence ran on 2026-07-19 with the robot supported on its
stand and no policy loaded. The 10,000-tick torque-off preflight passed before
motion was reachable. The independent stage validator then passed the complete
0.25 Hz population before the launcher permitted the 0.5 Hz population.

| Stage | Ticks | Tracking p95 (rad) | Tick p99 / p99.9 (ms) | Bus max (ms) | Failures / bursts |
| --- | ---: | ---: | ---: | ---: | ---: |
| Torque-off preflight | 10,000 | n/a | 20.002752 / 20.009002 | 4.374260 | 0 / 0 |
| 0.03 rad at 0.25 Hz | 10,000 | 0.006940 | 20.002669 / 20.006835 | 4.556593 | 0 / 0 |
| 0.03 rad at 0.5 Hz | 10,000 | 0.009892 | 20.002593 / 20.010044 | 4.574218 | 0 / 0 |

Both moving tracking p95 values are below the frozen `0.011 rad` threshold,
while every timing, bus, failure, burst, alarm, telemetry-completeness, RT, and
final-cutoff requirement is green. All 20,000 moving tracking samples were
fresh. Moving-stage voltage remained within 7.0–8.4 V. Each servo received
714–715 round-robin extended samples per 10,000-tick stage.

The launcher exited zero, restored `schedutil`, released `/dev/ttyS1`, and
confirmed torque-off after all three stages. A post-run board check verified all
27 entries in `board-sha256sums.txt`; the independent validator then reread all
30,000 rows with manifest checking enabled and passed. The 46,109,337-byte raw
directory is preserved in a 1,823,702-byte archive whose board and local
SHA-256 both equal
`ac2fbe32367dcf7d203f9d24064d109e307f0e0a570cfa7d71fe2ce5632b48a0`.

Rob was physically present for the supported run and confirmed afterward that
it "looked good," with nothing weird and smooth motion. That closes the physical
review item and promotes Gate 4 to `PASS_REVIEWED`. This result does not
authorize Gate 5.
